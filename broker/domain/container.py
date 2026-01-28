"""
VNC container management for Docker.
"""

import logging
import os
import secrets
import socket
import time

import docker
import docker.errors
import docker.types

from broker.config.settings import VNC_PORT, VNC_CONTAINER_TIMEOUT, VNC_PASSWORD_LENGTH
from broker.config.loader import BrokerConfig

logger = logging.getLogger("session-broker")

# Docker client
docker_client = docker.from_env()


def get_docker_network():
    """
    Get or create Docker network for VNC containers.

    Returns:
        Docker network object
    """
    network_name = BrokerConfig.get("containers", "network", default="guacamole_vnc-network")
    try:
        return docker_client.networks.get(network_name)
    except docker.errors.NotFound:
        logger.info(f"Creating network {network_name}")
        return docker_client.networks.create(network_name, driver="bridge")


def generate_vnc_password() -> str:
    """
    Generate a secure VNC password.

    Returns:
        Secure random password
    """
    return secrets.token_urlsafe(VNC_PASSWORD_LENGTH)


def spawn_vnc_container(session_id: str, username: str, vnc_password: str) -> tuple[str, str]:
    """
    Spawn a VNC container connected to Docker network.

    Args:
        session_id: Session identifier
        username: Username
        vnc_password: VNC password

    Returns:
        Tuple of (container_id, container_ip)
    """
    # Import here to avoid circular imports
    from broker.domain.user_profile import UserProfile

    container_name = f"vnc-{session_id}"

    # Get container settings from config
    container_config = BrokerConfig.get("containers", default={})
    vnc_image = container_config.get("image", "vnc-browser:latest")
    vnc_network = container_config.get("network", "guacamole_vnc-network")
    mem_limit = container_config.get("memory_limit", "2g")
    shm_size = container_config.get("shm_size", "256m")

    get_docker_network()

    # Get user configuration from profiles.yml
    user_config = UserProfile.get_config(username)
    homepage = user_config.get("homepage", "about:blank")
    bookmarks = user_config.get("bookmarks", [])
    autofill = user_config.get("autofill", [])

    # Detect browser type from image name
    browser = BrokerConfig.get_browser_type()

    # Apply browser policies (bookmarks, homepage, autofill)
    UserProfile.set_browser_policies(username, bookmarks, homepage, autofill)
    logger.info(f"Applied {browser} policies for {username}: {len(bookmarks)} bookmarks, homepage={homepage}")

    # Build volume mounts using Docker volume name for user data
    # Mount full volume - container's start script handles user-specific paths
    user_profiles_volume = os.environ.get("USER_PROFILES_VOLUME", "guacamole_user_profiles")
    mounts = [
        docker.types.Mount(
            target="/user-data",
            source=user_profiles_volume,
            type="volume",
            read_only=False
        ),
    ]

    container = docker_client.containers.run(
        vnc_image,
        name=container_name,
        detach=True,
        environment={
            "VNC_PW": vnc_password,
            "VNC_RESOLUTION": "1920x1080",
            "VNC_COL_DEPTH": "24",
            # "BROWSER": browser,
            "STARTING_URL": homepage,
            "GUAC_USERNAME": username
        },
        mounts=mounts,
        labels={
            "guac.session.id": session_id,
            "guac.managed": "true",
            "guac.username": username
        },
        mem_limit=mem_limit,
        shm_size=shm_size,
        auto_remove=False,
        network=vnc_network
    )

    # Wait for container to get IP
    container.reload()
    container_ip = container.attrs["NetworkSettings"]["Networks"][vnc_network]["IPAddress"]

    logger.info(f"Container {container_name} started with IP {container_ip}")
    return container.id, container_ip


def destroy_container(container_id: str) -> None:
    """
    Destroy a VNC container.

    Args:
        container_id: Docker container ID
    """
    try:
        container = docker_client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove()
        logger.info(f"Container {container_id[:12]} destroyed")
    except docker.errors.NotFound:
        pass
    except Exception as e:
        logger.error(f"Error destroying container: {e}")


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
    Check if a container is running.

    Args:
        container_id: Docker container ID

    Returns:
        True if running, False otherwise
    """
    try:
        container = docker_client.containers.get(container_id)
        return container.status == "running"
    except docker.errors.NotFound:
        return False
    except Exception as e:
        logger.warning(f"Error checking container status: {e}")
        return False
