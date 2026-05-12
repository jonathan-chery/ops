import os
import base64
from pathlib import Path
from typing import Optional

import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import keyring

from ..models.config import OpsConfig


class ConfigManager:
    def __init__(self, config_path: str = "~/.ops/config.yaml"):
        self.config_path = Path(config_path).expanduser()
        self.secrets_dir = self.config_path.parent / "secrets"
        self._ensure_dirs()
        self._config: Optional[OpsConfig] = None
        self._master_key: Optional[bytes] = None

    def _ensure_dirs(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets_dir, 0o700)

    def _get_or_create_master_key(self) -> bytes:
        if self._master_key:
            return self._master_key

        service_name = "ops-cli"
        key_name = "master-key"

        # Try OS keyring first
        try:
            stored_key = keyring.get_password(service_name, key_name)
            if stored_key:
                self._master_key = base64.urlsafe_b64decode(stored_key.encode())
                return self._master_key
        except Exception:
            pass

        # Fallback: derive from a password file
        key_file = self.config_path.parent / ".master_key"
        if key_file.exists():
            key_data = key_file.read_bytes()
            salt = key_data[:16]
            key_material = key_data[16:]
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480000,
            )
            self._master_key = base64.urlsafe_b64encode(kdf.derive(key_material))
            return self._master_key

        # Generate new master key
        key_material = Fernet.generate_key()
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        self._master_key = base64.urlsafe_b64encode(kdf.derive(key_material))

        # Try to store in keyring
        try:
            keyring.set_password(
                service_name,
                key_name,
                base64.urlsafe_b64encode(self._master_key).decode(),
            )
        except Exception:
            # Fallback: store in password file
            key_file.write_bytes(salt + key_material)
            os.chmod(key_file, 0o600)

        return self._master_key

    def _get_fernet(self) -> Fernet:
        return Fernet(self._get_or_create_master_key())

    def encrypt_value(self, plaintext: str) -> str:
        f = self._get_fernet()
        return f"ENC[{f.encrypt(plaintext.encode()).decode()}]"

    def decrypt_value(self, ciphertext: str) -> str:
        if not ciphertext.startswith("ENC[") or not ciphertext.endswith("]"):
            return ciphertext
        inner = ciphertext[4:-1]
        f = self._get_fernet()
        return f.decrypt(inner.encode()).decode()

    def _process_config_values(self, data: dict, encrypt: bool = False) -> dict:
        """Recursively encrypt/decrypt config values."""
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self._process_config_values(value, encrypt)
            elif isinstance(value, str):
                if (
                    encrypt
                    and not value.startswith("ENC[")
                    and key
                    in ("token_value", "client_secret", "admin_password", "password")
                ):
                    result[key] = self.encrypt_value(value)
                elif not encrypt and value.startswith("ENC["):
                    result[key] = self.decrypt_value(value)
                else:
                    result[key] = value
            else:
                result[key] = value
        return result

    def load(self) -> OpsConfig:
        if self._config:
            return self._config

        if not self.config_path.exists():
            default_config = self._generate_default_config()
            self.save(default_config)
            self._config = default_config
            return default_config

        with open(self.config_path, "r") as f:
            raw = yaml.safe_load(f)

        decrypted = self._process_config_values(raw, encrypt=False)
        self._config = OpsConfig(**decrypted)
        return self._config

    def save(self, config: OpsConfig):
        data = config.model_dump(mode="json")
        encrypted = self._process_config_values(data, encrypt=True)
        with open(self.config_path, "w") as f:
            yaml.dump(encrypted, f, default_flow_style=False, sort_keys=False)
        os.chmod(self.config_path, 0o600)

    def _generate_default_config(self) -> OpsConfig:
        return OpsConfig()

    def get_secrets_dir(self, app_name: str) -> Path:
        d = self.secrets_dir / app_name
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        return d
