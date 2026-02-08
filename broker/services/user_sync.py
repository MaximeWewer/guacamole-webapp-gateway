"""
User synchronization service for Guacamole users.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
import uuid

from broker.config.settings import VNC_PORT, VNC_CONTAINER_TIMEOUT
from broker.config.loader import BrokerConfig
from broker.domain.session import SessionStore
from broker.domain.container import (
    spawn_vnc_container,
    destroy_container,
    wait_for_vnc,
    generate_vnc_password,
)
from broker.domain.orchestrator import get_orchestrator
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
        self._running = False
        self.last_sync: float = 0
        self.sync_stats: dict[str, Any] = {"total_synced": 0, "last_new_users": [], "errors": 0}
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @running.setter
    def running(self, value: bool) -> None:
        with self._lock:
            self._running = value

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
                prewarm_enabled = BrokerConfig.settings().pool.enabled
                if prewarm_enabled:
                    self.prewarm_containers()
            except Exception as e:
                logger.error(f"Sync error: {e}")
                with self._lock:
                    self.sync_stats["errors"] += 1
            time.sleep(self.interval)

    def get_running_container_count(self) -> int:
        """Get count of running VNC containers/pods."""
        try:
            return get_orchestrator().get_running_count()
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
        """Get total memory used by VNC containers/pods in GB."""
        try:
            return get_orchestrator().get_containers_memory_gb()
        except Exception:
            return 0.0

    def can_start_container(self) -> tuple[bool, str]:
        """
        Check if we can start a new container based on resource limits.

        Returns:
            Tuple of (can_start, reason)
        """
        res = BrokerConfig.settings().pool.resources
        min_free = res.min_free_memory_gb
        max_total = res.max_total_memory_gb
        max_percent = res.max_memory_percent

        # Check minimum free memory
        available = self.get_available_memory_gb()
        if available < min_free:
            return False, f"low free memory ({available:.1f}GB < {min_free}GB)"

        # Check maximum total container memory
        if max_total > 0:
            container_mem = self.get_containers_memory_gb()
            container_limit = BrokerConfig.settings().containers.memory_limit
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
        Maintain the container pool at the target size.
        Creates new pool containers when the pool shrinks below init_containers.
        Respects limits from broker.yml: max containers, batch size, and memory.
        """
        from broker.container import get_services
        monitor = get_services().monitor

        try:
            # Load config from broker.yml
            pool_cfg = BrokerConfig.settings().pool
            if not pool_cfg.enabled:
                return

            max_containers = pool_cfg.max_containers
            batch_size = pool_cfg.batch_size
            target_pool_size = pool_cfg.init_containers

            # Check current container count
            current_count = self.get_running_container_count()
            if current_count >= max_containers:
                logger.debug(f"Pre-warm skipped: at max capacity ({current_count}/{max_containers})")
                return

            # Check how many pool containers we have
            pool_sessions = SessionStore.get_pool_sessions()
            current_pool_size = len(pool_sessions)

            # Calculate how many new pool containers we need
            needed = target_pool_size - current_pool_size
            if needed <= 0:
                return

            # Limit to batch size and respect max containers
            slots_available = min(
                batch_size,
                max_containers - current_count,
                needed
            )

            if slots_available <= 0:
                return

            # Check if we can start a container (memory limits)
            can_start, reason = self.can_start_container()
            if not can_start:
                # Try force kill if enabled
                force_kill = BrokerConfig.settings().lifecycle.force_kill_on_low_resources
                if force_kill:
                    killed = monitor.force_kill_oldest_inactive(count=1)
                    if killed > 0:
                        can_start, reason = self.can_start_container()

                if not can_start:
                    logger.warning(f"Pre-warm skipped: {reason}")
                    return

            started = 0
            for _ in range(slots_available):
                # Re-check resources before each container
                can_start, reason = self.can_start_container()
                if not can_start:
                    # Try force kill if enabled
                    force_kill = BrokerConfig.settings().lifecycle.force_kill_on_low_resources
                    if force_kill:
                        killed = monitor.force_kill_oldest_inactive(count=1)
                        if killed > 0:
                            can_start, reason = self.can_start_container()

                    if not can_start:
                        logger.warning(f"Pre-warm stopped: {reason}")
                        break

                try:
                    session_id = str(uuid.uuid4())[:8]
                    vnc_password = generate_vnc_password()

                    # Spawn pool container without username
                    container_id, container_ip = spawn_vnc_container(
                        session_id, None, vnc_password
                    )

                    if wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
                        # Save pool session (no username, no guac connection yet)
                        SessionStore.save_session(session_id, {
                            "session_id": session_id,
                            "username": None,
                            "guac_connection_id": None,
                            "vnc_password": vnc_password,
                            "container_id": container_id,
                            "container_ip": container_ip,
                            "created_at": time.time(),
                            "started_at": time.time()
                        })

                        started += 1
                        logger.info(f"Pool replenished: container {container_id} ready ({started}/{slots_available})")
                    else:
                        destroy_container(container_id)
                        logger.warning(f"Pre-warm timeout for pool container")
                except Exception as e:
                    logger.warning(f"Pre-warm error: {e}")

            if started > 0:
                logger.info(f"Pre-warm cycle: {started} pool containers added, {self.get_running_container_count()} total")
        except Exception as e:
            logger.error(f"Pre-warm scan error: {e}")

    def init_pool(self) -> None:
        """
        Initialize the container pool at startup.
        Creates pool.init_containers generic containers ready to be claimed.
        """
        pool_cfg = BrokerConfig.settings().pool
        if not pool_cfg.enabled:
            logger.info("Container pool disabled, skipping initialization")
            return

        init_count = pool_cfg.init_containers
        if init_count <= 0:
            return

        # Check how many pool containers already exist
        existing_pool = SessionStore.get_pool_sessions()
        needed = init_count - len(existing_pool)

        if needed <= 0:
            logger.info(f"Pool already has {len(existing_pool)} containers, no init needed")
            return

        logger.info(f"Initializing container pool with {needed} containers...")

        started = 0
        for _ in range(needed):
            # Check resources before each container
            can_start, reason = self.can_start_container()
            if not can_start:
                logger.warning(f"Pool init stopped: {reason}")
                break

            try:
                session_id = str(uuid.uuid4())[:8]
                vnc_password = generate_vnc_password()

                # Spawn pool container without username
                container_id, container_ip = spawn_vnc_container(
                    session_id, None, vnc_password
                )

                if wait_for_vnc(container_ip, port=VNC_PORT, timeout=VNC_CONTAINER_TIMEOUT):
                    # Save pool session (no username, no guac connection yet)
                    SessionStore.save_session(session_id, {
                        "session_id": session_id,
                        "username": None,
                        "guac_connection_id": None,
                        "vnc_password": vnc_password,
                        "container_id": container_id,
                        "container_ip": container_ip,
                        "created_at": time.time(),
                        "started_at": time.time()
                    })

                    started += 1
                    logger.info(f"Pool init: container {container_id} ready ({started}/{needed})")
                else:
                    destroy_container(container_id)
                    logger.warning(f"Pool init timeout for container {container_id}")
            except Exception as e:
                logger.warning(f"Pool init error: {e}")

        logger.info(f"Pool initialization complete: {started} containers started")

    def sync_users(self) -> list:
        """
        Sync users from Guacamole.

        Returns:
            List of newly provisioned usernames
        """
        from broker.container import get_services
        guac_api = get_services().guac_api

        ignored_users = set(BrokerConfig.settings().sync.ignored_users)
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
