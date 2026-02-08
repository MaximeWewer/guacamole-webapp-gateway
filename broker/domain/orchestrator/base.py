"""
Base classes and protocols for container orchestration.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ContainerInfo:
    """Information about a spawned container/pod."""

    container_id: str  # Docker container ID or Kubernetes Pod name
    container_ip: str  # IP address of the container/pod
    backend: str  # "docker" or "kubernetes"


class ContainerOrchestrator(Protocol):
    """Protocol defining the interface for container orchestration backends."""

    def spawn_container(
        self, session_id: str, username: str, vnc_password: str
    ) -> ContainerInfo:
        """
        Spawn a VNC container/pod.

        Args:
            session_id: Session identifier
            username: Username
            vnc_password: VNC password

        Returns:
            ContainerInfo with container details
        """
        ...

    def destroy_container(self, container_id: str) -> None:
        """
        Destroy a VNC container/pod.

        Args:
            container_id: Docker container ID or Kubernetes Pod name
        """
        ...

    def is_container_running(self, container_id: str) -> bool:
        """
        Check if a container/pod is running.

        Args:
            container_id: Docker container ID or Kubernetes Pod name

        Returns:
            True if running, False otherwise
        """
        ...

    def get_running_count(self) -> int:
        """
        Get count of running VNC containers/pods.

        Returns:
            Number of running containers
        """
        ...

    def list_managed_containers(self) -> list[dict]:
        """
        List all managed containers/pods.

        Returns:
            List of container info dictionaries with keys:
            - id: container ID or pod name
            - name: container/pod name
            - status: running status
            - labels: dict of labels
        """
        ...

    def get_containers_memory_gb(self) -> float:
        """
        Get total memory used by VNC containers/pods in GB.

        Returns:
            Memory usage in GB
        """
        ...

    def get_pool_containers(self) -> list[dict]:
        """
        Get list of available pool containers (running, unclaimed).

        Returns:
            List of pool container info dictionaries with keys:
            - id: container ID or pod name
            - session_id: session identifier
            - ip: container IP address
        """
        ...

    def claim_container(self, container_id: str, username: str) -> bool:
        """
        Claim a pool container for a specific user.

        Args:
            container_id: Container ID or pod name
            username: Username to assign

        Returns:
            True if claimed successfully, False otherwise
        """
        ...
