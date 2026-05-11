"""Firecracker network management utilities."""

import subprocess

from ops.utils.safe_shell import quote


class FirecrackerNetworkManager:
    """Manages TAP devices and host-side NAT/bridge for Firecracker microVMs.

    Uses standard Linux networking primitives via safe_shell subprocess calls.
    """

    def create_tap(self, tap_name: str) -> None:
        """Create a TAP device if it does not exist."""
        result = subprocess.run(
            ["ip", "tuntap", "show", tap_name],
            capture_output=True,
            text=True,
        )
        if tap_name not in result.stdout:
            subprocess.run(
                ["ip", "tuntap", "add", quote(tap_name), "mode", "tap"],
                check=True,
            )
            subprocess.run(["ip", "link", "set", quote(tap_name), "up"], check=True)

    def create_tap_nat(
        self,
        tap_name: str,
        vm_ip: str = "192.168.127.2",
        host_ip: str = "192.168.127.1",
    ) -> None:
        """Create a TAP device with a /30 subnet and NAT via iptables.

        Assigns a private subnet to the TAP and masquerades outbound traffic
        through the host's default interface.
        """
        self.create_tap(tap_name)
        # Assign host-side IP
        subprocess.run(
            ["ip", "addr", "add", f"{host_ip}/30", "dev", quote(tap_name)],
            check=True,
        )
        subprocess.run(["ip", "link", "set", quote(tap_name), "up"], check=True)
        # Enable IP forwarding and NAT
        subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], check=True)
        subprocess.run(
            [
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-o",
                "eth0",
                "-j",
                "MASQUERADE",
            ],
            check=False,
        )
        # Allow forwarding from TAP
        subprocess.run(
            [
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                quote(tap_name),
                "-j",
                "ACCEPT",
            ],
            check=False,
        )

    def create_tap_bridge(self, tap_name: str, bridge_name: str) -> None:
        """Add a TAP device to an existing Linux bridge."""
        self.create_tap(tap_name)
        subprocess.run(
            ["ip", "link", "set", quote(tap_name), "master", quote(bridge_name)],
            check=True,
        )
        subprocess.run(["ip", "link", "set", quote(tap_name), "up"], check=True)

    def delete_tap(self, tap_name: str) -> None:
        """Remove a TAP device."""
        subprocess.run(["ip", "link", "del", quote(tap_name)], check=False)
