import time
from pathlib import Path
from typing import Dict, List, Optional

from ..models.blueprint import AppBlueprint
from ..models.state import DeploymentPhase, DeploymentState
from ..models.config import OpsConfig
from ..providers.proxmox import ProxmoxProvider
from ..providers.database import DatabaseProvider
from ..providers.infisical import InfisicalProvider
from ..utils.secrets import SecretManager
from ..utils.network import IPAllocator
from ..utils.ssh import SSHKeyManager
from ..utils.templates import TemplateEngine
from ..core.config import ConfigManager
from ..core.state import StateManager
from ..core.heartbeat import HeartbeatManager
from ..deployers.docker import DockerDeployer
from ..deployers.native import NativeDeployer


class Orchestrator:
    def __init__(self, config: OpsConfig):
        self.config = config
        self.proxmox = ProxmoxProvider(config.proxmox)
        self.db_provider = DatabaseProvider(config.database) if config.database.host else None
        self.infisical = InfisicalProvider(config.infisical) if config.infisical.client_id else None
        self.state_mgr = StateManager()
        self.hb_mgr = HeartbeatManager()
        self.ip_alloc = IPAllocator(config.network)
        self.template_engine = TemplateEngine()

    def _get_state(self, app_name: str) -> DeploymentState:
        state = self.state_mgr.load(app_name)
        if not state:
            state = DeploymentState(app_name=app_name)
        return state

    def _save_state(self, state: DeploymentState):
        self.state_mgr.save(state)

    def _resolve_secrets(self, app_name: str, blueprint: AppBlueprint) -> Dict[str, str]:
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, app_name)
        secrets = {}

        for cfg in blueprint.secrets:
            if cfg.type == "infisical" and self.infisical:
                sv = self.infisical.resolve_secret(
                    cfg.name, cfg.path or "/", cfg.key or cfg.name, self.config.defaults.environment
                )
                secrets[cfg.name] = sv.value
            else:
                sv = secret_mgr.resolve_secret(cfg)
                secrets[cfg.name] = sv.value

        return secrets

    def deploy(self, app_name: str, blueprint: AppBlueprint, force: bool = False, no_teardown: bool = False):
        state = self._get_state(app_name)

        if state.completed and not force:
            print(f"[INFO] {app_name} is already deployed. Use --force to redeploy.")
            return

        if force:
            # Reset state for full redeploy
            state = DeploymentState(app_name=app_name)

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
            print(f"[OK] {app_name} deployed successfully at {state.ip}")

        except Exception as e:
            state.add_error(str(e))
            self._save_state(state)
            print(f"[ERROR] Deployment failed: {e}")

            auto_teardown = not no_teardown and self.config.defaults.auto_teardown_on_failure
            if auto_teardown:
                print("[INFO] Auto-teardown enabled. Cleaning up...")
                self.teardown(app_name, blueprint, skip_backup=True)
            raise

    def _phase_preflight(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.PREFLIGHT):
            print("[SKIP] Preflight already complete")
            return

        print("--> [PREFLIGHT] Validating and preparing...")

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

        state.mark_phase_complete(DeploymentPhase.PREFLIGHT)
        self._save_state(state)
        print(f"    [OK] VMID={vmid}, IP={ip}")

    def _phase_provision(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.PROVISION):
            print("[SKIP] Provision already complete")
            return

        print("--> [PROVISION] Creating LXC container...")

        # Ensure template exists
        templates = self.proxmox.get_available_templates(self.config.storage.pool)
        template_name = self.config.defaults.template
        template_volid = None
        for t in templates:
            if template_name in t:
                template_volid = t
                break

        if not template_volid:
            raise RuntimeError(f"Template '{template_name}' not found in storage '{self.config.storage.pool}'")

        # Generate root password
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        root_pw = secret_mgr.generate_secret("root_password", 32)

        # Create LXC
        self.proxmox.create_lxc(
            vmid=state.vmid,
            hostname=blueprint.container.hostname,
            template=template_volid,
            cores=blueprint.container.cores,
            memory=blueprint.container.memory,
            disk=blueprint.container.disk,
            storage=self.config.storage.pool,
            bridge=blueprint.network.bridge or self.config.network.bridge,
            ip_cidr=f"{state.ip}/24",
            gateway=str(self.config.network.gateway),
            password=root_pw,
            dns=" ".join(self.config.network.dns),
            node=state.node,
        )

        self.proxmox.start_lxc(state.vmid, state.node)

        # Wait for network
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

        print("--> [HARDEN] Securing container...")

        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        ssh_mgr = SSHKeyManager(secret_mgr.secrets_dir)

        # Generate SSH keys
        root_priv, root_pub = ssh_mgr.generate_keypair("root")
        app_priv, app_pub = ssh_mgr.generate_keypair("app")

        # Push root public key
        self.proxmox.exec(state.vmid, "mkdir -p /root/.ssh && chmod 700 /root/.ssh", node=state.node)
        self.proxmox.push_file(state.vmid, root_pub, "/root/.ssh/authorized_keys", node=state.node)
        self.proxmox.exec(state.vmid, "chmod 600 /root/.ssh/authorized_keys", node=state.node)

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
        # Write sshd config via exec
        self.proxmox.exec(
            state.vmid,
            f"cat > /etc/ssh/sshd_config <<'EOF'\n{sshd_config}EOF",
            node=state.node,
        )
        self.proxmox.exec(state.vmid, "ssh-keygen -A >/dev/null 2>>1; systemctl restart sshd", node=state.node)

        # Create app user (for native deployments)
        if blueprint.deployment.type == "native":
            native = blueprint.deployment.native
            self.proxmox.exec(
                state.vmid,
                f"id {native.app_user} >/dev/null 2>>1 || useradd -r -m -d {native.app_dir} -s /bin/bash {native.app_user}",
                node=state.node,
            )
            # Push app user public key
            self.proxmox.exec(state.vmid, f"mkdir -p /home/{native.app_user}/.ssh && chmod 700 /home/{native.app_user}/.ssh", node=state.node)
            self.proxmox.push_file(state.vmid, app_pub, f"/home/{native.app_user}/.ssh/authorized_keys", node=state.node)
            self.proxmox.exec(state.vmid, f"chown -R {native.app_user}:{native.app_user} /home/{native.app_user}/.ssh && chmod 600 /home/{native.app_user}/.ssh/authorized_keys", node=state.node)

        state.mark_phase_complete(DeploymentPhase.HARDEN)
        self._save_state(state)
        print("    [OK] SSH hardened, keys generated")

    def _phase_install(self, state: DeploymentState, blueprint: AppBlueprint):
        if state.is_phase_complete(DeploymentPhase.INSTALL):
            print("[SKIP] Install already complete")
            return

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

        if blueprint.dependencies.get("install_podman"):
            self._install_podman(state, blueprint)

        state.mark_phase_complete(DeploymentPhase.INSTALL)
        self._save_state(state)
        print("    [OK] Dependencies installed")

    def _install_docker(self, state: DeploymentState, blueprint: AppBlueprint):
        # Check if docker is installed
        result = self.proxmox.exec(state.vmid, "docker --version", node=state.node)
        if result.exit_code == 0:
            return

        self.proxmox.exec(
            state.vmid,
            "curl -fsSL https://get.docker.com | sh || true",
            node=state.node,
        )
        self.proxmox.exec(state.vmid, "systemctl enable docker && systemctl start docker", node=state.node)

    def _install_native_runtime(self, state: DeploymentState, blueprint: AppBlueprint):
        runtime = blueprint.deployment.runtime
        version = blueprint.deployment.runtime_version

        if runtime == "nodejs" and version:
            # Check if already installed
            result = self.proxmox.exec(state.vmid, f"node --version | grep -q 'v{version}'", node=state.node)
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
            # Enable pnpm
            self.proxmox.exec(state.vmid, "corepack enable && corepack prepare pnpm@latest --activate", node=state.node)

        elif runtime == "python" and version:
            result = self.proxmox.exec(state.vmid, f"python{version} --version", node=state.node)
            if result.exit_code == 0:
                return
            self.proxmox.exec(
                state.vmid,
                f"apt-get install -y python{version} python{version}-venv python{version}-pip",
                node=state.node,
            )

    def _install_podman(self, state: DeploymentState, blueprint: AppBlueprint):
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

        print("--> [DEPLOY] Deploying application...")

        # Prepare environment variables
        env = dict(blueprint.environment)
        env.update(state.secrets_resolved)

        # Push templates
        for tpl in blueprint.templates:
            # Render template locally
            rendered = self.template_engine.render_file(tpl.source, env)
            local_tmp = Path(f"/tmp/ops_{blueprint.name}_{Path(tpl.dest).name}")
            local_tmp.write_text(rendered)
            self.proxmox.push_file(state.vmid, str(local_tmp), tpl.dest, node=state.node)
            self.proxmox.exec(state.vmid, f"chmod {tpl.mode} {tpl.dest}", node=state.node)
            if blueprint.deployment.type == "native":
                self.proxmox.exec(
                    state.vmid,
                    f"chown {blueprint.deployment.native.app_user}:{blueprint.deployment.native.app_user} {tpl.dest}",
                    node=state.node,
                )
            local_tmp.unlink()

        # Deploy using strategy
        if blueprint.deployment.type == "docker":
            deployer = DockerDeployer()
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

        print("--> [FINALIZE] Running health checks...")

        # Health check
        health_result = self.hb_mgr.run_health_check(blueprint, state.vmid, state.ip, self.proxmox, state.node)

        # Generate SSH key paths for heartbeat
        config_mgr = ConfigManager()
        secret_mgr = SecretManager(config_mgr, blueprint.name)
        ssh_mgr = SSHKeyManager(secret_mgr.secrets_dir)
        ssh_keys = {
            "root": ssh_mgr.get_private_key("root"),
            "app": ssh_mgr.get_private_key("app"),
        }

        heartbeat = self.hb_mgr.generate_heartbeat(
            blueprint.name, blueprint, state, health_result, ssh_keys
        )

        if health_result.get("status") != "ok":
            print(f"    [WARN] Health check failed: {health_result.get('error')}")
        else:
            print(f"    [OK] Health check passed: {health_result.get('url')}")

        state.mark_phase_complete(DeploymentPhase.FINALIZE)
        self._save_state(state)
        print("    [OK] Deployment finalized")

    def teardown(self, app_name: str, blueprint: Optional[AppBlueprint] = None, skip_backup: bool = False):
        state = self._get_state(app_name)

        if not state.vmid:
            print(f"[WARN] No container found for {app_name}")
            return

        print(f"--> [TEARDOWN] Destroying {app_name} (VMID {state.vmid})...")

        # Backup before destroy
        if not skip_backup:
            self._backup_before_teardown(state, blueprint)

        # Stop and destroy
        try:
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

    def _backup_before_teardown(self, state: DeploymentState, blueprint: Optional[AppBlueprint]):
        if not blueprint:
            return
        backup_dir = Path("~/.ops/backups").expanduser()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{blueprint.name}_{timestamp}.tar.gz"

        if blueprint.deployment.type == "docker":
            self.proxmox.exec(state.vmid, f"cd /opt/{blueprint.name} && docker compose down", node=state.node)
            self.proxmox.exec(
                state.vmid,
                f"tar czf /tmp/backup.tar.gz -C /opt/{blueprint.name} . || true",
                node=state.node,
            )
        elif blueprint.deployment.type == "native":
            app_dir = blueprint.deployment.native.app_dir if blueprint.deployment.native else "/opt/app"
            self.proxmox.exec(
                state.vmid,
                f"tar czf /tmp/backup.tar.gz -C {app_dir} . || true",
                node=state.node,
            )

        # Pull backup from container
        try:
            result = self.proxmox.exec(state.vmid, "cat /tmp/backup.tar.gz | base64", node=state.node)
            if result.stdout:
                import base64
                backup_path.write_bytes(base64.b64decode(result.stdout))
                print(f"    [OK] Backup saved to {backup_path}")
        except Exception:
            pass

    def restart_service(self, app_name: str, blueprint: AppBlueprint):
        state = self._get_state(app_name)
        if not state.vmid:
            raise RuntimeError(f"No container found for {app_name}")

        if blueprint.deployment.type == "docker":
            deployer = DockerDeployer()
        else:
            deployer = NativeDeployer()
        deployer.restart_service(self.proxmox, state.node, state.vmid, blueprint)

    def get_logs(self, app_name: str, blueprint: AppBlueprint, follow: bool = False, lines: int = 100):
        state = self._get_state(app_name)
        if not state.vmid:
            raise RuntimeError(f"No container found for {app_name}")

        if blueprint.deployment.type == "docker":
            deployer = DockerDeployer()
        else:
            deployer = NativeDeployer()
        return deployer.get_logs(self.proxmox, state.node, state.vmid, blueprint, follow, lines)

    def sync(self, app_name: str, blueprint: AppBlueprint):
        state = self._get_state(app_name)
        if not state.vmid:
            raise RuntimeError(f"No container found for {app_name}")

        print(f"--> [SYNC] Updating {app_name}...")

        # Re-push templates
        env = dict(blueprint.environment)
        env.update(state.secrets_resolved)

        for tpl in blueprint.templates:
            rendered = self.template_engine.render_file(tpl.source, env)
            local_tmp = Path(f"/tmp/ops_{blueprint.name}_{Path(tpl.dest).name}")
            local_tmp.write_text(rendered)
            self.proxmox.push_file(state.vmid, str(local_tmp), tpl.dest, node=state.node)
            local_tmp.unlink()

        # Restart service
        self.restart_service(app_name, blueprint)
        print("    [OK] Sync complete")
