from typing import List, Optional
from ipaddress import IPv4Address, IPv4Network
from pydantic import BaseModel, Field, field_validator


class ProxmoxConfig(BaseModel):
    host: str = "pve.local"
    user: str = "root"
    token_name: str = "ops-token"
    token_value: str = "placeholder"
    verify_ssl: bool = False
    node: Optional[str] = None


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


class OpsConfig(BaseModel):
    proxmox: ProxmoxConfig = Field(default_factory=ProxmoxConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    infisical: InfisicalConfig = Field(default_factory=InfisicalConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
