"""Firecracker microVM deployer."""

import time
from typing import Dict

from ops.deployers.base import BaseDeployer
from ops.providers.proxmox import ProxmoxProvider
from ops.providers.firecracker import FirecrackerProvider
from ops.models.blueprint import AppBlueprint
from ops.utils.network_firecracker import FirecrackerNetworkManager


class FirecrackerDeployer(BaseDeployer):
    """Deploys workloads inside Firecracker microVMs."""

    def __init__(self, fc_provider: FirecrackerProvider):
        self.fc = fc_provider
        self.net_mgr = FirecrackerNetworkManager()

    def deploy(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        env: Dict[str, str],
    ) -> None:
        fc_cfg = blueprint.deployment.firecracker
        if not fc_cfg:
            raise RuntimeError("Firecracker deployment config missing")

        # Build rootfs if not pre-built
        rootfs_path = fc_cfg.rootfs_path
        if fc_cfg.rootfs_source == "built-in" or not rootfs_path:
            from ops.utils.rootfs_builder import RootfsBuilder

            rootfs_path = f"/var/lib/firecracker/{vmid}/rootfs.ext4"
            builder = RootfsBuilder(
                size_mb=fc_cfg.rootfs_size_mb,
                output_path=rootfs_path,
            )
            builder.build(blueprint)

        # Setup network
        tap_name = f"tap{vmid}"
        if fc_cfg.network_mode == "nat":
            self.net_mgr.create_tap_nat(tap_name)
        elif fc_cfg.network_mode == "bridge":
            bridge = blueprint.network.bridge or "br0"
            self.net_mgr.create_tap_bridge(tap_name, bridge)

        # Create VM
        self.fc.create_vm(vmid, blueprint, fc_cfg, tap_name)
        if not self.fc.wait_for_boot(timeout=90):
            raise RuntimeError("Firecracker microVM did not boot")

        time.sleep(2)

    def get_logs(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ) -> str:
        # Firecracker serial console logs (if configured) or MMDS
        return "Firecracker logs: not yet implemented"

    def restart_service(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> None:
        self.fc.pause()
        self.fc.resume()

    def get_service_status(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> str:
        info = self.fc.get_info()
        return info.get("state", "unknown")
