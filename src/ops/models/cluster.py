from typing import Optional, Dict, List, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class OpsNode(BaseModel):
    """Represents a discovered or configured cluster node."""

    node_id: str
    name: str
    host: str
    port: int = 22
    api_port: Optional[int] = None
    fingerprint: str
    transport: Literal["ssh", "https"] = "ssh"
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["active", "suspected", "failed"] = "active"
    labels: Dict[str, str] = Field(default_factory=dict)
    resources: Dict[str, int] = Field(default_factory=dict)  # cpu, mem, disk


class ClusterConstraint(BaseModel):
    """Label constraint for node placement."""

    key: str
    op: Literal["eq", "ne", "in", "notin", "exists"]
    value: Optional[str] = None


class ClusterConfig(BaseModel):
    """Cluster and auto-discovery configuration."""

    enabled: bool = False
    secret: Optional[str] = None  # Encrypted shared secret for HMAC beacons
    transport: Literal["ssh", "https"] = "ssh"
    api_port: int = 8443
    advertise_port: int = 9876  # UDP beacon port
    labels: Dict[str, str] = Field(default_factory=dict)
    constraints: List[ClusterConstraint] = Field(default_factory=list)
    discovery: Literal["zeroconf", "udp", "static"] = "udp"
    bootstrap_hosts: List[str] = Field(default_factory=list)  # Static seed IPs
