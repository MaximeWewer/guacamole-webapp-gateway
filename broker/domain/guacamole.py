"""
Guacamole API client for REST operations.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests

from broker.resilience import CircuitBreaker, CircuitOpenError, CircuitState

logger = logging.getLogger("session-broker")


class GuacamoleAPI:
    """Client for Guacamole REST API."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        """
        Initialize Guacamole API client.

        Args:
            base_url: Guacamole base URL
            username: Admin username
            password: Admin password
            circuit_breaker: Optional pre-built CircuitBreaker (defaults to a new one)
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.token_expires: float = 0
        self.data_source = "postgresql"
        self._lock = threading.Lock()
        self._circuit = circuit_breaker or CircuitBreaker(name="guacamole")

    @property
    def circuit_healthy(self) -> bool:
        """Whether the Guacamole circuit breaker is CLOSED (healthy)."""
        return self._circuit.state == CircuitState.CLOSED

    def _request(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute an HTTP request through the circuit breaker."""
        return self._circuit.call(method, *args, **kwargs)

    def authenticate(self) -> str:
        """
        Authenticate with Guacamole.  Must be called under ``self._lock``.

        Returns:
            Authentication token
        """
        resp = self._request(
            requests.post,
            f"{self.base_url}/api/tokens",
            data={"username": self.username, "password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["authToken"]
        # Token valid for ~1 hour, refresh at 58 minutes
        self.token_expires = time.time() + 3500
        self.data_source = list(data.get("availableDataSources", ["postgresql"]))[0]
        return self.token

    def _get_auth_params(self) -> tuple[str, str]:
        """Return ``(token, data_source)`` in a thread-safe manner."""
        with self._lock:
            if not self.token or time.time() > self.token_expires:
                self.authenticate()
            assert self.token is not None
            return self.token, self.data_source

    def _invalidate_token(self) -> None:
        """Force token refresh on next API call."""
        with self._lock:
            self.token = None
            self.token_expires = 0

    def _do_request(
        self,
        method: Callable[..., Any],
        path: str,
        *,
        raise_for_status: bool = True,
        timeout: int = 10,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make an authenticated API call with automatic re-auth on 403.

        Args:
            method: HTTP method (requests.get, requests.post, etc.)
            path: API path relative to /api/session/data/{ds}/
            raise_for_status: Whether to raise on non-2xx responses
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to the request

        Returns:
            Response object
        """
        for attempt in range(2):
            token, ds = self._get_auth_params()
            url = f"{self.base_url}/api/session/data/{ds}/{path}"
            resp = self._request(
                method, url, params={"token": token}, timeout=timeout, **kwargs
            )
            if resp.status_code == 403 and attempt == 0:
                logger.warning("Got 403 from Guacamole, forcing re-authentication")
                self._invalidate_token()
                continue
            if raise_for_status:
                resp.raise_for_status()
            return resp
        return resp  # pragma: no cover

    def ensure_auth(self) -> None:
        """Ensure valid authentication token exists."""
        self._get_auth_params()

    def get_users(self) -> list:
        """
        Get list of Guacamole users.

        Returns:
            List of usernames
        """
        resp = self._do_request(requests.get, "users")
        return list(resp.json().keys())

    def get_user_groups(self, username: str) -> list:
        """
        Get groups for a user.

        Args:
            username: Username

        Returns:
            List of group names
        """
        resp = self._do_request(requests.get, f"users/{username}/userGroups")
        return resp.json()

    def get_all_user_groups(self) -> dict:
        """
        Get all user groups in Guacamole.

        Returns:
            Dictionary of group data
        """
        resp = self._do_request(requests.get, "userGroups")
        return resp.json()

    def create_connection(self, name: str, hostname: str, port: int, password: str, username: str = "") -> str:
        """
        Create a VNC connection.

        Args:
            name: Connection name
            hostname: VNC hostname
            port: VNC port
            password: VNC password
            username: Username (for recording filename)

        Returns:
            Connection identifier
        """
        from broker.config.loader import BrokerConfig
        from datetime import datetime

        parameters = {
            "hostname": hostname,
            "port": str(port),
            "password": password,
            "color-depth": "24",
            "clipboard-encoding": "UTF-8",
            "resize-method": "display-update"
        }

        # Add recording parameters if enabled
        recording = BrokerConfig.settings().guacamole.recording
        if recording.enabled:
            parameters["recording-path"] = recording.path
            parameters["recording-include-keys"] = "true" if recording.include_keys else "false"
            parameters["create-recording-path"] = "true" if recording.auto_create_path else "false"

            # Only set recording-name if not empty
            recording_name = recording.name
            if recording_name:
                now = datetime.now()
                recording_name = recording_name.replace("${GUAC_USERNAME}", username or "unknown")
                recording_name = recording_name.replace("${GUAC_DATE}", now.strftime("%Y%m%d"))
                recording_name = recording_name.replace("${GUAC_TIME}", now.strftime("%H%M%S"))
                parameters["recording-name"] = recording_name

        connection_data = {
            "parentIdentifier": "ROOT",
            "name": name,
            "protocol": "vnc",
            "parameters": parameters,
            "attributes": {"max-connections": "1", "max-connections-per-user": "1"}
        }
        resp = self._do_request(requests.post, "connections", json=connection_data)
        return resp.json()["identifier"]

    def update_connection(self, conn_id: str, hostname: str, port: int, password: str) -> None:
        """
        Update a VNC connection.

        Args:
            conn_id: Connection identifier
            hostname: VNC hostname
            port: VNC port
            password: VNC password
        """
        # Get connection details
        resp = self._do_request(requests.get, f"connections/{conn_id}")
        connection = resp.json()

        # Get existing parameters separately
        params_resp = self._do_request(requests.get, f"connections/{conn_id}/parameters")
        parameters = params_resp.json()

        # Update parameters
        parameters.update({
            "hostname": hostname,
            "port": str(port),
            "password": password
        })
        connection["parameters"] = parameters

        self._do_request(requests.put, f"connections/{conn_id}", json=connection)

    def sync_connection_config(self, conn_id: str, username: str = "") -> bool:
        """
        Synchronize connection configuration with current broker settings.
        Updates recording parameters and other configurable settings.

        Args:
            conn_id: Connection identifier
            username: Username (for recording filename)

        Returns:
            True if updated successfully, False otherwise
        """
        from broker.config.loader import BrokerConfig
        from datetime import datetime

        try:
            # Get current connection
            resp = self._do_request(
                requests.get, f"connections/{conn_id}", raise_for_status=False
            )
            if resp.status_code != 200:
                return False
            connection = resp.json()

            # Get existing parameters
            params_resp = self._do_request(
                requests.get, f"connections/{conn_id}/parameters"
            )
            parameters = params_resp.json()

            # Update connection name from config
            settings = BrokerConfig.settings()
            base_name = settings.containers.connection_name
            connection["name"] = f"{base_name} - {username}" if username else base_name

            # Update recording parameters from config
            recording = settings.guacamole.recording
            if recording.enabled:
                parameters["recording-path"] = recording.path
                parameters["recording-include-keys"] = "true" if recording.include_keys else "false"
                parameters["create-recording-path"] = "true" if recording.auto_create_path else "false"

                # Only set recording-name if not empty
                recording_name = recording.name
                if recording_name:
                    now = datetime.now()
                    recording_name = recording_name.replace("${GUAC_USERNAME}", username or "unknown")
                    recording_name = recording_name.replace("${GUAC_DATE}", now.strftime("%Y%m%d"))
                    recording_name = recording_name.replace("${GUAC_TIME}", now.strftime("%H%M%S"))
                    parameters["recording-name"] = recording_name
                else:
                    # Remove recording-name if empty (let Guacamole use default)
                    parameters.pop("recording-name", None)
            else:
                # Remove recording parameters if disabled
                for key in ["recording-path", "recording-name", "recording-include-keys", "create-recording-path"]:
                    parameters.pop(key, None)

            connection["parameters"] = parameters

            # Update connection
            self._do_request(
                requests.put, f"connections/{conn_id}", json=connection
            )
            logger.info(f"Synced config for connection {conn_id} (user: {username})")
            return True

        except CircuitOpenError:
            raise
        except Exception as e:
            logger.warning(f"Failed to sync config for connection {conn_id}: {e}")
            return False

    def delete_connection(self, conn_id: str) -> None:
        """
        Delete a connection.

        Args:
            conn_id: Connection identifier
        """
        self._do_request(
            requests.delete, f"connections/{conn_id}", raise_for_status=False
        )

    def grant_connection_permission(self, username: str, conn_id: str) -> None:
        """
        Grant connection permission to a user.

        Args:
            username: Username
            conn_id: Connection identifier
        """
        permissions = [{"op": "add", "path": f"/connectionPermissions/{conn_id}", "value": "READ"}]
        self._do_request(
            requests.patch, f"users/{username}/permissions", json=permissions
        )

    def create_home_connection(self, username: str) -> str | None:
        """
        Create a placeholder 'Home' connection to force Guacamole to show home page.
        The connection points to localhost:1 (unavailable) with skip-if-unavailable.

        Args:
            username: Username

        Returns:
            Connection identifier or None if already exists
        """
        from broker.config.loader import BrokerConfig

        home_name = BrokerConfig.settings().guacamole.home_connection_name
        conn_name = f"{home_name} - {username}"

        # Check if already exists
        try:
            conns = self.get_connections()
            for conn_id, conn in conns.items():
                if conn.get("name") == conn_name:
                    return None  # Already exists
        except CircuitOpenError:
            raise
        except Exception:
            pass

        connection_data = {
            "parentIdentifier": "ROOT",
            "name": conn_name,
            "protocol": "vnc",
            "parameters": {
                "hostname": "localhost",
                "port": "1",
                "read-only": "true"
            },
            "attributes": {
                "max-connections": "0",
                "max-connections-per-user": "0",
                "failover-only": "true"
            }
        }
        try:
            resp = self._do_request(
                requests.post, "connections",
                json=connection_data, raise_for_status=False,
            )
            if resp.status_code in (200, 201):
                conn_id = resp.json().get("identifier")
                self.grant_connection_permission(username, conn_id)
                return conn_id
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.warning(f"Could not create home connection for {username}: {e}")
        return None

    def get_connections(self) -> dict:
        """
        Get all connections.

        Returns:
            Dictionary of connections {id: connection_data}
        """
        resp = self._do_request(requests.get, "connections", raise_for_status=False)
        if resp.status_code == 200:
            return resp.json()
        return {}

    def get_active_connections(self) -> dict:
        """
        Get active connections.

        Returns:
            Dictionary of active connections
        """
        resp = self._do_request(requests.get, "activeConnections")
        return resp.json()
