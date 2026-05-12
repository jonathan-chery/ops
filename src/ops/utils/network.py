from ipaddress import IPv4Address
from typing import List

from ops.models.network import SubnetConfig


class IPAllocator:
    def __init__(self, subnet: SubnetConfig):
        self.subnet = subnet

    def allocate(self, vmid: int, used_ips: List[str]) -> IPv4Address:
        ip = self.subnet.allocate_ip(vmid)
        if not self.subnet.is_ip_available(ip, used_ips):
            raise ValueError(
                f"IP {ip} is not available in subnet {self.subnet.network}"
            )
        return ip

    def suggest_vmid(self, used_vmids: List[int], start: int = 100) -> int:
        vmid = start
        while vmid in used_vmids:
            vmid += 1
        if vmid > 999999999:
            raise ValueError("No available VMIDs")
        return vmid

    def is_vmid_available(self, vmid: int, used_vmids: List[int]) -> bool:
        return vmid not in used_vmids
