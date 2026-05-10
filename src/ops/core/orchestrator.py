import paramiko
from typing import List
from .blueprint import AppBlueprint

class Orchestrator:
    def __init__(self, proxmox_provider, infisical_provider):
        self.proxmox = proxmox_provider
        self.infisical = infisical_provider

    def run_remote_command(self, ip, command, password=None):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username="root", password=password)
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        ssh.close()
        return output

    def deploy(self, blueprint: AppBlueprint):
        print(f"Deploying {blueprint.name}...")
        
        # 1. Provision
        vmid = 100 # In real use, this should be dynamically allocated
        self.proxmox.create_lxc(vmid, blueprint.name, blueprint.template, blueprint.resources)
        self.proxmox.start_lxc(vmid)
        
        # Get IP (Simplified)
        ip = "192.168.1.100" 
        
        # 2. Resolve Secrets from Infisical
        secrets = {}
        for var in blueprint.env_vars:
            secrets[var] = self.infisical.get_secret(var)
        
        # 3. Install Dependencies
        for step in blueprint.install_steps:
            print(f"Executing: {step}")
            self.run_remote_command(ip, step)
            
        # 4. Deploy App with Secrets
        env_str = " ".join([f"{k}={v}" for k, v in secrets.items()])
        deploy_cmd = f"export {env_str} && ./deploy.sh"
        self.run_remote_command(ip, deploy_cmd)
        
        print(f"Successfully deployed {blueprint.name} at {ip}")

    def teardown(self, blueprint: AppBlueprint):
        print(f"Tearing down {blueprint.name}...")
        vmid = 100
        self.proxmox.stop_lxc(vmid)
        self.proxmox.destroy_lxc(vmid)
        print(f"Successfully removed {blueprint.name}")
