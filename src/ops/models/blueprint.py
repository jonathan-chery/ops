from typing import List, Dict, Optional, Literal, Any
from ipaddress import IPv4Address
from pydantic import BaseModel, Field, field_validator, model_validator

BLUEPRINT_SCHEMA_VERSION = "1.2"


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


class LxcMountConfig(BaseModel):
    """Raw LXC config passthrough entry.

    Injected into /etc/pve/lxc/<vmid>.conf after container creation.
    Only used when `deployment.type == 'firecracker'` with `backend='lxc'`.
    """

    key: str
    value: str


class BuildStep(BaseModel):
    cmd: str
    user: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)


class FirecrackerDeploymentConfig(BaseModel):
    """MicroVM deployment using Firecracker.

    Migration path: version 1.1 did not have `backend`, `image`, or
    `firecracker_version`. The `backend` defaults to `pve-microvm` so
    existing blueprints that rely on node-level packages continue to work,
    while new blueprints can opt into `lxc` nested mode.
    """

    backend: Literal["pve-microvm", "lxc"] = "pve-microvm"
    kernel_path: str = ""
    rootfs_path: Optional[str] = None
    rootfs_size_mb: int = 512
    rootfs_source: Literal["built-in", "pre-built"] = "built-in"
    network_mode: Literal["nat", "bridge"] = "nat"
    image: str = ""  # OCI image or pre-built rootfs path for pve-microvm
    firecracker_version: str = "latest"  # Version to download in lxc mode (A1)


class WasmDeploymentConfig(BaseModel):
    """WebAssembly deployment using wasmtime.

    Migration path: version 1.0 blueprints do not include this block.
    Add under `deployment.wasm` when upgrading to schema 1.1.
    """

    artifact: str
    wasi_dirs: List[str] = Field(default_factory=list)
    wasi_network: bool = False
    runtime: Literal["rust", "go", "python", "node"] = "rust"


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
    type: Literal["none", "native", "docker", "firecracker", "wasm"] = "docker"
    runtime: Optional[str] = None  # nodejs, python
    runtime_version: Optional[int] = None
    native: Optional[NativeDeploymentConfig] = None
    docker: Optional[DockerDeploymentConfig] = None
    firecracker: Optional[FirecrackerDeploymentConfig] = None
    wasm: Optional[WasmDeploymentConfig] = None

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

    @field_validator("firecracker", mode="before")
    @classmethod
    def validate_firecracker(cls, v, info):
        data = info.data
        if data.get("type") == "firecracker" and v is None:
            return FirecrackerDeploymentConfig(kernel_path="")
        return v

    @field_validator("wasm", mode="before")
    @classmethod
    def validate_wasm(cls, v, info):
        data = info.data
        if data.get("type") == "wasm" and v is None:
            return WasmDeploymentConfig(artifact="")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        # Allow any valid deployment type
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


class MetricsConfig(BaseModel):
    """Prometheus node_exporter sidecar configuration.

    Opt-out by default (``enabled=True``).  Set ``enabled: false`` in the
    blueprint to skip sidecar installation.
    """

    enabled: bool = True
    scrape_port: int = 9100


class AlertingConfig(BaseModel):
    """Per-application alerting configuration."""

    enabled: bool = False
    webhook_url: Optional[str] = None
    cooldown_seconds: int = 900  # 15 minutes


class HealthCheckConfig(BaseModel):
    enabled: bool = False
    url: Optional[str] = None
    port: Optional[int] = None
    path: Optional[str] = None
    method: str = "GET"
    expected_status: int = 200
    retries: int = 30
    interval: int = 5

    @model_validator(mode="after")
    def validate_url(self):
        if self.url is not None:
            return self
        if self.port is not None and self.path is not None:
            self.url = f"http://{{ip}}:{self.port}{self.path}"
        elif self.port is not None:
            self.url = f"http://{{ip}}:{self.port}"
        return self


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
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        supported = {BLUEPRINT_SCHEMA_VERSION, "1.1"}
        if v not in supported:
            raise ValueError(
                f"Blueprint version {v} is not supported. "
                f"Supported versions: {', '.join(sorted(supported))}"
            )
        return v
