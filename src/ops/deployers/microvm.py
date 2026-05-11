"""MicroVM deployer for pve-microvm-backed QEMU microVMs."""

import time
from typing import Dict

from ops.deployers.base import BaseDeployer
from ops.models.blueprint import AppBlueprint
from ops.providers.proxmox import ProxmoxProvider
from ops.providers.microvm import MicroVMProvider


class MicroVMDeployer(BaseDeployer):
    """Deploys workloads as QEMU microVMs via pve-microvm.

    Uses MicroVMProvider to manage the VM lifecycle on the Proxmox node.
    Because microVMs are full QEMU VMs (not LXC), the deployer does not
    use ProxmoxProvider for the deploy phase itself, but it still accepts
    it to satisfy the BaseDeployer interface.
    """

    def __init__(self, microvm: MicroVMProvider):
        self.microvm = microvm

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

        image = fc_cfg.image or "debian:trixie-slim"
        template_vmid = self.microvm.ensure_template(image, vmid=9000)

        # Clone template to target VMID
        self.microvm.create_vm(
            vmid=vmid,
            blueprint=blueprint,
            template_vmid=int(template_vmid),
            bridge=blueprint.network.bridge or "vmbr1",
        )
        self.microvm.start_vm(vmid)

        if not self.microvm.wait_for_boot(vmid, timeout=120):
            raise RuntimeError(f"MicroVM {vmid} did not reach running state")

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
        out, err, rc = self.microvm._exec(
            f"qm terminal {vmid}{flag} --timeout 5 || true"
        )
        return out or err or "No logs available"

    def restart_service(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> None:
        self.microvm.stop_vm(vmid)
        time.sleep(2)
        self.microvm.start_vm(vmid)

    def get_service_status(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> str:
        return self.microvm.get_vm_status(vmid)
