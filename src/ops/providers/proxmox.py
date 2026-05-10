import requests
from proxmoxer import ProxmoxAPI

class ProxmoxProvider:
    def __init__(self, host, user, token_name, token_value, verify_ssl=False):
        self.proxmox = ProxmoxAPI(
            host, 
            user=f"{user}@{token_name}", 
            token_name=token_name, 
            token_value=token_value, 
            verify_ssl=verify_ssl
        )

    def create_lxc(self, vmid, hostname, template, resources):
        # Simplified LXC creation logic
        return self.proxmox.nodes('pve1').lxc.create(
            vmid=vmid,
            hostname=hostname,
            ostemplate=template,
            cores=resources.cores,
            memory=resources.memory,
            rootfs=f"local-lvm:{resources.disk}",
        )

    def start_lxc(self, vmid):
        return self.proxmox.nodes('pve1').lxc(vmid).status.start.post()

    def stop_lxc(self, vmid):
        return self.proxmox.nodes('pve1').lxc(vmid).status.stop.post()

    def destroy_lxc(self, vmid):
        return self.proxmox.nodes('pve1').lxc(vmid).delete()
