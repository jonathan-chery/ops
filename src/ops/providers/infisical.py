from typing import Optional

from ..models.config import InfisicalConfig
from ..models.secrets import SecretValue


class InfisicalProvider:
    def __init__(self, config: InfisicalConfig):
        self.config = config
        self._client = None
        self._initialized = False

    def _init_client(self):
        if self._initialized:
            return
        try:
            from infisical_sdk import InfisicalSDKClient

            self._client = InfisicalSDKClient(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                url=self.config.url,
            )
            self._initialized = True
        except ImportError:
            raise RuntimeError("infisicalsdk package not installed")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Infisical client: {e}")

    def get_secret(
        self, path: str, key: str, environment: str = "dev"
    ) -> Optional[str]:
        if not self.config.client_id or not self.config.client_secret:
            return None
        self._init_client()
        try:
            response = self._client.secrets.get_secret(
                secretPath=path,
                env=environment,
                projectId=self.config.project_id,
                projectSlug=self.config.project_slug,
            )
            return response.get("secretValue")
        except Exception:
            return None

    def resolve_secret(
        self, name: str, path: str, key: str, environment: str = "dev"
    ) -> SecretValue:
        value = self.get_secret(path, key, environment)
        if value is None:
            raise RuntimeError(
                f"Secret '{name}' not found in Infisical at path '{path}' key '{key}'"
            )
        return SecretValue(
            name=name, value=value, source="infisical", encrypted_at_rest=False
        )
