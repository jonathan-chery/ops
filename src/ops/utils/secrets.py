import os
import base64
from pathlib import Path
from typing import Dict


from ..core.config import ConfigManager
from ..models.secrets import SecretValue
from ..models.blueprint import SecretConfig


class SecretManager:
    def __init__(self, config_manager: ConfigManager, app_name: str):
        self.config = config_manager
        self.app_name = app_name
        self.secrets_dir = config_manager.get_secrets_dir(app_name)
        self._fernet = config_manager._get_fernet()

    # Public interface for CLI use
    @property
    def secret_path(self) -> Path:
        """Return the base directory for this app's secrets."""
        return self.secrets_dir

    def _secret_file(self, name: str, ext: str = "secret") -> Path:
        return self.secrets_dir / f"{name}.{ext}"

    def _load_encrypted(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Secret file not found: {path}")
        data = path.read_bytes()
        return self._fernet.decrypt(data).decode()

    def _save_encrypted(self, path: Path, value: str):
        path.write_bytes(self._fernet.encrypt(value.encode()))
        os.chmod(path, 0o600)

    def generate_secret(self, name: str, length: int = 32) -> str:
        """Generate a cryptographically secure secret."""
        raw = os.urandom(length)
        # Base64 encode to make it printable, trim to desired length
        value = base64.urlsafe_b64encode(raw).decode()[:length]
        self._save_encrypted(self._secret_file(name), value)
        return value

    def resolve_secret(self, cfg: SecretConfig) -> SecretValue:
        if cfg.type == "generated":
            path = self._secret_file(cfg.name)
            if path.exists():
                value = self._load_encrypted(path)
            else:
                value = self.generate_secret(cfg.name, cfg.length)
            return SecretValue(name=cfg.name, value=value, source="generated", encrypted_at_rest=True)

        elif cfg.type == "prompt":
            import typer
            value = typer.prompt(f"Enter secret '{cfg.name}'", hide_input=True)
            self._save_encrypted(self._secret_file(cfg.name), value)
            return SecretValue(name=cfg.name, value=value, source="prompt", encrypted_at_rest=True)

        elif cfg.type == "file":
            if not cfg.source_path:
                raise ValueError(f"Secret '{cfg.name}' type=file requires source_path")
            src = Path(cfg.source_path).expanduser()
            if not src.exists():
                if cfg.required:
                    raise FileNotFoundError(f"Secret file not found: {src}")
                return SecretValue(name=cfg.name, value="", source="file", encrypted_at_rest=False)
            value = src.read_text().strip()
            self._save_encrypted(self._secret_file(cfg.name), value)
            return SecretValue(name=cfg.name, value=value, source="file", encrypted_at_rest=True)

        elif cfg.type == "infisical":
            # Will be resolved by InfisicalProvider in the orchestrator
            # For now, return placeholder; orchestrator fills in actual value
            return SecretValue(name=cfg.name, value="", source="infisical", encrypted_at_rest=False)

        else:
            raise ValueError(f"Unknown secret type: {cfg.type}")

    def get_all_secrets(self) -> Dict[str, str]:
        """Load all locally stored secrets for this app."""
        secrets = {}
        for f in self.secrets_dir.glob("*.secret"):
            name = f.stem
            try:
                secrets[name] = self._load_encrypted(f)
            except Exception:
                continue
        return secrets

    def rotate_secret(self, name: str, length: int = 32) -> str:
        """Regenerate a generated secret."""
        return self.generate_secret(name, length)

    def delete_secret(self, name: str) -> bool:
        """Delete a single secret file."""
        path = self._secret_file(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def cleanup(self):
        """Remove all secrets for this app."""
        for f in self.secrets_dir.glob("*"):
            f.unlink()
        if self.secrets_dir.exists():
            self.secrets_dir.rmdir()
