"""
VNC container management facade.

This module provides a facade over the container orchestration backends
(Docker or Kubernetes), maintaining backward compatibility with existing code.
"""

import logging
import secrets
import socket
import time

from broker.config.settings import VNC_PORT, VNC_CONTAINER_TIMEOUT, VNC_PASSWORD_LENGTH
from broker.domain.orchestrator import get_orchestrator

logger = logging.getLogger("session-broker")


def generate_vnc_password() -> str:
    """
    Generate a secure VNC password.

    Returns:
        Secure random password
    """
    return secrets.token_urlsafe(VNC_PASSWORD_LENGTH)


def spawn_vnc_container(session_id: str, username: str | None, vnc_password: str) -> tuple[str, str]:
    """
    Spawn a VNC container/pod connected to the network.

    Args:
        session_id: Session identifier
        username: Username (None for pool containers)
        vnc_password: VNC password

    Returns:
        Tuple of (container_id, container_ip)
    """
    info = get_orchestrator().spawn_container(session_id, username, vnc_password)
    return info.container_id, info.container_ip


def get_pool_containers() -> list[dict]:
    """
    Get list of available pool containers (running, unclaimed).

    Returns:
        List of pool container info dictionaries with keys:
        - id: container ID or pod name
        - session_id: session identifier
        - ip: container IP address
    """
    return get_orchestrator().get_pool_containers()


def claim_container(container_id: str, username: str) -> bool:
    """
    Claim a pool container for a specific user.

    Args:
        container_id: Container ID or pod name
        username: Username to assign

    Returns:
        True if claimed successfully, False otherwise
    """
    return get_orchestrator().claim_container(container_id, username)


def destroy_container(container_id: str) -> None:
    """
    Destroy a VNC container/pod.

    Args:
        container_id: Docker container ID or Kubernetes Pod name
    """
    get_orchestrator().destroy_container(container_id)


def wait_for_vnc(host: str, port: int = VNC_PORT, timeout: int = VNC_CONTAINER_TIMEOUT) -> bool:
    """
    Wait for VNC server to be available.

    Args:
        host: VNC host
        port: VNC port
        timeout: Timeout in seconds

    Returns:
        True if VNC is available, False on timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def is_container_running(container_id: str) -> bool:
    """
    Check if a container/pod is running.

    Args:
        container_id: Docker container ID or Kubernetes Pod name

    Returns:
        True if running, False otherwise
    """
    return get_orchestrator().is_container_running(container_id)
