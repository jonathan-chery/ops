import time
from pathlib import Path
from typing import Dict

from .base import BaseDeployer
from ..providers.proxmox import ProxmoxProvider
from ..models.blueprint import AppBlueprint


class NativeDeployer(BaseDeployer):
    def deploy(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        env: Dict[str, str],
    ) -> None:
        native = blueprint.deployment.native
        if not native:
            raise RuntimeError("Native deployment config missing")

        # Git clone
        if native.git_repo:
            proxmox.exec(vmid, f"rm -rf {native.app_dir}", node=node)
            tag_flag = f" --branch {native.tag}" if native.tag else ""
            proxmox.exec(
                vmid,
                f"git clone{tag_flag} {native.git_repo} {native.app_dir}",
                node=node,
            )
            if native.tag:
                proxmox.exec(
                    vmid, f"cd {native.app_dir} && git checkout {native.tag}", node=node
                )
            proxmox.exec(
                vmid,
                f"chown -R {native.app_user}:{native.app_user} {native.app_dir}",
                node=node,
            )

        # Build steps
        for step in native.build_steps:
            user = step.user or native.app_user
            env_str = " ".join([f"{k}='{v}'" for k, v in step.env.items()])
            cmd = step.cmd
            if env_str:
                cmd = f"export {env_str} && {cmd}"
            proxmox.exec(
                vmid,
                f"su - {user} -s /bin/bash -c 'cd {native.app_dir} && {cmd}'",
                node=node,
            )

        # Create systemd service
        self._create_systemd_service(proxmox, node, vmid, blueprint, env)

    def _create_systemd_service(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        env: Dict[str, str],
    ):
        native = blueprint.deployment.native
        assert native is not None
        service_name = blueprint.name

        # Build environment file content
        env_file_content = ""
        for k, v in env.items():
            env_file_content += f"{k}={v}\n"

        env_file_path = f"{native.app_dir}/{native.service_env_file or '.env'}"

        # Push env file
        local_env = Path(f"/tmp/ops_env_{blueprint.name}")
        local_env.write_text(env_file_content)
        proxmox.push_file(vmid, str(local_env), env_file_path, node=node)
        proxmox.exec(
            vmid,
            f"chown {native.app_user}:{native.app_user} {env_file_path} && chmod 600 {env_file_path}",
            node=node,
        )
        local_env.unlink()

        # Create systemd unit
        unit = f"""[Unit]
Description={blueprint.name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={native.app_user}
Group={native.app_user}
WorkingDirectory={native.app_dir}
ExecStart={native.service_command}
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=false
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths={native.app_dir}
PrivateTmp=true
EnvironmentFile={env_file_path}

[Install]
WantedBy=multi-user.target
"""
        local_unit = Path(f"/tmp/ops_unit_{blueprint.name}.service")
        local_unit.write_text(unit)
        proxmox.push_file(
            vmid,
            str(local_unit),
            f"/etc/systemd/system/{service_name}.service",
            node=node,
        )
        local_unit.unlink()

        # Reload and start
        proxmox.exec(vmid, "systemctl daemon-reload", node=node)
        proxmox.exec(vmid, f"systemctl enable --now {service_name}", node=node)
        time.sleep(3)

    def get_logs(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ) -> str:
        flag = " -f" if follow else ""
        result = proxmox.exec(
            vmid,
            f"journalctl -u {blueprint.name}{flag} -n {lines} --no-pager",
            node=node,
        )
        return result.stdout or result.stderr

    def restart_service(
        self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint
    ) -> None:
        proxmox.exec(vmid, f"systemctl restart {blueprint.name}", node=node)

    def get_service_status(
        self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint
    ) -> str:
        result = proxmox.exec(vmid, f"systemctl is-active {blueprint.name}", node=node)
        return result.stdout.strip() or "unknown"
