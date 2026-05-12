"""Proxmox microVM provider via pve-microvm."""

import time
from typing import Optional

import paramiko

from ..utils.safe_shell import quote
from ..models.blueprint import AppBlueprint


class MicroVMProvider:
    """Manages QEMU microVMs on Proxmox nodes via SSH.

    Delegates to the pve-microvm CLI tools installed on the target Proxmox
    host.  This provider creates a new SSH client for every invocation to
    avoid long-lived paramiko connections across different phases of the
    orchestrator.
    """

    def __init__(
        self,
        hostname: str,
        username: str = "root",
        port: int = 22,
        private_key_path: Optional[str] = None,
    ):
        self.hostname = hostname
        self.username = username
        self.port = port
        self._private_key_path = private_key_path

    # -- SSH helpers ---------------------------------------------------------

    def _ssh_client(self) -> paramiko.SSHClient:
        """Create a fresh paramiko client connected to the Proxmox host."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs: dict = {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
        }
        if self._private_key_path:
            connect_kwargs["key_filename"] = self._private_key_path
        client.connect(**connect_kwargs)
        return client

    def _exec(self, command: str) -> tuple[str, str, int]:
        """Execute a command on the Proxmox host and return (stdout, stderr, rc)."""
        client = self._ssh_client()
        try:
            stdin, stdout, stderr = client.exec_command(command)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return out, err, rc
        finally:
            client.close()

    # -- Capability probe ----------------------------------------------------

    def is_available(self) -> bool:
        """Return True if pve-microvm is installed on the target node."""
        out, _, rc = self._exec("which pve-microvm-template >/dev/null 2>&1 && echo OK")
        return rc == 0 and "OK" in out

    # -- Template management -------------------------------------------------

    def ensure_template(self, image: str, vmid: int = 9000) -> str:
        """Ensure a pve-microvm template exists for the given OCI image.

        Returns the template VMID as a string.
        """
        # Check if template already exists
        out, _, rc = self._exec(f"qm status {vmid} >/dev/null 2>&1 && echo OK")
        if rc == 0 and "OK" in out:
            return str(vmid)

        # Create template from OCI image
        quoted_image = quote(image)
        out, err, rc = self._exec(
            f"pve-microvm-template --image {quoted_image} --vmid {vmid}"
        )
        if rc != 0:
            raise RuntimeError(
                f"pve-microvm-template failed for image {image}: {err or out}"
            )
        return str(vmid)

    # -- VM lifecycle --------------------------------------------------------

    def create_vm(
        self,
        vmid: int,
        blueprint: AppBlueprint,
        template_vmid: int,
        storage: str = "local",
        bridge: str = "vmbr1",
    ) -> None:
        """Clone a microVM template and configure it."""
        # Full clone from template
        quoted_name = quote(blueprint.container.hostname)
        out, err, rc = self._exec(
            f"qm clone {template_vmid} {vmid} --name {quoted_name} --full",
        )
        if rc != 0:
            raise RuntimeError(f"qm clone failed: {err or out}")

        # Configure resources
        out, err, rc = self._exec(
            f"qm set {vmid} --cores {blueprint.container.cores} "
            f"--memory {blueprint.container.memory} "
            f"--net0 virtio,bridge={quote(bridge)}"
        )
        if rc != 0:
            raise RuntimeError(f"qm set failed: {err or out}")

    def start_vm(self, vmid: int) -> None:
        out, err, rc = self._exec(f"qm start {vmid}")
        if rc != 0:
            raise RuntimeError(f"qm start {vmid} failed: {err}")

    def stop_vm(self, vmid: int) -> None:
        out, err, rc = self._exec(f"qm stop {vmid}")
        if rc != 0:
            raise RuntimeError(f"qm stop {vmid} failed: {err}")

    def destroy_vm(self, vmid: int) -> None:
        out, err, rc = self._exec(f"qm destroy {vmid} --purge")
        if rc != 0:
            raise RuntimeError(f"qm destroy {vmid} failed: {err}")

    def get_vm_status(self, vmid: int) -> str:
        out, err, rc = self._exec(f"qm status {vmid}")
        if rc != 0:
            return "unknown"
        # qm status output is "status: running" etc.
        for line in out.strip().splitlines():
            if line.startswith("status:"):
                return line.split(":", 1)[1].strip()
        return "unknown"

    def get_vm_ip(self, vmid: int) -> Optional[str]:
        """Try to get the guest IP via the PVE API (qm guest or agent)."""
        out, err, rc = self._exec(f"qm guest cmd {vmid} network-get-interfaces")
        if rc != 0:
            return None
        # Simple heuristic: look for first IPv4 address in JSON-like output
        import json

        try:
            data = json.loads(out)
            for iface in data.get("result", []):
                for addr in iface.get("ip-addresses", []):
                    if addr.get("ip-address-type") == "ipv4":
                        ip = addr.get("ip-address")
                        if ip and not ip.startswith("127."):
                            return ip
        except Exception:
            pass
        return None

    def wait_for_boot(self, vmid: int, timeout: int = 120) -> bool:
        """Poll qm status until the VM is running."""
        for _ in range(timeout // 2):
            status = self.get_vm_status(vmid)
            if status == "running":
                return True
            time.sleep(2)
        return False

    def wait_for_network(self, vmid: int, timeout: int = 120) -> Optional[str]:
        """Poll until the VM has a guest IP."""
        for _ in range(timeout // 2):
            ip = self.get_vm_ip(vmid)
            if ip:
                return ip
            time.sleep(2)
        return None
