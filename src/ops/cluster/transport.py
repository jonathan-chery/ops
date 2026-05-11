"""Pluggable cluster transport: SSH (default) and HTTPS (opt-in)."""

from abc import ABC, abstractmethod
from typing import Dict

from ops.models.cluster import OpsNode
from ops.models.blueprint import AppBlueprint
from ops.models.state import DeploymentState


class ClusterTransport(ABC):
    """Abstract interface for deploying workloads to remote cluster nodes."""

    @abstractmethod
    def deploy_on_node(
        self, node: OpsNode, app_name: str, blueprint: AppBlueprint
    ) -> DeploymentState:
        """Deploy an application on a remote node and return its state."""
        pass

    @abstractmethod
    def get_node_status(self, node: OpsNode) -> Dict[str, str]:
        """Query the remote node for its current status."""
        pass

    @abstractmethod
    def is_available(self, node: OpsNode) -> bool:
        """Return True if the transport can reach the node."""
        pass
