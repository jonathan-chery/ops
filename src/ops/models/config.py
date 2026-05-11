from typing import List, Optional
from ipaddress import IPv4Address, IPv4Network
from pydantic import BaseModel, Field, field_validator

from ops.models.cluster import ClusterConfig


class NetworkConfig(BaseModel):
    bridge: str = "vmbr1"
    gateway: IPv4Address = IPv4Address("10.0.0.254")
    subnet: IPv4Network = IPv4Network("10.0.0.0/24")
    dns: List[str] = Field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])

    @field_validator("dns", mode="before")
    @classmethod
    def validate_dns(cls, v):
        if isinstance(v, str):
            return v.split()
        return v


class StorageConfig(BaseModel):
    pool: str = "local"
    disk_size: int = 20


class InfisicalConfig(BaseModel):
    url: str = "https://app.infisical.com"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    project_id: Optional[str] = None
    project_slug: Optional[str] = None
    default_path: str = "/"


class DatabaseConfig(BaseModel):
    host: Optional[str] = None
    port: int = 5432
    admin_user: Optional[str] = None
    admin_password: Optional[str] = None
    ssl_mode: str = "prefer"


class DefaultsConfig(BaseModel):
    environment: str = "dev"
    template: str = "ubuntu-24.04-standard"
    auto_teardown_on_failure: bool = True


class HostConfig(BaseModel):
    """Generic onboarded host configuration. Supports multiple host types."""

    name: str
    type: str = "proxmox"
    host: str
    port: int = 22
    user: str = "root"
    password: Optional[str] = None
    ssh_onboarded: bool = False


class ProxmoxHostConfig(HostConfig):
    """Proxmox-specific host configuration."""

    type: str = "proxmox"
    token_name: str = "ops-token"
    token_value: str = "placeholder"
    verify_ssl: bool = True
    node: Optional[str] = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v):
        if v != "proxmox":
            raise ValueError("ProxmoxHostConfig type must be 'proxmox'")
        return v

    @field_validator("host")
    @classmethod
    def _validate_host(cls, v):
        """Reject shell metacharacters in host string."""
        bad = set(";|\u0026$`'\"\n\r\u003c\u003e")
        if any(c in v for c in bad):
            raise ValueError(f"Host contains forbidden characters: {v}")
        return v

    @field_validator("verify_ssl", mode="after")
    @classmethod
    def _warn_insecure(cls, v):
        if not v:
            import warnings

            warnings.warn(
                "WARNING: TLS verification disabled for Proxmox API. "
                "MITM attacks are possible. Set verify_ssl=true in config.",
                stacklevel=2,
            )
        return v


class ProxmoxConfig(BaseModel):
    """Legacy single-host Proxmox config. Deprecated -- retained for migration."""

    host: str = "pve.local"
    user: str = "root"
    token_name: str = "ops-token"
    token_value: str = "placeholder"
    verify_ssl: bool = False
    node: Optional[str] = None


class OpsConfig(BaseModel):
    """Top-level ops configuration supporting multiple hosts and clustering."""

    hosts: List[ProxmoxHostConfig] = Field(default_factory=list)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    infisical: InfisicalConfig = Field(default_factory=InfisicalConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)

    # Backwards-compatibility: if hosts is empty, ConfigManager auto-migrates
    # the legacy flat `proxmox:` block into hosts[0].
    proxmox: Optional[ProxmoxConfig] = None
