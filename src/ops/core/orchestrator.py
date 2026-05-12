import time
import base64
from pathlib import Path
from typing import Optional

from ops.models.blueprint import AppBlueprint
from ops.models.state import DeploymentPhase, DeploymentState
from ops.models.config import OpsConfig, ProxmoxConfig
from ops.models.network import SubnetConfig
from ops.providers.proxmox import ProxmoxProvider
from ops.providers.database import DatabaseProvider
from ops.providers.infisical import InfisicalProvider
from ops.providers.microvm import MicroVMProvider
from ops.utils.secrets import SecretManager
from ops.utils.network import IPAllocator
from ops.utils.ssh import SSHKeyManager
from ops.utils.templates import TemplateEngine
from ops.utils.safe_shell import quote
from ops.core.config import ConfigManager
from ops.core.state import StateManager
from ops.core.heartbeat import HeartbeatManager
from ops.core.audit import AuditLogger
from ops.deployers.docker import DockerDeployer
from ops.deployers.native import NativeDeployer
from ops.deployers.base import BaseDeployer
from ops.deployers.microvm import MicroVMDeployer
from ops.deployers.nested_firecracker import NestedFirecrackerDeployer


class Orchestrator:
    def __init__(self, config: OpsConfig):
        self.config = config
        # Use the first host as the primary Proxmox provider
        host_config = config.hosts[0] if config.hosts else None
        if not host_config:
            raise RuntimeError(
                "No Proxmox hosts configured. Run 'ops onboard --host <host>' first."
            )
        self.proxmox = ProxmoxProvider(
            ProxmoxConfig(
                host=host_config.host,
                user=host_config.user,
                token_name=host_config.token_name,
                token_value=host_config.token_value,
                verify_ssl=host_config.verify_ssl,
                node=host_config.node,
            )
        )
        self.db_provider = (
            DatabaseProvider(config.database) if config.database.host else None
        )
        self.infisical = (
            InfisicalProvider(config.infisical) if config.infisical.client_id else None
        )
        self.state_mgr = StateManager()
        self.hb_mgr = HeartbeatManager()
        self.ip_alloc = IPAllocator(
            SubnetConfig(
                network=config.network.subnet,
                gateway=config.network.gateway,
                bridge=config.network.bridge,
            )
        )
        self.template_engine = TemplateEngine()
        self.audit = AuditLogger()
        self._host_name = host_config.name
        self._host_config = host_config
        self._microvm_provider: Optional[MicroVMProvider] = None

    def _audit_start(self, command: str, vmid: Optional[int] = None, details: str = ""):
        self.audit.log(
            command, host=self._host_name, vmid=vmid, status="started", details=details
        )

    def _audit_end(
        self,
        command: str,
        vmid: Optional[int] = None,
        success: bool = True,
        details: str = "",
    ):
        self.audit.log_result(
            command, host=self._host_name, vmid=vmid, success=success, details=details
        )

    def _get_state(self, app_name: str):
        state = self.state_mgr.load(app_name)
        if not state:
            state = DeploymentState(app_name=app_name)
        return state

    def _save_state(self, state: DeploymentState):
        self.state_mgr.save(state)

    def _resolve_secrets(self, app_name: str, blueprint: AppBlueprint):
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, app_name)
        secrets = {}

        for cfg in blueprint.secrets:
            if cfg.type == "infisical" and self.infisical:
                sv = self.infisical.resolve_secret(
                    cfg.name,
                    cfg.path or "/",
                    cfg.key or cfg.name,
                    self.config.defaults.environment,
                )
                secrets[cfg.name] = sv.value
            else:
                sv = secret_mgr.resolve_secret(cfg)
                secrets[cfg.name] = sv.value

        return secrets

    def _get_ssh_key_manager(self, blueprint: AppBlueprint) -> SSHKeyManager:
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        return SSHKeyManager(secret_mgr.secrets_dir)

    # -- Firecracker backend resolution ---------------------------------------

    def _is_firecracker_microvm(
        self, state: DeploymentState, blueprint: AppBlueprint
    ) -> bool:
        """Return True if this deployment uses the pve-microvm backend."""
        if blueprint.deployment.type != "firecracker":
            return False
        return state.backend == "pve-microvm"

    def _is_firecracker_lxc(
        self, state: DeploymentState, blueprint: AppBlueprint
    ) -> bool:
        """Return True if this deployment uses nested Firecracker inside LXC."""
        if blueprint.deployment.type != "firecracker":
            return False
        return state.backend == "lxc"

    def _resolve_firecracker_backend(
        self, state: DeploymentState, blueprint: AppBlueprint
    ) -> None:
        """Probe the target node for pve-microvm availability and cache it."""
        if state.backend:
            print(f"    [INFO] Using cached Firecracker backend: {state.backend}")
            return

        # Default to pve-microvm
        backend = "lxc"
        if blueprint.deployment.firecracker:
            backend = blueprint.deployment.firecracker.backend

        # If blueprint explicitly chooses lxc, respect it without probing
        if backend == "lxc":
            state.backend = "lxc"
            print("    [INFO] Firecracker backend: lxc (configured in blueprint)")
            return

        # Probe node for pve-microvm
        print("    [INFO] Probing target node for pve-microvm...")
        ssh_mgr = self._get_ssh_key_manager(blueprint)
        try:
            client = ssh_mgr.ssh_client(
                "root",
                self._host_config.host,
                self._host_config.user,
                self._host_config.port,
            )
            client.close()
            # If we can connect, create a MicroVMProvider and check
            microvm = self._microvm_provider_for(blueprint)
            if microvm.is_available():
                state.backend = "pve-microvm"
                print("    [OK] pve-microvm detected on node")
            else:
                state.backend = "lxc"
                print(
                    "    [WARN] pve-microvm not found; falling back to lxc nested mode"
                )
        except Exception as e:
            state.backend = "lxc"
            print(f"    [WARN] SSH probe failed ({e}); falling back to lxc nested mode")

    def _microvm_provider_for(self, blueprint: AppBlueprint) -> MicroVMProvider:
        """Return a cached MicroVMProvider for the target node."""
        if self._microvm_provider is None:
            ssh_mgr = self._get_ssh_key_manager(blueprint)
            private_key = ssh_mgr.get_private_key("root")
            self._microvm_provider = MicroVMProvider(
                hostname=self._host_config.host,
                username=self._host_config.user,
                port=self._host_config.port,
                private_key_path=private_key,
            )
        return self._microvm_provider

    def deploy(
        self,
        app_name: str,
        blueprint: AppBlueprint,
        force: bool = False,
        no_teardown: bool = False,
        cluster: bool = False,
        cluster_transport: Optional[str] = None,
    ):
        state = self._get_state(app_name)

        if state.completed and not force:
            print(f"[INFO] {app_name} is already deployed. Use --force to redeploy.")
            return

        if force:
            # Reset state for full redeploy
            state = DeploymentState(app_name=app_name)

        self._audit_start(
            "deploy", vmid=state.vmid, details=f"blueprint={blueprint.name}"
        )
        try:
            self._phase_preflight(state, blueprint)
            self._phase_provision(state, blueprint)
            self._phase_harden(state, blueprint)
            self._phase_install(state, blueprint)
            self._phase_database(state, blueprint)
            self._phase_deploy(state, blueprint)
            self._phase_finalize(state, blueprint)

            state.completed = True
            self._save_state(state)
            self._audit_end("deploy", vmid=state.vmid, success=True)
            print(f"[OK] {app_name} deployed successfully at {state.ip}")

        except Exception as e:
            state.add_error(str(e))
            self._save_state(state)
            self._audit_end("deploy", vmid=state.vmid, success=False, details=str(e))
            print(f"[ERROR] Deployment failed: {e}")

            auto_teardown = (
                not no_teardown and self.config.defaults.auto_teardown_on_failure
            )
            if auto_teardown:
                print("[INFO] Auto-teardown enabled. Cleaning up...")
                self.teardown(app_name, blueprint, skip_backup=True)
            raise

    def _phase_preflight(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.PREFLIGHT):
            print("[SKIP] Preflight already complete")
            return

        print("--> [PREFLIGHT] Validating and preparing...")

        # Resolve template (works with restricted API tokens — no storage perms needed)
        template_name = self.config.defaults.template
        template_volid = self.proxmox.resolve_template_volid(
            template_name, self.config.storage.pool, self.proxmox._get_node()
        )
        if template_volid:
            print(f"    [INFO] Template resolved: {template_volid}")
        else:
            print(
                f"    [WARN] Template '{template_name}' could not be resolved via API. Will attempt at provision time."
            )

        # Allocate VMID and IP
        used_vmids = self.proxmox.get_used_vmids()
        used_ips = self.proxmox.get_used_ips()

        vmid = blueprint.container.vmid
        if vmid is None:
            vmid = self.ip_alloc.suggest_vmid(used_vmids)
        elif vmid in used_vmids and not state.vmid:
            raise ValueError(f"VMID {vmid} is already in use")

        ip = blueprint.container.ip
        if ip is None:
            ip = self.ip_alloc.allocate(vmid, used_ips)
        elif not self.ip_alloc.subnet.is_ip_available(ip, used_ips):
            raise ValueError(f"IP {ip} is not available")

        state.vmid = vmid
        state.ip = str(ip)
        state.node = self.proxmox._get_node()

        # Resolve secrets
        secrets = self._resolve_secrets(blueprint.name, blueprint)
        state.secrets_resolved = secrets

        # Firecracker backend probe
        if blueprint.deployment.type == "firecracker":
            self._resolve_firecracker_backend(state, blueprint)

        state.mark_phase_complete(DeploymentPhase.PREFLIGHT)
        self._save_state(state)
        print(f"    [OK] VMID={vmid}, IP={ip}")

    def _phase_provision(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.PROVISION):
            print("[SKIP] Provision already complete")
            return

        # pve-microvm path: skip LXC provisioning entirely
        if self._is_firecracker_microvm(state, blueprint):
            print("--> [PROVISION] Skipping LXC provision (microVM backend)")
            state.mark_phase_complete(DeploymentPhase.PROVISION)
            self._save_state(state)
            print("    [OK] MicroVM backend — no LXC container needed")
            return

        assert state.vmid is not None
        assert state.node is not None
        print("--> [PROVISION] Creating LXC container...")

        # Resolve template volid. Works with restricted tokens (no storage perms needed).
        template_name = self.config.defaults.template
        template_volid = self.proxmox.resolve_template_volid(
            template_name, self.config.storage.pool, state.node
        )
        if not template_volid:
            # Last resort: ask user to run pveam manually
            raise RuntimeError(
                f"Template '{template_name}' not found in storage '{self.config.storage.pool}'.\n"
                f"Run on your Proxmox host:\n"
                f"  pveam list {self.config.storage.pool}\n"
                f"  pveam download {self.config.storage.pool} {template_name}"
            )

        # Compute CIDR using actual subnet prefix
        net = self.config.network.subnet
        prefix = net.prefixlen

        # Create LXC (no root password via API — SSH keys only)
        self.proxmox.create_lxc(
            vmid=state.vmid,
            hostname=blueprint.container.hostname,
            template=template_volid,
            cores=blueprint.container.cores,
            memory=blueprint.container.memory,
            disk=blueprint.container.disk,
            storage=self.config.storage.pool,
            bridge=blueprint.network.bridge or self.config.network.bridge,
            ip_cidr=f"{state.ip}/{prefix}",
            gateway=str(self.config.network.gateway),
            dns=" ".join(self.config.network.dns),
            node=state.node,
        )

        # If nested Firecracker, inject raw LXC config for /dev/kvm passthrough
        if self._is_firecracker_lxc(state, blueprint):
            print("    [INFO] Injecting LXC config for /dev/kvm passthrough...")
            self.proxmox.patch_lxc_config(
                state.vmid,
                {
                    "lxc.cgroup2.devices.allow": "c 10:232 rwm",
                    "lxc.mount.entry": "/dev/kvm dev/kvm none bind,optional,create=file",
                },
                node=state.node,
            )

        self.proxmox.start_lxc(state.vmid, state.node)

        # Wait for container to boot (systemd-networkd needs time to start)
        print("    [INFO] Waiting for container to boot...")
        if not self.proxmox.wait_for_boot(state.vmid, timeout=120, node=state.node):
            print(
                "    [WARN] Container did not signal systemd readiness. Proceeding anyway..."
            )

        # Wait for network
        print("    [INFO] Waiting for network...")
        if not self.proxmox.wait_for_network(state.vmid, timeout=120, node=state.node):
            raise RuntimeError("Container did not get network connectivity")

        # Base tuning
        self.proxmox.exec(state.vmid, "timedatectl set-timezone UTC", node=state.node)

        state.mark_phase_complete(DeploymentPhase.PROVISION)
        self._save_state(state)
        print(f"    [OK] Container {state.vmid} running at {state.ip}")

    def _phase_harden(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.HARDEN):
            print("[SKIP] Harden already complete")
            return

        # pve-microvm path: skip hardening (microVMs are immutable guests)
        if self._is_firecracker_microvm(state, blueprint):
            print("--> [HARDEN] Skipping (microVM backend)")
            state.mark_phase_complete(DeploymentPhase.HARDEN)
            self._save_state(state)
            return

        assert state.vmid is not None
        assert state.node is not None
        print("--> [HARDEN] Securing container...")

        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        ssh_mgr = SSHKeyManager(secret_mgr.secrets_dir)

        # Generate SSH keys
        root_priv, root_pub = ssh_mgr.generate_keypair("root")
        app_priv, app_pub = ssh_mgr.generate_keypair("app")

        # Push root public key
        self.proxmox.exec(
            state.vmid, "mkdir -p /root/.ssh && chmod 700 /root/.ssh", node=state.node
        )
        self.proxmox.push_file(
            state.vmid, root_pub, "/root/.ssh/authorized_keys", node=state.node
        )
        self.proxmox.exec(
            state.vmid, "chmod 600 /root/.ssh/authorized_keys", node=state.node
        )

        # Harden sshd
        sshd_config = """Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server
"""
        self.proxmox.exec(
            state.vmid,
            f"cat > /etc/ssh/sshd_config <<'EOF'\n{sshd_config}EOF",
            node=state.node,
        )
        self.proxmox.exec(
            state.vmid,
            "ssh-keygen -A >/dev/null 2>&1; systemctl restart sshd",
            node=state.node,
        )

        # Create app user (for native deployments only)
        if blueprint.deployment.type == "native":
            native = blueprint.deployment.native
            assert native is not None
            self.proxmox.exec(
                state.vmid,
                f"id {quote(native.app_user)} >/dev/null 2>&1 || useradd -r -m -d {quote(native.app_dir)} -s /bin/bash {quote(native.app_user)}",
                node=state.node,
            )
            # Push app user public key
            self.proxmox.exec(
                state.vmid,
                f"mkdir -p /home/{quote(native.app_user)}/.ssh && chmod 700 /home/{quote(native.app_user)}/.ssh",
                node=state.node,
            )
            self.proxmox.push_file(
                state.vmid,
                app_pub,
                f"/home/{native.app_user}/.ssh/authorized_keys",
                node=state.node,
            )
            self.proxmox.exec(
                state.vmid,
                f"chown -R {quote(native.app_user)}:{quote(native.app_user)} /home/{quote(native.app_user)}/.ssh && chmod 600 /home/{native.app_user}/.ssh/authorized_keys",
                node=state.node,
            )

        state.mark_phase_complete(DeploymentPhase.HARDEN)
        self._save_state(state)
        print("    [OK] SSH hardened, keys generated")

    def _phase_install(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.INSTALL):
            print("[SKIP] Install already complete")
            return

        # pve-microvm path: skip install (image is baked into template)
        if self._is_firecracker_microvm(state, blueprint):
            print("--> [INSTALL] Skipping (microVM backend)")
            state.mark_phase_complete(DeploymentPhase.INSTALL)
            self._save_state(state)
            return

        assert state.vmid is not None
        assert state.node is not None
        print("--> [INSTALL] Installing dependencies...")

        # Install system packages
        packages = blueprint.dependencies.get("packages", [])
        if packages:
            pkg_str = " ".join(packages)
            self.proxmox.exec(
                state.vmid,
                f"export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get install -y {pkg_str}",
                node=state.node,
            )

        # Install runtime-specific dependencies
        if blueprint.deployment.type == "docker":
            self._install_docker(state, blueprint)
        elif blueprint.deployment.type == "native":
            self._install_native_runtime(state, blueprint)
        elif blueprint.deployment.type == "none":
            print("    [INFO] No runtime to install (type=none)")

        if blueprint.dependencies.get("install_podman"):
            self._install_podman(state, blueprint)

        state.mark_phase_complete(DeploymentPhase.INSTALL)
        self._save_state(state)
        print("    [OK] Dependencies installed")

    def _install_docker(self, state: DeploymentState, blueprint: AppBlueprint):
        assert state.vmid is not None
        assert state.node is not None
        result = self.proxmox.exec(state.vmid, "docker --version", node=state.node)
        if result.exit_code == 0:
            return

        self.proxmox.exec(
            state.vmid,
            "curl -fsSL https://get.docker.com | sh || true",
            node=state.node,
        )
        self.proxmox.exec(
            state.vmid,
            "systemctl enable docker && systemctl start docker",
            node=state.node,
        )

    def _install_native_runtime(self, state: DeploymentState, blueprint: AppBlueprint):
        assert state.vmid is not None
        assert state.node is not None
        runtime = blueprint.deployment.runtime
        version = blueprint.deployment.runtime_version

        if runtime == "nodejs" and version:
            result = self.proxmox.exec(
                state.vmid, f"node --version | grep -q 'v{version}'", node=state.node
            )
            if result.exit_code == 0:
                return

            self.proxmox.exec(
                state.vmid,
                f"curl -fsSL https://deb.nodesource.com/setup_{version}.x | bash -",
                node=state.node,
            )
            self.proxmox.exec(
                state.vmid,
                "export DEBIAN_FRONTEND=noninteractive; apt-get install -y nodejs",
                node=state.node,
            )
            self.proxmox.exec(
                state.vmid,
                "corepack enable && corepack prepare pnpm@latest --activate",
                node=state.node,
            )

        elif runtime == "python" and version:
            result = self.proxmox.exec(
                state.vmid, f"python{version} --version", node=state.node
            )
            if result.exit_code == 0:
                return
            self.proxmox.exec(
                state.vmid,
                f"apt-get install -y python{version} python{version}-venv python{version}-pip",
                node=state.node,
            )

    def _install_podman(self, state: DeploymentState, blueprint: AppBlueprint):
        assert state.vmid is not None
        assert state.node is not None
        result = self.proxmox.exec(state.vmid, "podman --version", node=state.node)
        if result.exit_code == 0:
            return

        self.proxmox.exec(
            state.vmid,
            "curl -fsSL https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/unstable/xUbuntu_24.04/Release.key | gpg --dearmor > /etc/apt/keyrings/podman.gpg && chmod a+r /etc/apt/keyrings/podman.gpg",
            node=state.node,
        )
        self.proxmox.exec(
            state.vmid,
            "echo 'deb [signed-by=/etc/apt/keyrings/podman.gpg] https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/unstable/xUbuntu_24.04/ /' | tee /etc/apt/sources.list.d/podman.list",
            node=state.node,
        )
        self.proxmox.exec(
            state.vmid,
            "export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get install -y podman",
            node=state.node,
        )

    def _phase_database(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.DATABASE):
            print("[SKIP] Database already configured")
            return

        if not blueprint.database.enabled or not self.db_provider:
            return

        print("--> [DATABASE] Provisioning database...")

        db_name = blueprint.database.name or f"{blueprint.name}_db"
        db_user = f"{blueprint.name}_user"

        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        db_pass = secret_mgr.generate_secret("db_password", 32)

        self.db_provider.ensure_database(db_name)
        self.db_provider.ensure_user(db_user, db_pass, db_name)

        # Store DB credentials in state secrets
        state.secrets_resolved["DB_NAME"] = db_name
        state.secrets_resolved["DB_USER"] = db_user
        state.secrets_resolved["DB_PASSWORD"] = db_pass

        state.mark_phase_complete(DeploymentPhase.DATABASE)
        self._save_state(state)
        print(f"    [OK] Database {db_name} ready")

    def _phase_deploy(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.DEPLOY):
            print("[SKIP] Deploy already complete")
            return

        assert state.vmid is not None
        assert state.node is not None
        print("--> [DEPLOY] Deploying application...")

        # Build template context with nested namespace support
        env = dict(blueprint.environment)
        env.update(state.secrets_resolved)

        context = {
            "environment": blueprint.environment,
            "secrets": state.secrets_resolved,
            "ip": state.ip,
            "name": blueprint.name,
            "hostname": blueprint.container.hostname,
            "vmid": state.vmid,
            **state.secrets_resolved,  # flat for backward compat
            **blueprint.environment,  # flat for backward compat
        }

        # Push templates + deploy (skip for microVM and vanilla)
        if blueprint.deployment.type == "none":
            print("    [INFO] No app to deploy (type=none)")
        elif self._is_firecracker_microvm(state, blueprint):
            # MicroVM path: no templates; deploy via MicroVMDeployer
            microvm = self._microvm_provider_for(blueprint)
            deployer: BaseDeployer = MicroVMDeployer(microvm)
            deployer.deploy(self.proxmox, state.node, state.vmid, blueprint, env)
        elif self._is_firecracker_lxc(state, blueprint):
            # Nested Firecracker path: push templates into LXC
            for tpl in blueprint.templates:
                rendered = self.template_engine.render_file(tpl.source, context)
                local_tmp = Path(f"/tmp/ops_{blueprint.name}_{Path(tpl.dest).name}")
                local_tmp.write_text(rendered)
                self.proxmox.push_file(
                    state.vmid, str(local_tmp), tpl.dest, node=state.node
                )
                self.proxmox.exec(
                    state.vmid, f"chmod {tpl.mode} {tpl.dest}", node=state.node
                )
                local_tmp.unlink()
            # Deploy nested Firecracker
            deployer = NestedFirecrackerDeployer()
            deployer.deploy(self.proxmox, state.node, state.vmid, blueprint, env)
        else:
            # Standard LXC paths (docker, native, wasm)
            for tpl in blueprint.templates:
                rendered = self.template_engine.render_file(tpl.source, context)
                local_tmp = Path(f"/tmp/ops_{blueprint.name}_{Path(tpl.dest).name}")
                local_tmp.write_text(rendered)
                self.proxmox.push_file(
                    state.vmid, str(local_tmp), tpl.dest, node=state.node
                )
                self.proxmox.exec(
                    state.vmid, f"chmod {tpl.mode} {tpl.dest}", node=state.node
                )
                if blueprint.deployment.type == "native":
                    assert blueprint.deployment.native is not None
                    self.proxmox.exec(
                        state.vmid,
                        f"chown {blueprint.deployment.native.app_user}:{blueprint.deployment.native.app_user} {tpl.dest}",
                        node=state.node,
                    )
                local_tmp.unlink()

            # Deploy using strategy
            if blueprint.deployment.type == "docker":
                deployer = DockerDeployer()
                deployer.deploy(self.proxmox, state.node, state.vmid, blueprint, env)
            elif blueprint.deployment.type == "wasm":
                from ops.deployers.wasm import WasmDeployer

                deployer = WasmDeployer()
                deployer.deploy(self.proxmox, state.node, state.vmid, blueprint, env)
            else:
                deployer = NativeDeployer()
                deployer.deploy(self.proxmox, state.node, state.vmid, blueprint, env)

        state.mark_phase_complete(DeploymentPhase.DEPLOY)
        self._save_state(state)
        print("    [OK] Application deployed")

    def _phase_finalize(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.FINALIZE):
            print("[SKIP] Finalize already complete")
            return

        assert state.vmid is not None
        assert state.ip is not None
        assert state.node is not None
        print("--> [FINALIZE] Running health checks...")

        # Health check
        health_result = self.hb_mgr.run_health_check(
            blueprint, state.vmid, state.ip, self.proxmox, state.node
        )

        # Generate SSH key paths for heartbeat
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        ssh_mgr = SSHKeyManager(secret_mgr.secrets_dir)
        ssh_keys = {
            "root": ssh_mgr.get_private_key("root"),
            "app": ssh_mgr.get_private_key("app"),
        }

        self.hb_mgr.generate_heartbeat(
            blueprint.name, blueprint, state, health_result, ssh_keys
        )

        if health_result.get("status") == "skipped":
            print("    [INFO] Health check skipped (not enabled)")
        elif health_result.get("status") != "ok":
            print(f"    [WARN] Health check failed: {health_result.get('error')}")
        else:
            print(f"    [OK] Health check passed: {health_result.get('url')}")

        state.mark_phase_complete(DeploymentPhase.FINALIZE)
        self._save_state(state)
        print("    [OK] Deployment finalized")

    def teardown(self, app_name: str, blueprint=None, skip_backup: bool = False):
        state = self._get_state(app_name)

        if state.vmid is None:
            print(f"[WARN] No container found for {app_name}")
            return

        print(f"--> [TEARDOWN] Destroying {app_name} (VMID {state.vmid})...")

        # Backup before destroy
        if not skip_backup:
            self._backup_before_teardown(state, blueprint)

        # Stop and destroy
        try:
            if blueprint and blueprint.deployment.type == "firecracker":
                if state.backend == "pve-microvm":
                    microvm = self._microvm_provider_for(blueprint)
                    microvm.stop_vm(state.vmid)
                    microvm.destroy_vm(state.vmid)
                else:
                    self.proxmox.stop_lxc(state.vmid, state.node)
                    time.sleep(3)
                    self.proxmox.destroy_lxc(state.vmid, state.node)
            else:
                self.proxmox.stop_lxc(state.vmid, state.node)
                time.sleep(3)
                self.proxmox.destroy_lxc(state.vmid, state.node)
        except Exception as e:
            print(f"    [WARN] Error during destroy: {e}")

        # Clean up state and secrets
        self.state_mgr.delete(app_name)

        config_mgr = ConfigManager()
        if blueprint:
            secret_mgr = SecretManager(config_mgr, blueprint.name)
            secret_mgr.cleanup()

        print(f"    [OK] {app_name} teardown complete")

    def _backup_before_teardown(self, state: DeploymentState, blueprint):
        if not blueprint:
            return
        assert state.vmid is not None
        assert state.node is not None
        backup_dir = Path("~/.ops/backups").expanduser()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{blueprint.name}_{timestamp}.tar.gz"
        remote_backup_path = f"/tmp/backup_ops_{blueprint.name}_{timestamp}.tar.gz"

        if blueprint.deployment.type == "docker":
            self.proxmox.exec(
                state.vmid,
                f"cd /opt/{blueprint.name} && docker compose down",
                node=state.node,
            )
            self.proxmox.exec(
                state.vmid,
                f"tar czf {remote_backup_path} -C /opt/{blueprint.name} . || true",
                node=state.node,
            )
        elif blueprint.deployment.type == "native":
            app_dir = (
                blueprint.deployment.native.app_dir
                if blueprint.deployment.native
                else "/opt/app"
            )
            self.proxmox.exec(
                state.vmid,
                f"tar czf {remote_backup_path} -C {app_dir} . || true",
                node=state.node,
            )

        # Pull backup from container
        try:
            result = self.proxmox.exec(
                state.vmid, f"cat {remote_backup_path} | base64", node=state.node
            )
            if result.stdout:
                backup_path.write_bytes(base64.b64decode(result.stdout))
                print(f"    [OK] Backup saved to {backup_path}")
        except Exception:
            pass

    def restart_service(self, app_name: str, blueprint: AppBlueprint):
        state = self._get_state(app_name)
        if state.vmid is None:
            raise RuntimeError(f"No container found for {app_name}")
        assert state.node is not None

        # Sync secrets back to state before restart
        self._sync_secrets_to_state(app_name, state)

        if blueprint.deployment.type == "firecracker":
            if state.backend == "pve-microvm":
                microvm = self._microvm_provider_for(blueprint)
                deployer: BaseDeployer = MicroVMDeployer(microvm)
                deployer.restart_service(
                    self.proxmox, state.node, state.vmid, blueprint
                )
                return
            elif state.backend == "lxc":
                deployer = NestedFirecrackerDeployer()
                deployer.restart_service(
                    self.proxmox, state.node, state.vmid, blueprint
                )
                return

        if blueprint.deployment.type == "docker":
            deployer = DockerDeployer()
        elif blueprint.deployment.type == "native":
            deployer = NativeDeployer()
        else:
            print("[INFO] No service to restart (type=none)")
            return
        deployer.restart_service(self.proxmox, state.node, state.vmid, blueprint)

    def _sync_secrets_to_state(self, app_name: str, state: DeploymentState):
        """Reload current secrets from disk into state file."""
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, app_name)
        disk_secrets = secret_mgr.get_all_secrets()
        state.secrets_resolved.update(disk_secrets)

    def get_logs(
        self,
        app_name: str,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ):
        state = self._get_state(app_name)
        if state.vmid is None:
            raise RuntimeError(f"No container found for {app_name}")
        assert state.node is not None

        if blueprint.deployment.type == "firecracker":
            if state.backend == "pve-microvm":
                microvm = self._microvm_provider_for(blueprint)
                deployer: BaseDeployer = MicroVMDeployer(microvm)
                return deployer.get_logs(
                    self.proxmox, state.node, state.vmid, blueprint, follow, lines
                )
            elif state.backend == "lxc":
                deployer = NestedFirecrackerDeployer()
                return deployer.get_logs(
                    self.proxmox, state.node, state.vmid, blueprint, follow, lines
                )

        if blueprint.deployment.type == "docker":
            deployer = DockerDeployer()
        elif blueprint.deployment.type == "native":
            deployer = NativeDeployer()
        else:
            return "No logs available for vanilla containers"
        return deployer.get_logs(
            self.proxmox, state.node, state.vmid, blueprint, follow, lines
        )

    def sync(self, app_name: str, blueprint: AppBlueprint):
        state = self._get_state(app_name)
        if state.vmid is None:
            raise RuntimeError(f"No container found for {app_name}")

        if blueprint.deployment.type == "none":
            print("[INFO] Nothing to sync for vanilla containers")
            return

        # MicroVMs are immutable; sync is not applicable
        if self._is_firecracker_microvm(state, blueprint):
            print(
                "[WARN] Sync is not supported for microVM deployments (immutable guest)"
            )
            return

        print(f"--> [SYNC] Updating {app_name}...")

        # Reload secrets from disk
        self._sync_secrets_to_state(app_name, state)

        env = dict(blueprint.environment)
        env.update(state.secrets_resolved)

        context = {
            "environment": blueprint.environment,
            "secrets": state.secrets_resolved,
            "ip": state.ip,
            "name": blueprint.name,
            "hostname": blueprint.container.hostname,
            "vmid": state.vmid,
            **blueprint.environment,
            **state.secrets_resolved,
        }

        for tpl in blueprint.templates:
            rendered = self.template_engine.render_file(tpl.source, context)
            local_tmp = Path(f"/tmp/ops_{blueprint.name}_{Path(tpl.dest).name}")
            local_tmp.write_text(rendered)
            self.proxmox.push_file(
                state.vmid, str(local_tmp), tpl.dest, node=state.node
            )
            local_tmp.unlink()

        # Restart service
        self.restart_service(app_name, blueprint)
        print("    [OK] Sync complete")
