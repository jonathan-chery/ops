from enum import Enum
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class DeploymentPhase(str, Enum):
    PREFLIGHT = "preflight"
    PROVISION = "provision"
    HARDEN = "harden"
    INSTALL = "install"
    DATABASE = "database"
    DEPLOY = "deploy"
    FINALIZE = "finalize"


class DeploymentState(BaseModel):
    app_name: str
    current_phase: DeploymentPhase = DeploymentPhase.PREFLIGHT
    phases_completed: Set[str] = Field(default_factory=set)
    vmid: Optional[int] = None
    ip: Optional[str] = None
    node: Optional[str] = None
    backend: Optional[str] = None  # Cached firecracker backend (microvm or lxc)
    secrets_resolved: Dict[str, str] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed: bool = False

    def mark_phase_complete(self, phase: DeploymentPhase):
        self.phases_completed.add(phase.value)
        self.current_phase = phase
        self.updated_at = datetime.now(timezone.utc)

    def is_phase_complete(self, phase: DeploymentPhase) -> bool:
        return phase.value in self.phases_completed

    def add_error(self, error: str):
        self.errors.append(error)
        self.updated_at = datetime.now(timezone.utc)
