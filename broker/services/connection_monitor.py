"""
Connection monitoring service for active connections.
"""

import logging
import threading
import time

from broker.config.loader import BrokerConfig
from broker.domain.session import SessionStore
from broker.domain.guacamole import guac_api
from broker.domain.container import destroy_container
from broker.services.provisioning import on_connection_start, on_connection_end

logger = logging.getLogger("session-broker")


class ConnectionMonitor:
    """Background service to monitor active connections."""

    def __init__(self, interval: int = 5):
        """
        Initialize connection monitor.

        Args:
            interval: Check interval in seconds
        """
        self.interval = interval
        self.active_connections: set = set()
        self.running = False
        self._cleanup_counter = 0

    def start(self) -> None:
        """Start the monitor service."""
        self.running = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        logger.info("Connection monitor started")

    def _monitor_loop(self) -> None:
        """Main monitor loop."""
        while self.running:
            try:
                active = guac_api.get_active_connections()
                current = {c.get("connectionIdentifier") for c in active.values() if c.get("connectionIdentifier")}

                # Handle new connections
                for conn_id in current - self.active_connections:
                    info: dict[str, str] = next((c for c in active.values() if c.get("connectionIdentifier") == conn_id), {})
                    on_connection_start(conn_id, info.get("username", "unknown"))

                # Handle ended connections
                for conn_id in self.active_connections - current:
                    session = SessionStore.get_session_by_connection(conn_id)
                    if session:
                        on_connection_end(conn_id, session.username or "unknown")

                self.active_connections = current

                # Update Prometheus gauges
                from broker.observability import ACTIVE_CONNECTIONS, collect_business_metrics
                ACTIVE_CONNECTIONS.set(len(current))
                collect_business_metrics()

                # Run cleanup every 60 iterations (~5 minutes with 5s interval)
                self._cleanup_counter += 1
                if self._cleanup_counter >= 60:
                    self._cleanup_counter = 0
                    self.cleanup_inactive_containers()
            except Exception as e:
                logger.error(f"Monitor error: {e}")
            time.sleep(self.interval)

    def cleanup_inactive_containers(self) -> None:
        """
        Clean up containers that have been inactive longer than the timeout.
        Uses lifecycle.idle_timeout_minutes from config.
        """
        timeout_minutes = BrokerConfig.settings().lifecycle.idle_timeout_minutes
        if timeout_minutes <= 0:
            return  # No timeout configured

        try:
            sessions = SessionStore.list_sessions()
            now = time.time()
            timeout_seconds = timeout_minutes * 60
            cleaned = 0

            for session in sessions:
                if session is None:
                    continue
                if not session.container_id:
                    continue

                # Skip if container is currently in use
                if session.guac_connection_id and session.guac_connection_id in self.active_connections:
                    continue

                # Check inactivity timeout
                last_activity = session.last_activity or session.started_at
                if not last_activity:
                    continue

                inactive_seconds = now - last_activity

                if inactive_seconds > timeout_seconds:
                    username = session.username or "unknown"
                    logger.info(f"Cleaning up inactive container for {username} "
                               f"(idle {inactive_seconds/60:.1f}min > {timeout_minutes}min)")
                    destroy_container(session.container_id)
                    session.container_id = None
                    session.container_ip = None
                    SessionStore.save_session(session.session_id, session)
                    cleaned += 1

            if cleaned > 0:
                logger.info(f"Cleanup: {cleaned} idle containers destroyed")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    def force_kill_oldest_inactive(self, count: int = 1) -> int:
        """
        Force kill the oldest inactive containers to free resources.
        Called when resources are low, even if timeout not reached.

        Args:
            count: Number of containers to kill

        Returns:
            Number of containers killed
        """
        try:
            sessions = SessionStore.list_sessions()
            now = time.time()

            # Get inactive sessions with containers, sorted by last_activity (oldest first)
            inactive = []
            for session in sessions:
                if session is None:
                    continue
                if not session.container_id:
                    continue

                if session.guac_connection_id and session.guac_connection_id in self.active_connections:
                    continue  # Skip active connections

                last_activity = session.last_activity or session.started_at or now
                inactive.append((last_activity, session))

            # Sort by last_activity (oldest first)
            inactive.sort(key=lambda x: x[0])

            killed = 0
            for _, session in inactive[:count]:
                username = session.username or "unknown"
                logger.warning(f"Force killing container for {username} (low resources)")
                if session.container_id:
                    destroy_container(session.container_id)
                session.container_id = None
                session.container_ip = None
                SessionStore.save_session(session.session_id, session)
                killed += 1

            return killed

        except Exception as e:
            logger.error(f"Force kill error: {e}")
            return 0


# Global instance
monitor = ConnectionMonitor(interval=5)
