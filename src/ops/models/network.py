from ipaddress import IPv4Address, IPv4Network
from pydantic import BaseModel


class SubnetConfig(BaseModel):
    network: IPv4Network
    gateway: IPv4Address
    bridge: str = "vmbr1"

    def allocate_ip(self, vmid: int) -> IPv4Address:
        """Allocate an IP where the last octet matches the VMID."""
        octets = str(self.network.network_address).split(".")
        octets[3] = str(vmid % 256)
        return IPv4Address(".".join(octets))

    def is_ip_available(self, ip: IPv4Address, used_ips: list) -> bool:
        """Check if an IP is within the subnet and not in use."""
        return ip in self.network and str(ip) not in [str(u) for u in used_ips]
