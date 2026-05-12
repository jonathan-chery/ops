import time
from typing import Dict

from .base import BaseDeployer
from ..providers.proxmox import ProxmoxProvider
from ..models.blueprint import AppBlueprint


class DockerDeployer(BaseDeployer):
    def deploy(self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint, env: Dict[str, str]) -> None:
        docker_cfg = blueprint.deployment.docker
        if not docker_cfg:
            raise RuntimeError("Docker deployment config missing")

        app_dir = f"/opt/{blueprint.name}"

        # Ensure app directory exists
        proxmox.exec(vmid, f"mkdir -p {app_dir}", node=node)

        # Build and start
        proxmox.exec(vmid, f"cd {app_dir} && docker compose down >/dev/null 2>&1 || true", node=node)
        build_flag = " --build" if docker_cfg.build_context else ""
        proxmox.exec(vmid, f"cd {app_dir} && docker compose up -d{build_flag}", node=node)

        time.sleep(5)

    def get_logs(self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint, follow: bool = False, lines: int = 100) -> str:
        docker_cfg = blueprint.deployment.docker
        if not docker_cfg:
            return "No docker config"
        app_dir = f"/opt/{blueprint.name}"
        flag = " -f" if follow else f" --tail={lines}"
        result = proxmox.exec(vmid, f"cd {app_dir} && docker compose logs{flag} {docker_cfg.service_name}", node=node)
        return result.stdout or result.stderr

    def restart_service(self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint) -> None:
        docker_cfg = blueprint.deployment.docker
        if not docker_cfg:
            return
        app_dir = f"/opt/{blueprint.name}"
        proxmox.exec(vmid, f"cd {app_dir} && docker compose restart {docker_cfg.service_name}", node=node)

    def get_service_status(self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint) -> str:
        docker_cfg = blueprint.deployment.docker
        if not docker_cfg:
            return "unknown"
        app_dir = f"/opt/{blueprint.name}"
        result = proxmox.exec(vmid, f"cd {app_dir} && docker compose ps {docker_cfg.service_name}", node=node)
        return result.stdout or "unknown"
