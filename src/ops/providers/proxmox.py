import base64
import time
from typing import List, Optional, Dict

from proxmoxer import ProxmoxAPI

from ..models.config import ProxmoxConfig
from ..models.container import ContainerStatus

__all__ = ["ProxmoxProvider", "ExecResult"]


class ExecResult:
    def __init__(self, stdout: str, stderr: str, exit_code: int):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class ProxmoxProvider:
    def __init__(self, config: ProxmoxConfig):
        self.config = config
        self.api = ProxmoxAPI(
            config.host,
            user=f"{config.user}@pam" if "@" not in config.user else config.user,
            token_name=config.token_name,
            token_value=config.token_value,
            verify_ssl=config.verify_ssl,
        )
        self._node: Optional[str] = config.node

    def _get_node(self) -> str:
        if self._node:
            return self._node
        nodes = self.get_nodes()
        if not nodes:
            raise RuntimeError("No Proxmox nodes found")
        self._node = nodes[0]
        return self._node

    def get_nodes(self) -> List[str]:
        return [n["node"] for n in self.api.nodes.get()]

    def list_containers(self, node: Optional[str] = None) -> List[ContainerStatus]:
        node = node or self._get_node()
        containers = []
        for ct in self.api.nodes(node).lxc.get():
            containers.append(
                ContainerStatus(
                    vmid=ct.get("vmid", 0),
                    hostname=ct.get("name", ""),
                    name=ct.get("name", ""),
                    status=ct.get("status", "unknown"),
                    ip=None,
                )
            )
        return containers

    def get_container(
        self, vmid: int, node: Optional[str] = None
    ) -> Optional[ContainerStatus]:
        node = node or self._get_node()
        try:
            ct = self.api.nodes(node).lxc(vmid).status.current.get()
            return ContainerStatus(
                vmid=vmid,
                hostname=ct.get("name", ""),
                name=ct.get("name", ""),
                status=ct.get("status", "unknown"),
                ip=None,
                uptime=ct.get("uptime", None),
            )
        except Exception:
            return None

    def get_available_templates(
        self, storage: str = "local", node: Optional[str] = None
    ) -> List[str]:
        node = node or self._get_node()
        try:
            templates = (
                self.api.nodes(node).storage(storage).content.get(content="vztmpl")
            )
            return [t["volid"] for t in templates]
        except Exception:
            return []

    def download_template(
        self, storage: str = "local", node: Optional[str] = None
    ) -> None:
        """Download the default Ubuntu 24.04 template from Proxmox template repo."""
        node = node or self._get_node()
        # Try the standard Ubuntu 24.04 template name
        template_filename = "ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
        try:
            self.api.nodes(node).storage(storage).download(
                content="vztmpl",
                filename=template_filename,
            )
            # Wait a bit for download to start
            time.sleep(2)
        except Exception:
            # If API download fails, raise with helpful message
            raise RuntimeError(
                f"Cannot download template '{template_filename}'. Please download manually:\n"
                f"  pveam download {storage}:vztmpl {template_filename}"
            )

    def resolve_template_volid(
        self, template_name: str, storage: str = "local", node: Optional[str] = None
    ) -> Optional[str]:
        """Try to resolve a template name to a full volid."""
        node = node or self._get_node()
        # Try exact match first
        available = self.get_available_templates(storage, node)
        for volid in available:
            if template_name in volid:
                return volid
        return None

    def wait_for_boot(
        self, vmid: int, timeout: int = 120, node: Optional[str] = None
    ) -> bool:
        """Poll container until systemd signals readiness."""
        node = node or self._get_node()
        for _ in range(timeout // 2):
            result = self.exec(
                vmid,
                "systemctl is-system-running >/dev/null 2>&1 && echo OK",
                node=node,
            )
            if "OK" in result.stdout:
                return True
            time.sleep(2)
        return False

    def create_lxc(
        self,
        vmid: int,
        hostname: str,
        template: str,
        cores: int,
        memory: int,
        disk: int,
        storage: str = "local",
        bridge: str = "vmbr1",
        ip_cidr: str = "",
        gateway: str = "",
        password: str = "",
        dns: str = "1.1.1.1",
        node: Optional[str] = None,
    ) -> None:
        node = node or self._get_node()
        net0 = f"name=eth0,bridge={bridge},ip={ip_cidr},gw={gateway}"
        if not ip_cidr:
            net0 = f"name=eth0,bridge={bridge},ip=dhcp"

        params = {
            "vmid": vmid,
            "hostname": hostname,
            "ostemplate": template,
            "cores": cores,
            "memory": memory,
            "rootfs": f"{storage}:{disk}",
            "net0": net0,
            "nameserver": dns,
            "unprivileged": 1,
            "features": "nesting=1",
            "onboot": 1,
        }
        if password:
            params["password"] = password

        self.api.nodes(node).lxc.create(**params)

    def start_lxc(self, vmid: int, node: Optional[str] = None) -> None:
        node = node or self._get_node()
        self.api.nodes(node).lxc(vmid).status.start.post()

    def stop_lxc(self, vmid: int, node: Optional[str] = None) -> None:
        node = node or self._get_node()
        self.api.nodes(node).lxc(vmid).status.stop.post()

    def restart_lxc(self, vmid: int, node: Optional[str] = None) -> None:
        self.stop_lxc(vmid, node)
        time.sleep(2)
        self.start_lxc(vmid, node)

    def destroy_lxc(self, vmid: int, node: Optional[str] = None) -> None:
        node = node or self._get_node()
        try:
            self.api.nodes(node).lxc(vmid).delete()
        except Exception:
            pass

    def exec(
        self,
        vmid: int,
        command: str,
        user: str = "root",
        node: Optional[str] = None,
        retries: int = 3,
    ) -> ExecResult:
        node = node or self._get_node()
        last_error = None
        for attempt in range(retries):
            try:
                result = (
                    self.api.nodes(node)
                    .lxc(vmid)
                    .exec_post(
                        command=command,
                        user=user,
                    )
                )
                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                exit_code = result.get("exitcode", 0)
                return ExecResult(stdout, stderr, exit_code)
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Retry on transient errors only
                if any(
                    x in err_str
                    for x in [
                        "ct did not start",
                        "timeout",
                        "Connection refused",
                        "CT not running",
                    ]
                ):
                    time.sleep(2)
                    continue
                break  # Non-transient error, fail immediately
        return ExecResult("", str(last_error), 1)

    def exec_with_env(
        self,
        vmid: int,
        command: str,
        env: Dict[str, str],
        user: str = "root",
        node: Optional[str] = None,
    ) -> ExecResult:
        env_str = " ".join([f"{k}='{v}'" for k, v in env.items()])
        full_cmd = f"export {env_str} && {command}"
        return self.exec(vmid, full_cmd, user, node)

    def push_file(
        self,
        vmid: int,
        local_path: str,
        remote_path: str,
        user: str = "root",
        node: Optional[str] = None,
    ) -> None:
        """Push a file to the container using pct exec with base64 encoding."""
        node = node or self._get_node()

        with open(local_path, "rb") as f:
            raw_bytes = f.read()
        data = base64.b64encode(raw_bytes).decode()

        chunk_size = 800  # Reduced to avoid shell length limits

        # Ensure parent directory exists
        self.exec(vmid, f"mkdir -p $(dirname {remote_path})", user, node)
        # Clear target file
        self.exec(vmid, f"> {remote_path}", user, node)

        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            # Use printf for binary-safe chunk writing
            self.exec(vmid, f"printf '%s' '{chunk}' >> {remote_path}.b64", user, node)

        # Decode the full file at once
        self.exec(
            vmid,
            f"base64 -d {remote_path}.b64 > {remote_path} && rm {remote_path}.b64",
            user,
            node,
        )

    def wait_for_network(
        self, vmid: int, timeout: int = 120, node: Optional[str] = None
    ) -> bool:
        node = node or self._get_node()
        for _ in range(timeout // 2):
            result = self.exec(vmid, "ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && echo OK")
            if "OK" in result.stdout:
                return True
            time.sleep(2)
        return False

    def wait_for_port(
        self, vmid: int, port: int, timeout: int = 60, node: Optional[str] = None
    ) -> bool:
        node = node or self._get_node()
        for _ in range(timeout // 2):
            result = self.exec(vmid, f"ss -tlnp | grep -q ':{port} ' && echo OK")
            if "OK" in result.stdout:
                return True
            time.sleep(2)
        return False

    def get_container_ip(self, vmid: int, node: Optional[str] = None) -> Optional[str]:
        """Try to get IP from guest agent or network config."""
        node = node or self._get_node()
        result = self.exec(
            vmid, "ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1"
        )
        ip = result.stdout.strip()
        if ip:
            return ip
        return None

    def is_vmid_used(self, vmid: int, node: Optional[str] = None) -> bool:
        node = node or self._get_node()
        try:
            self.api.nodes(node).lxc(vmid).status.current.get()
            return True
        except Exception:
            return False

    def get_used_vmids(self, node: Optional[str] = None) -> List[int]:
        node = node or self._get_node()
        containers = self.list_containers(node)
        return [c.vmid for c in containers]

    def get_used_ips(self, node: Optional[str] = None) -> List[str]:
        node = node or self._get_node()
        ips = []
        for ct in self.list_containers(node):
            ip = self.get_container_ip(ct.vmid, node)
            if ip:
                ips.append(ip)
        return ips

    def patch_lxc_config(
        self,
        vmid: int,
        lines: Dict[str, str],
        node: Optional[str] = None,
    ) -> None:
        """Append raw key/value lines to /etc/pve/lxc/<vmid>.conf.

        Used to inject device passthrough rules (e.g. /dev/kvm) into LXC
        containers.  The remote helper script uses a simple append; callers
        should ensure idempotency where required.
        """
        node = node or self._get_node()
        config_path = f"/etc/pve/lxc/{vmid}.conf"
        for key, value in lines.items():
            line = f"{key}: {value}"
            quoted_line = line.replace("'", "'\"'\"'")
            cmd = f"grep -qFx '{quoted_line}' {config_path} || echo '{quoted_line}' >> {config_path}"
            self.exec(vmid, cmd, "root", node)

    def get_lxc_config(self, vmid: int, node: Optional[str] = None) -> Dict[str, str]:
        """Read raw config lines from /etc/pve/lxc/<vmid>.conf.

        Returns a dict of key:value for keys that use the colon syntax.
        """
        node = node or self._get_node()
        result = self.exec(vmid, f"cat /etc/pve/lxc/{vmid}.conf", "root", node)
        out: Dict[str, str] = {}
        for line in result.stdout.strip().splitlines():
            if ":" in line and not line.startswith("#"):
                key, value = line.split(":", 1)
                out[key.strip()] = value.strip()
        return out
