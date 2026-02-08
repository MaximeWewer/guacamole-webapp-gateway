"""
Docker implementation of container orchestration.
"""

import logging
import os

import docker
import docker.errors
import docker.types

from broker.config.loader import BrokerConfig
from broker.domain.orchestrator.base import ContainerInfo

logger = logging.getLogger("session-broker")


class DockerOrchestrator:
    """Docker-based container orchestrator."""

    def __init__(self) -> None:
        """Initialize Docker client."""
        self._client = docker.from_env()

    @property
    def client(self) -> docker.DockerClient:
        """Get the Docker client."""
        return self._client

    def _get_network(self) -> str:
        """
        Get or create Docker network for VNC containers.

        Returns:
            Network name
        """
        settings = BrokerConfig.settings()
        network_name = settings.orchestrator.docker.network or settings.containers.network
        try:
            self._client.networks.get(network_name)
        except docker.errors.NotFound:
            logger.info(f"Creating network {network_name}")
            self._client.networks.create(network_name, driver="bridge")
        return network_name

    def spawn_container(
        self, session_id: str, username: str | None, vnc_password: str
    ) -> ContainerInfo:
        """
        Spawn a VNC container connected to Docker network.

        Args:
            session_id: Session identifier
            username: Username (None for pool containers)
            vnc_password: VNC password

        Returns:
            ContainerInfo with container details
        """
        container_name = f"vnc-{session_id}"

        # Get container settings from config
        containers_cfg = BrokerConfig.settings().containers
        vnc_image = containers_cfg.image
        mem_limit = containers_cfg.memory_limit
        shm_size = containers_cfg.shm_size

        vnc_network = self._get_network()

        # For pool containers (no username), use default config
        homepage = "about:blank"
        environment = {
            "VNC_PW": vnc_password,
            "VNC_RESOLUTION": "1920x1080",
            "VNC_COL_DEPTH": "24",
            "STARTING_URL": homepage,
        }
        labels = {
            "guac.session.id": session_id,
            "guac.managed": "true",
            "guac.pool": "true" if not username else "false",
        }

        if username:
            # Import here to avoid circular imports
            from broker.domain.user_profile import UserProfile

            # Get user configuration from profiles.yml
            user_config = UserProfile.get_config(username)
            homepage = user_config.get("homepage", "about:blank")
            bookmarks = user_config.get("bookmarks", [])
            autofill = user_config.get("autofill", [])

            # Detect browser type from image name
            browser = BrokerConfig.get_browser_type()

            # Apply browser policies (bookmarks, homepage, autofill)
            UserProfile.set_browser_policies(username, bookmarks, homepage, autofill)
            logger.info(
                f"Applied {browser} policies for {username}: "
                f"{len(bookmarks)} bookmarks, homepage={homepage}"
            )

            environment["STARTING_URL"] = homepage
            environment["GUAC_USERNAME"] = username
            labels["guac.username"] = username

        # Build volume mounts using Docker volume name for user data
        user_profiles_volume = os.environ.get(
            "USER_PROFILES_VOLUME", "guacamole_user_profiles"
        )
        mounts = [
            docker.types.Mount(
                target="/user-data",
                source=user_profiles_volume,
                type="volume",
                read_only=False,
            ),
        ]

        container = self._client.containers.run(
            vnc_image,
            name=container_name,
            detach=True,
            environment=environment,
            mounts=mounts,
            labels=labels,
            mem_limit=mem_limit,
            shm_size=shm_size,
            auto_remove=False,
            network=vnc_network,
        )

        # Wait for container to get IP
        container.reload()
        container_ip = container.attrs["NetworkSettings"]["Networks"][vnc_network][
            "IPAddress"
        ]

        logger.info(f"Container {container_name} started with IP {container_ip}")
        return ContainerInfo(
            container_id=container.id, container_ip=container_ip, backend="docker"
        )

    def destroy_container(self, container_id: str) -> None:
        """
        Destroy a VNC container.

        Args:
            container_id: Docker container ID
        """
        try:
            container = self._client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove()
            logger.info(f"Container {container_id[:12]} destroyed")
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"Error destroying container: {e}")

    def is_container_running(self, container_id: str) -> bool:
        """
        Check if a container is running.

        Args:
            container_id: Docker container ID

        Returns:
            True if running, False otherwise
        """
        try:
            container = self._client.containers.get(container_id)
            return bool(container.status == "running")
        except docker.errors.NotFound:
            return False
        except Exception as e:
            logger.warning(f"Error checking container status: {e}")
            return False

    def get_running_count(self) -> int:
        """
        Get count of running VNC containers.

        Returns:
            Number of running containers
        """
        try:
            containers = self._client.containers.list(
                filters={"label": "guac.managed=true", "status": "running"}
            )
            return len(containers)
        except Exception:
            return 0

    def list_managed_containers(self) -> list[dict]:
        """
        List all managed containers.

        Returns:
            List of container info dictionaries
        """
        result = []
        try:
            containers = self._client.containers.list(
                all=True, filters={"label": "guac.managed=true"}
            )
            for container in containers:
                result.append(
                    {
                        "id": container.id,
                        "name": container.name,
                        "status": container.status,
                        "labels": container.labels,
                    }
                )
        except Exception as e:
            logger.error(f"Error listing containers: {e}")
        return result

    def get_containers_memory_gb(self) -> float:
        """
        Get total memory used by VNC containers in GB.

        Returns:
            Memory usage in GB
        """
        try:
            containers = self._client.containers.list(
                filters={"label": "guac.managed=true", "status": "running"}
            )
            total_bytes = 0
            for container in containers:
                try:
                    stats = container.stats(stream=False)
                    mem_usage = stats.get("memory_stats", {}).get("usage", 0)
                    total_bytes += mem_usage
                except Exception:
                    # Estimate 1GB per container if stats fail
                    total_bytes += 1024 * 1024 * 1024
            return total_bytes / 1024 / 1024 / 1024
        except Exception:
            return 0.0

    def get_pool_containers(self) -> list[dict]:
        """
        Get list of available pool containers (running, unclaimed).

        Returns:
            List of pool container info dictionaries
        """
        result = []
        try:
            containers = self._client.containers.list(
                filters={"label": ["guac.managed=true", "guac.pool=true"], "status": "running"}
            )
            for container in containers:
                labels = container.labels or {}
                # Only include if not yet claimed (no username label)
                if "guac.username" not in labels:
                    # Get container IP
                    container.reload()
                    networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                    container_ip = ""
                    for net_info in networks.values():
                        container_ip = net_info.get("IPAddress", "")
                        if container_ip:
                            break

                    result.append({
                        "id": container.id,
                        "session_id": labels.get("guac.session.id", ""),
                        "ip": container_ip,
                    })
        except Exception as e:
            logger.error(f"Error listing pool containers: {e}")
        return result

    def claim_container(self, container_id: str, username: str) -> bool:
        """
        Claim a pool container for a specific user by updating its labels.

        Note: Docker doesn't support updating labels on running containers.
        We track claiming via session store instead.

        Args:
            container_id: Container ID
            username: Username to assign

        Returns:
            True (always succeeds for Docker, actual claiming is done via session store)
        """
        logger.info(f"Claimed pool container {container_id[:12]} for user {username}")
        return True
