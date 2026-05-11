"""Nested Firecracker deployer (runs Firecracker inside an LXC container)."""

import time
from typing import Dict

from ops.deployers.base import BaseDeployer
from ops.providers.proxmox import ProxmoxProvider
from ops.models.blueprint import AppBlueprint
from ops.utils.network_firecracker import FirecrackerNetworkManager


class NestedFirecrackerDeployer(BaseDeployer):
    """Deploys Firecracker microVMs *inside* an LXC container.

    Requires /dev/kvm passthrough configured on the container.  The
    orchestrator must call `patch_lxc_config` on the ProxmoxProvider
    before starting the container so that the KVM device is visible
    inside the guest.
    """

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

        # Ensure Firecracker binary is installed inside the container
        self._ensure_firecracker(proxmox, node, vmid, fc_cfg.firecracker_version)

        # Build rootfs if requested
        rootfs_path = fc_cfg.rootfs_path
        if fc_cfg.rootfs_source == "built-in" or not rootfs_path:
            rootfs_path = f"/var/lib/firecracker/{blueprint.name}/rootfs.ext4"
            proxmox.exec(
                vmid,
                f"mkdir -p /var/lib/firecracker/{blueprint.name}",
                node=node,
            )
            from ops.utils.rootfs_builder import RootfsBuilder

            builder = RootfsBuilder(
                size_mb=fc_cfg.rootfs_size_mb,
                output_path=rootfs_path,
            )
            builder.build(blueprint)

        # Setup TAP device from inside the LXC (needs CAP_NET_ADMIN)
        tap_name = f"tap{vmid}"
        net_mgr = FirecrackerNetworkManager()
        if fc_cfg.network_mode == "nat":
            net_mgr.create_tap_nat(tap_name)
        elif fc_cfg.network_mode == "bridge":
            bridge = blueprint.network.bridge or "br0"
            net_mgr.create_tap_bridge(tap_name, bridge)

        # Start Firecracker daemon inside container
        socket_path = f"/tmp/firecracker_{blueprint.name}.sock"
        proxmox.exec(
            vmid,
            f"nohup firecracker --api-sock {socket_path} >/dev/null 2>&1 &",
            node=node,
        )
        time.sleep(2)

        # Configure VM via REST inside the container
        kernel = fc_cfg.kernel_path or "/vmlinux"
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/machine-config' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"vcpu_count\":{blueprint.container.cores},\"mem_size_mib\":{blueprint.container.memory}}}'",
            node=node,
        )
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/boot-source' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"kernel_image_path\":\"{kernel}\",\"boot_args\":\"console=ttyS0 reboot=k panic=1 pci=off\"}}'",
            node=node,
        )
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/drives/rootfs' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"drive_id\":\"rootfs\",\"path_on_host\":\"{rootfs_path}\",\"is_root_device\":true,\"is_read_only\":false}}'",
            node=node,
        )
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/network-interfaces/eth0' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"iface_id\":\"eth0\",\"host_dev_name\":\"{tap_name}\"}}'",
            node=node,
        )
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/actions' "
            f"-H 'Content-Type: application/json' -d '{{\"action_type\":\"InstanceStart\"}}'",
            node=node,
        )

        # Wait for boot by polling state
        for _ in range(90):
            res = proxmox.exec(
                vmid,
                f"curl -fsS --unix-socket {socket_path} '>http://localhost/'",
                node=node,
            )
            if '"state":"Running"' in res.stdout:
                return
            time.sleep(1)
        raise RuntimeError("Nested Firecracker microVM did not boot")

    def get_logs(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ) -> str:
        return "Nested Firecracker logs: not yet implemented"

    def restart_service(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> None:
        socket_path = f"/tmp/firecracker_{blueprint.name}.sock"
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/actions' "
            f"-H 'Content-Type: application/json' -d '{{\"action_type\":\"SendCtrlAltDel\"}}'",
            node=node,
        )
        time.sleep(2)
        proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} -X PUT '>http://localhost/actions' "
            f"-H 'Content-Type: application/json' -d '{{\"action_type\":\"InstanceStart\"}}'",
            node=node,
        )

    def get_service_status(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> str:
        socket_path = f"/tmp/firecracker_{blueprint.name}.sock"
        res = proxmox.exec(
            vmid,
            f"curl -fsS --unix-socket {socket_path} '>http://localhost/'",
            node=node,
        )
        if '"state":"Running"' in res.stdout:
            return "running"
        return "unknown"

    # -- Helper --------------------------------------------------------------

    def _ensure_firecracker(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        version: str,
    ) -> None:
        """Download the Firecracker binary inside the LXC if it is missing."""
        check = proxmox.exec(vmid, "which firecracker >/dev/null 2>&1 && echo OK", node=node)
        if "OK" in check.stdout:
            return

        ver = version if version != "latest" else "v1.7.0"
        url = (
            f"https://github.com/firecracker-microvm/firecracker/releases/download/{ver}/"
            f"firecracker-{ver}-x86_64.tgz"
        )
        proxmox.exec(
            vmid,
            f"curl -fsSL {url} | tar -xz -C /tmp && "
            f"cp /tmp/release-{ver}-x86_64/firecracker-{ver}-x86_64 /usr/local/bin/firecracker && "
            f"chmod +x /usr/local/bin/firecracker",
            node=node,
        )
        # Verify again
        check = proxmox.exec(vmid, "which firecracker >/dev/null 2>&1 && echo OK", node=node)
        if "OK" not in check.stdout:
            raise RuntimeError("Failed to install Firecracker inside LXC")
