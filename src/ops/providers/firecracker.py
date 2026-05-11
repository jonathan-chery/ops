"""Firecracker microVM provider."""

import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any

import requests_unixsocket  # type: ignore[import-untyped]

from ops.models.blueprint import AppBlueprint, FirecrackerDeploymentConfig


class FirecrackerProvider:
    """Manages Firecracker microVMs via the REST API over a Unix domain socket.

    The API surface is small (~10 core endpoints). We use requests with
    requests-unixsocket to avoid coupling to alpha community libraries.
    """

    def __init__(
        self,
        socket_path: str,
        fc_binary: str = "firecracker",
        jailer_binary: Optional[str] = None,
    ):
        self.socket_path = Path(socket_path)
        self.fc_binary = fc_binary
        self.jailer_binary = jailer_binary
        self._process: Optional[subprocess.Popen] = None
        self._session = requests_unixsocket.Session()

    def ensure_daemon(self) -> None:
        """Start the firecracker binary if the socket is not already present."""
        if self.socket_path.exists():
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.fc_binary,
            "--api-sock",
            str(self.socket_path),
        ]
        # Run in background; we rely on the socket file for readiness
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for socket to appear
        for _ in range(30):
            if self.socket_path.exists():
                return
            time.sleep(0.1)
        raise RuntimeError("Firecracker socket did not appear")

    def _request(self, method: str, path: str, json_body: Optional[Dict] = None) -> Any:
        url = f"http+unix://{str(self.socket_path).replace('/', '%2F')}{path}"
        response = self._session.request(method, url, json=json_body)
        response.raise_for_status()
        if response.text:
            return response.json()
        return None

    # -- VM lifecycle --

    def configure_machine(
        self,
        vcpu_count: int,
        mem_size_mib: int,
        smt: bool = False,
        track_dirty_pages: bool = False,
    ) -> None:
        """PUT /machine-config"""
        self._request(
            "PUT",
            "/machine-config",
            {
                "vcpu_count": vcpu_count,
                "mem_size_mib": mem_size_mib,
                "smt": smt,
                "track_dirty_pages": track_dirty_pages,
            },
        )

    def set_boot_source(
        self, kernel_path: str, boot_args: Optional[str] = None
    ) -> None:
        """PUT /boot-source"""
        body: Dict[str, Any] = {"kernel_image_path": kernel_path}
        if boot_args:
            body["boot_args"] = boot_args
        self._request("PUT", "/boot-source", body)

    def add_drive(self, drive_id: str, path: str, read_only: bool = False) -> None:
        """PUT /drives/{drive_id}"""
        self._request(
            "PUT",
            f"/drives/{drive_id}",
            {
                "drive_id": drive_id,
                "path_on_host": path,
                "is_root_device": drive_id == "rootfs",
                "is_read_only": read_only,
            },
        )

    def add_network_interface(
        self,
        iface_id: str,
        host_dev_name: str,
        guest_mac: Optional[str] = None,
    ) -> None:
        """PUT /network-interfaces/{iface_id}"""
        body: Dict[str, Any] = {
            "iface_id": iface_id,
            "host_dev_name": host_dev_name,
            "guest_mac": guest_mac,
        }
        self._request("PUT", f"/network-interfaces/{iface_id}", body)

    def start(self) -> None:
        """PUT /actions with InstanceStart."""
        self._request(
            "PUT",
            "/actions",
            {"action_type": "InstanceStart"},
        )

    def stop(self) -> None:
        """Send SIGTERM to the firecracker process."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=5)

    def pause(self) -> None:
        """PUT /actions Pause."""
        self._request("PUT", "/actions", {"action_type": "Pause"})

    def resume(self) -> None:
        """PUT /actions Resume."""
        self._request("PUT", "/actions", {"action_type": "Resume"})

    def get_info(self) -> Dict[str, Any]:
        """GET /"""
        return self._request("GET", "/") or {}

    # -- Utilities --

    def create_vm(
        self,
        vmid: int,
        blueprint: AppBlueprint,
        fc_cfg: FirecrackerDeploymentConfig,
        tap_name: str,
    ) -> None:
        """Orchestrate a full microVM creation."""
        self.ensure_daemon()
        self.configure_machine(
            vcpu_count=blueprint.container.cores,
            mem_size_mib=blueprint.container.memory,
        )
        self.set_boot_source(fc_cfg.kernel_path)
        rootfs = fc_cfg.rootfs_path or f"/var/lib/firecracker/{vmid}/rootfs.ext4"
        self.add_drive("rootfs", rootfs)
        self.add_network_interface("eth0", tap_name)
        self.start()

    def wait_for_boot(self, timeout: int = 90) -> bool:
        """Poll MMDS or instance info until VM signals readiness.

        Firecracker does not expose a direct systemd signal, so we
        poll the instance info endpoint for state == 'Running'.
        """
        for _ in range(timeout):
            info = self.get_info()
            if info.get("state") == "Running":
                return True
            time.sleep(1)
        return False

    def destroy(self) -> None:
        """Gracefully terminate the VM and remove the socket."""
        try:
            self._request("PUT", "/actions", {"action_type": "SendCtrlAltDel"})
        except Exception:
            pass
        time.sleep(1)
        self.stop()
        if self.socket_path.exists():
            self.socket_path.unlink()
