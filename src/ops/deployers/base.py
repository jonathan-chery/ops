from abc import ABC, abstractmethod
from typing import Dict

from ..providers.proxmox import ProxmoxProvider
from ..models.blueprint import AppBlueprint


class BaseDeployer(ABC):
    @abstractmethod
    def deploy(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        env: Dict[str, str],
    ) -> None:
        pass

    @abstractmethod
    def get_logs(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ) -> str:
        pass

    @abstractmethod
    def restart_service(
        self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint
    ) -> None:
        pass

    @abstractmethod
    def get_service_status(
        self, proxmox: ProxmoxProvider, node: str, vmid: int, blueprint: AppBlueprint
    ) -> str:
        pass
