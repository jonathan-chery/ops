from typing import List, Dict, Optional, Literal, Any
from ipaddress import IPv4Address
from pydantic import BaseModel, Field, field_validator


BLUEPRINT_SCHEMA_VERSION = "1.0"


class ResourceConfig(BaseModel):
    cores: int = 1
    memory: int = 512
    disk: int = 8


class ContainerConfig(BaseModel):
    hostname: str
    cores: int = 1
    memory: int = 512
    disk: int = 8
    vmid: Optional[int] = None
    ip: Optional[IPv4Address] = None


class BlueprintNetworkConfig(BaseModel):
    bridge: Optional[str] = None


class BuildStep(BaseModel):
    cmd: str
    user: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)


class NativeDeploymentConfig(BaseModel):
    git_repo: Optional[str] = None
    tag: Optional[str] = None
    app_dir: str = "/opt/app"
    app_user: str = "appuser"
    build_steps: List[BuildStep] = Field(default_factory=list)
    service_command: str = "./start.sh"
    service_env_file: Optional[str] = None


class DockerDeploymentConfig(BaseModel):
    compose_file: str = "docker-compose.yml"
    service_name: str = "app"
    build_context: Optional[str] = None
    env_file: Optional[str] = None


class DeploymentConfig(BaseModel):
    type: Literal["native", "docker"] = "docker"
    runtime: Optional[str] = None  # nodejs, python
    runtime_version: Optional[int] = None
    native: Optional[NativeDeploymentConfig] = None
    docker: Optional[DockerDeploymentConfig] = None

    @field_validator("native", mode="before")
    @classmethod
    def validate_native(cls, v, info):
        data = info.data
        if data.get("type") == "native" and v is None:
            return NativeDeploymentConfig()
        return v

    @field_validator("docker", mode="before")
    @classmethod
    def validate_docker(cls, v, info):
        data = info.data
        if data.get("type") == "docker" and v is None:
            return DockerDeploymentConfig()
        return v


class SecretConfig(BaseModel):
    name: str
    type: Literal["generated", "infisical", "prompt", "file"] = "generated"
    length: int = 32
    path: Optional[str] = None
    key: Optional[str] = None
    source_path: Optional[str] = None
    required: bool = True


class TemplateConfig(BaseModel):
    source: str
    dest: str
    mode: str = "600"


class BlueprintDatabaseConfig(BaseModel):
    enabled: bool = False
    name: Optional[str] = None


class HealthCheckConfig(BaseModel):
    enabled: bool = False
    url: Optional[str] = None
    method: str = "GET"
    expected_status: int = 200
    retries: int = 30
    interval: int = 5


class AppBlueprint(BaseModel):
    version: str = BLUEPRINT_SCHEMA_VERSION
    name: str
    description: Optional[str] = None
    container: ContainerConfig
    network: BlueprintNetworkConfig = Field(default_factory=BlueprintNetworkConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    dependencies: Dict[str, Any] = Field(default_factory=dict)
    secrets: List[SecretConfig] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)
    templates: List[TemplateConfig] = Field(default_factory=list)
    database: BlueprintDatabaseConfig = Field(default_factory=BlueprintDatabaseConfig)
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        if v != BLUEPRINT_SCHEMA_VERSION:
            raise ValueError(
                f"Blueprint version {v} is not supported. "
                f"Supported version: {BLUEPRINT_SCHEMA_VERSION}"
            )
        return v
