from typing import Optional
from pydantic import BaseModel


class ContainerStatus(BaseModel):
    vmid: int
    hostname: str
    name: Optional[str] = None
    status: str = "unknown"  # running, stopped, unknown
    ip: Optional[str] = None
    uptime: Optional[str] = None
    metrics_enabled: bool = False
    metrics_port: Optional[int] = None


class ContainerInfo(BaseModel):
    vmid: int
    hostname: str
    name: Optional[str] = None
    status: str = "unknown"
    ip: Optional[str] = None
    blueprint_name: Optional[str] = None
    app_name: Optional[str] = None
    uptime: Optional[str] = None
    health_status: Optional[str] = None
    metrics_enabled: bool = False
    metrics_port: Optional[int] = None
