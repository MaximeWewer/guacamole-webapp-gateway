"""
User synchronization service for Guacamole users.
"""

import logging
import threading
import time

from broker.config.settings import VNC_PORT, VNC_CONTAINER_TIMEOUT
from broker.config.loader import BrokerConfig
from broker.domain.session import SessionStore
from broker.domain.guacamole import guac_api
from broker.domain.container import (
    docker_client,
    spawn_vnc_container,
    destroy_container,
    wait_for_vnc,
    generate_vnc_password,
)
from broker.services.provisioning import provision_user_connection

logger = logging.getLogger("session-broker")


class UserSyncService:
    """Background service to sync Guacamole users."""

    def __init__(self, interval: int = 60):
        """
        Initialize sync service.

        Args:
            interval: Sync interval in seconds
        """
        self.interval = interval
        self.running = False
        self.last_sync: float = 0
        self.sync_stats = {"total_synced": 0, "last_new_users": [], "errors": 0}
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the sync service."""
        self.running = True
        threading.Thread(target=self._sync_loop, daemon=True).start()
        logger.info(f"User sync service started (interval: {self.interval}s)")

    def _sync_loop(self) -> None:
        """Main sync loop."""
        time.sleep(10)  # Initial delay
        while self.running:
            try:
                new_users = self.sync_users()
                if new_users:
                    logger.info(f"New users provisioned: {new_users}")

                # Pre-warm containers for existing users
                prewarm_enabled = BrokerConfig.get("pool", "enabled", default=True)
                if prewarm_enabled:
                    self.prewarm_containers()
            except Exception as e:
                logger.error(f"Sync error: {e}")
                with self._lock:
                    self.sync_stats["errors"] += 1
            time.sleep(self.interval)

    def get_running_container_count(self) -> int:
        """Get count of running VNC containers."""
        try:
            containers = docker_client.containers.list(
                filters={"label": "guac.managed=true", "status": "running"}
            )
            return len(containers)
        except Exception:
            return 0

    def get_total_memory_gb(self) -> float:
        """Get total system memory in GB."""
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / 1024 / 1024
        except Exception:
            pass
        return 32.0  # Assume 32GB if can't check

    def get_available_memory_gb(self) -> float:
        """Get available system memory in GB."""
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        return kb / 1024 / 1024
        except Exception:
            pass
        return 999.0  # Assume plenty if can't check

    def get_containers_memory_gb(self) -> float:
        """Get total memory used by VNC containers in GB."""
        try:
            containers = docker_client.containers.list(
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

    def can_start_container(self) -> tuple[bool, str]:
        """
        Check if we can start a new container based on resource limits.

        Returns:
            Tuple of (can_start, reason)
        """
        config = BrokerConfig.get("pool", "resources", default={})
        min_free = config.get("min_free_memory_gb", 2.0)
        max_total = config.get("max_total_memory_gb", 0)
        max_percent = config.get("max_memory_percent", 0)

        # Check minimum free memory
        available = self.get_available_memory_gb()
        if available < min_free:
            return False, f"low free memory ({available:.1f}GB < {min_free}GB)"

        # Check maximum total container memory
        if max_total > 0:
            container_mem = self.get_containers_memory_gb()
            container_limit = BrokerConfig.get("containers", "memory_limit", default="2g")
            # Parse memory limit (e.g., "2g" -> 2.0)
            limit_gb = float(container_limit.rstrip("gGmM"))
            if container_limit.lower().endswith("m"):
                limit_gb /= 1024

            if container_mem + limit_gb > max_total:
                return False, f"max container memory ({container_mem:.1f}GB + {limit_gb}GB > {max_total}GB)"

        # Check maximum memory percentage
        if max_percent > 0:
            total_mem = self.get_total_memory_gb()
            available = self.get_available_memory_gb()
            used_percent = 1 - (available / total_mem)
            if used_percent > max_percent:
                return False, f"max memory percent ({used_percent:.0%} > {max_percent:.0%})"

        return True, "ok"

    def prewarm_containers(self) -> None:
        """
        Pre-warm containers for users who have sessions but no running container.
        Respects limits from broker.yml: max containers, batch size, and memory.
        """
        # Import here to avoid circular imports
        from broker.services.connection_monitor import monitor

        try:
            # Load config from broker.yml
            pool_config = BrokerConfig.get("pool", default={})
            if not pool_config.get("enabled", True):
                return

            max_containers = pool_config.get("max_containers", 10)
            batch_size = pool_config.get("batch_size", 3)

            # Check current container count
            current_count = self.get_running_container_count()
            if current_count >= max_containers:
                logger.debug(f"Pre-warm skipped: at max capacity ({current_count}/{max_containers})")
                return

            # Check if we can start a container (memory limits)
            can_start, reason = self.can_start_container()
            if not can_start:
                # Try force kill if enabled
                force_kill = BrokerConfig.get("lifecycle", "force_kill_on_low_resources", default=True)
                if force_kill:
                    killed = monitor.force_kill_oldest_inactive(count=1)
                    if killed > 0:
                        can_start, reason = self.can_start_container()

                if not can_start:
                    logger.warning(f"Pre-warm skipped: {reason}")
                    return

            sessions = SessionStore.get_sessions_needing_containers()
            if not sessions:
                return

            # Limit to batch size and respect max containers
            slots_available = min(
                batch_size,
                max_containers - current_count,
                len(sessions)
            )

            started = 0
            for session in sessions[:slots_available]:
                username = session.get("username")
                if not username:
                    continue

                # Re-check resources before each container
                can_start, reason = self.can_start_container()
                if not can_start:
                    # Try force kill if enabled
                    force_kill = BrokerConfig.get("lifecycle", "force_kill_on_low_resources", default=True)
                    if force_kill:
                        killed = monitor.force_kill_oldest_inactive(count=1)
                        if killed > 0:
                            can_start, reason = self.can_start_container()

                    if not can_start:
                        logger.warning(f"Pre-warm stopped: {reason}")
                        break

                try:
                    vnc_password = session.get("vnc_password") or generate_vnc_password()
                    session_id = session.get("session_id")

                    container_id, container_ip = spawn_vnc_container(
                        session_id, username, vnc_password
                    )

                    if wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
                        session.update({
                            "container_id": container_id,
                            "container_ip": container_ip,
                            "vnc_password": vnc_password,
                            "started_at": time.time()
                        })
                        SessionStore.save_session(session_id, session)

                        if session.get("guac_connection_id"):
                            guac_api.update_connection(
                                session["guac_connection_id"],
                                container_ip,
                                VNC_PORT,
                                vnc_password
                            )

                        started += 1
                        logger.info(f"Pre-warmed container for {username} ({started}/{slots_available})")
                    else:
                        destroy_container(container_id)
                        logger.warning(f"Pre-warm timeout for {username}")
                except Exception as e:
                    logger.warning(f"Pre-warm error for {username}: {e}")

            if started > 0:
                logger.info(f"Pre-warm cycle: {started} containers started, {self.get_running_container_count()} total")
        except Exception as e:
            logger.error(f"Pre-warm scan error: {e}")

    def init_pool(self) -> None:
        """
        Initialize the container pool at startup.
        Starts pool.init_containers containers for existing sessions without containers.
        """
        pool_config = BrokerConfig.get("pool", default={})
        if not pool_config.get("enabled", True):
            logger.info("Container pool disabled, skipping initialization")
            return

        init_count = pool_config.get("init_containers", 2)
        if init_count <= 0:
            return

        logger.info(f"Initializing container pool with {init_count} containers...")

        # Get sessions that need containers
        sessions = SessionStore.get_sessions_needing_containers()
        if not sessions:
            logger.info("No sessions need containers at startup")
            return

        started = 0
        for session in sessions[:init_count]:
            # Check resources before each container
            can_start, reason = self.can_start_container()
            if not can_start:
                logger.warning(f"Pool init stopped: {reason}")
                break

            username = session.get("username")
            if not username:
                continue

            try:
                vnc_password = session.get("vnc_password") or generate_vnc_password()
                session_id = session.get("session_id")

                container_id, container_ip = spawn_vnc_container(
                    session_id, username, vnc_password
                )

                if wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
                    session.update({
                        "container_id": container_id,
                        "container_ip": container_ip,
                        "vnc_password": vnc_password,
                        "started_at": time.time()
                    })
                    SessionStore.save_session(session_id, session)

                    if session.get("guac_connection_id"):
                        guac_api.update_connection(
                            session["guac_connection_id"],
                            container_ip,
                            VNC_PORT,
                            vnc_password
                        )

                    started += 1
                    logger.info(f"Pool init: container ready for {username} ({started}/{init_count})")
                else:
                    destroy_container(container_id)
                    logger.warning(f"Pool init timeout for {username}")
            except Exception as e:
                logger.warning(f"Pool init error for {username}: {e}")

        logger.info(f"Pool initialization complete: {started} containers started")

    def sync_users(self) -> list:
        """
        Sync users from Guacamole.

        Returns:
            List of newly provisioned usernames
        """
        ignored_users = set(BrokerConfig.get("sync", "ignored_users", default=["guacadmin"]))
        guac_users = set(guac_api.get_users()) - ignored_users
        provisioned = SessionStore.get_provisioned_users()
        new_users = guac_users - provisioned

        result = []
        for username in new_users:
            try:
                provision_user_connection(username)
                result.append(username)
                with self._lock:
                    self.sync_stats["total_synced"] += 1
            except Exception as e:
                logger.error(f"Provisioning error for {username}: {e}")
                with self._lock:
                    self.sync_stats["errors"] += 1

        with self._lock:
            self.sync_stats["last_new_users"] = result
            self.last_sync = time.time()
        return result

    def get_stats(self) -> dict:
        """
        Get sync statistics.

        Returns:
            Statistics dictionary
        """
        with self._lock:
            return {**self.sync_stats, "last_sync": self.last_sync, "interval": self.interval}


# Global instance
user_sync = UserSyncService(interval=BrokerConfig.get("sync", "interval", default=60))
