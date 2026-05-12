import os
from pathlib import Path
from typing import Tuple

import paramiko
from paramiko import Ed25519Key


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

        key = Ed25519Key.generate()
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
