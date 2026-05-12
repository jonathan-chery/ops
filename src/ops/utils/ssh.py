import os
import socket
from pathlib import Path
from typing import Tuple, Optional, List

import paramiko
from paramiko import Ed25519Key


class SSHOnboardManager:
    """Manages SSH-based onboarding of remote endpoints (Proxmox hosts, etc.).

    Uses the ops Ed25519 key (managed by ``SSHKeyManager``) to establish
    key-based authentication on remote hosts via an initial password login.
    """

    def __init__(self, ssh_dir: Path):
        self.ssh_dir = Path(ssh_dir)
        self._key_mgr = SSHKeyManager(self.ssh_dir)

    def discover_endpoint_type(self, host: str) -> str:
        """Attempt to detect the endpoint type from open ports.

        Returns one of: ``proxmox``, ``docker``, ``kubernetes``, ``ssh``.
        """
        # Port 8006 is a strong indicator of Proxmox VE
        try:
            with socket.create_connection((host, 8006), timeout=3):
                return "proxmox"
        except (socket.timeout, OSError):
            pass
        return "ssh"

    def _ops_key_paths(self) -> Tuple[Path, Path]:
        """Return (private_key_path, public_key_path) for the ops keypair."""
        private_path, public_path = self._key_mgr.generate_keypair("ops")
        return Path(private_path), Path(public_path)

    def _test_ssh_key(
        self, hostname: str, username: str, port: int = 22
    ) -> Optional[paramiko.SSHClient]:
        """Probe whether key-based auth already works."""
        private_path, _ = self._ops_key_paths()
        if not private_path.exists():
            return None
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname,
                port=port,
                username=username,
                key_filename=str(private_path),
                timeout=5,
                look_for_keys=False,
            )
            return client
        except paramiko.AuthenticationException:
            return None
        except Exception:
            return None

    def onboard_host(
        self,
        hostname: str,
        username: str,
        port: int = 22,
        password: Optional[str] = None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """Install the ops public key on a remote host via password authentication.

        If *password* is not provided and the host does not already support
        key auth, the connection will fail.
        """
        # Generate ops keys if they don't exist yet.
        private_path, public_path = self._ops_key_paths()
        public_key = public_path.read_text().strip()

        if not force:
            existing = self._test_ssh_key(hostname, username, port)
            if existing:
                existing.close()
                return True, "Already onboarded (key auth works)"

        # Connect via password and install the public key
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname,
                port=port,
                username=username,
                password=password,
                timeout=10,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException:
            return False, "Password authentication failed"
        except Exception as exc:
            return False, f"SSH connection failed: {exc}"

        # Install public key into authorized_keys
        commands = [
            "mkdir -p ~/.ssh",
            f"chmod 700 ~/.ssh",
            f"echo '{public_key}' >> ~/.ssh/authorized_keys",
            "chmod 600 ~/.ssh/authorized_keys",
        ]
        for cmd in commands:
            stdin, stdout, stderr = client.exec_command(cmd)
            _ = stdout.channel.recv_exit_status()

        client.close()
        return True, f"Successfully onboarded {username}@{hostname}"

    def rotate_key_for_all_hosts(
        self, hosts: List
    ) -> Tuple[bool, str]:
        """Regenerate the ops keypair and push the new public key to all *hosts*.

        Returns ``(True, message)`` on full success or
        ``(False, error_message)`` on any failure.
        """
        private_path, public_path = self._ops_key_paths()

        # Backup old keys
        old_private = Path(str(private_path) + ".old")
        old_public = Path(str(public_path) + ".old")
        if private_path.exists():
            private_path.rename(old_private)
        if public_path.exists():
            public_path.rename(old_public)

        try:
            self._key_mgr.generate_keypair("ops")
        except Exception as exc:
            # Restore old keys on failure
            if old_private.exists():
                old_private.rename(private_path)
            if old_public.exists():
                old_public.rename(public_path)
            return False, f"Key regeneration failed: {exc}"

        new_public_key = public_path.read_text().strip()
        failed_hosts = []
        for h in hosts:
            if not h.ssh_onboarded:
                continue
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    h.host,
                    port=getattr(h, "port", 22),
                    username=getattr(h, "user", "root"),
                    key_filename=str(old_private),
                    timeout=10,
                    look_for_keys=False,
                )
                # Remove old key and add new key
                stdin, stdout, stderr = client.exec_command(
                    "sed -i '/ssh-ed25519/d' ~/.ssh/authorized_keys"
                )
                _ = stdout.channel.recv_exit_status()
                stdin, stdout, stderr = client.exec_command(
                    f"echo '{new_public_key}' >> ~/.ssh/authorized_keys"
                )
                _ = stdout.channel.recv_exit_status()
                client.close()
            except Exception as exc:
                failed_hosts.append(f"{h.name}: {exc}")

        # Clean up old keys
        if old_private.exists():
            old_private.unlink()
        if old_public.exists():
            old_public.unlink()

        if failed_hosts:
            return False, f"Rotation completed with {len(failed_hosts)} failures: {', '.join(failed_hosts)}"
        return True, "Key rotated and updated on all hosts"


class SSHKeyManager:
    def __init__(self, secrets_dir: Path):
        self.secrets_dir = secrets_dir

    def _key_path(self, name: str) -> Path:
        return self.secrets_dir / f"ssh_{name}_ed25519"

    def generate_keypair(self, name: str) -> Tuple[str, str]:
        """Generate an Ed25519 key pair. Returns (private_path, public_path)."""
        private_path = self._key_path(name)
        public_path = Path(str(private_path) + ".pub")

        if private_path.exists() and public_path.exists():
            return str(private_path), str(public_path)

        key = Ed25519Key.generate()  # type: ignore[attr-defined]
        key.write_private_key_file(str(private_path))
        os.chmod(private_path, 0o600)

        public_key = f"ssh-ed25519 {key.get_base64()} {name}@{name}"
        public_path.write_text(public_key)
        os.chmod(public_path, 0o644)

        return str(private_path), str(public_path)

    def get_public_key(self, name: str) -> str:
        public_path = Path(str(self._key_path(name)) + ".pub")
        if not public_path.exists():
            self.generate_keypair(name)
        return public_path.read_text().strip()

    def get_private_key(self, name: str) -> str:
        private_path = self._key_path(name)
        if not private_path.exists():
            self.generate_keypair(name)
        return str(private_path)

    def ssh_client(
        self, name: str, hostname: str, username: str, port: int = 22
    ) -> paramiko.SSHClient:
        private_path = self.get_private_key(name)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname, port=port, username=username, key_filename=private_path
        )
        return client
