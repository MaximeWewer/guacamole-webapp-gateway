"""
Guacamole API client for REST operations.
"""

import logging
import threading
import time

import requests

from broker.config.settings import get_env

logger = logging.getLogger("session-broker")

# Guacamole configuration
GUACAMOLE_URL = get_env("guacamole_url", "http://guacamole:8080/guacamole")
GUAC_ADMIN_USER = get_env("guacamole_admin_user", "guacadmin")
GUAC_ADMIN_PASSWORD = get_env("guacamole_admin_password", required=True)


class GuacamoleAPI:
    """Client for Guacamole REST API."""

    def __init__(self, base_url: str, username: str, password: str):
        """
        Initialize Guacamole API client.

        Args:
            base_url: Guacamole base URL
            username: Admin username
            password: Admin password
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.token_expires: float = 0
        self.data_source = "postgresql"
        self._lock = threading.Lock()

    def authenticate(self) -> str:
        """
        Authenticate with Guacamole.

        Returns:
            Authentication token
        """
        resp = requests.post(
            f"{self.base_url}/api/tokens",
            data={"username": self.username, "password": self.password},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["authToken"]
        # Token valid for ~1 hour, refresh at 58 minutes
        self.token_expires = time.time() + 3500
        self.data_source = list(data.get("availableDataSources", ["postgresql"]))[0]
        return self.token

    def ensure_auth(self) -> None:
        """Ensure valid authentication token exists."""
        with self._lock:
            if not self.token or time.time() > self.token_expires:
                self.authenticate()

    def get_users(self) -> list:
        """
        Get list of Guacamole users.

        Returns:
            List of usernames
        """
        self.ensure_auth()
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/users",
            params={"token": self.token},
            timeout=10
        )
        resp.raise_for_status()
        return list(resp.json().keys())

    def get_user_groups(self, username: str) -> list:
        """
        Get groups for a user.

        Args:
            username: Username

        Returns:
            List of group names
        """
        self.ensure_auth()
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/users/{username}/userGroups",
            params={"token": self.token},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_all_user_groups(self) -> dict:
        """
        Get all user groups in Guacamole.

        Returns:
            Dictionary of group data
        """
        self.ensure_auth()
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/userGroups",
            params={"token": self.token},
            timeout=10
        )
        resp.raise_for_status()
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

        self.ensure_auth()

        parameters = {
            "hostname": hostname,
            "port": str(port),
            "password": password,
            "color-depth": "24",
            "clipboard-encoding": "UTF-8",
            "resize-method": "display-update"
        }

        # Add recording parameters if enabled
        recording_config = BrokerConfig.get("guacamole", "recording", default={})
        if recording_config.get("enabled", False):
            parameters["recording-path"] = recording_config.get("path", "/recordings")
            parameters["recording-include-keys"] = "true" if recording_config.get("include_keys", False) else "false"
            parameters["create-recording-path"] = "true" if recording_config.get("auto_create_path", True) else "false"

            # Only set recording-name if not empty
            recording_name = recording_config.get("name", "")
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
        resp = requests.post(
            f"{self.base_url}/api/session/data/{self.data_source}/connections",
            params={"token": self.token},
            json=connection_data,
            timeout=10
        )
        resp.raise_for_status()
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
        self.ensure_auth()
        # Get connection details
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}",
            params={"token": self.token},
            timeout=10
        )
        resp.raise_for_status()
        connection = resp.json()

        # Get existing parameters separately
        params_resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}/parameters",
            params={"token": self.token},
            timeout=10
        )
        params_resp.raise_for_status()
        parameters = params_resp.json()

        # Update parameters
        parameters.update({
            "hostname": hostname,
            "port": str(port),
            "password": password
        })
        connection["parameters"] = parameters

        requests.put(
            f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}",
            params={"token": self.token},
            json=connection,
            timeout=10
        )

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

        self.ensure_auth()

        try:
            # Get current connection
            resp = requests.get(
                f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}",
                params={"token": self.token},
                timeout=10
            )
            if resp.status_code != 200:
                return False
            connection = resp.json()

            # Get existing parameters
            params_resp = requests.get(
                f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}/parameters",
                params={"token": self.token},
                timeout=10
            )
            params_resp.raise_for_status()
            parameters = params_resp.json()

            # Update connection name from config
            connection_name = BrokerConfig.get("containers", "connection_name", default="Virtual Desktop")
            connection["name"] = connection_name

            # Update recording parameters from config
            recording_config = BrokerConfig.get("guacamole", "recording", default={})
            if recording_config.get("enabled", False):
                parameters["recording-path"] = recording_config.get("path", "/recordings")
                parameters["recording-include-keys"] = "true" if recording_config.get("include_keys", False) else "false"
                parameters["create-recording-path"] = "true" if recording_config.get("auto_create_path", True) else "false"

                # Only set recording-name if not empty
                recording_name = recording_config.get("name", "")
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
            resp = requests.put(
                f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}",
                params={"token": self.token},
                json=connection,
                timeout=10
            )
            resp.raise_for_status()
            logger.info(f"Synced config for connection {conn_id} (user: {username})")
            return True

        except Exception as e:
            logger.warning(f"Failed to sync config for connection {conn_id}: {e}")
            return False

    def delete_connection(self, conn_id: str) -> None:
        """
        Delete a connection.

        Args:
            conn_id: Connection identifier
        """
        self.ensure_auth()
        requests.delete(
            f"{self.base_url}/api/session/data/{self.data_source}/connections/{conn_id}",
            params={"token": self.token},
            timeout=10
        )

    def grant_connection_permission(self, username: str, conn_id: str) -> None:
        """
        Grant connection permission to a user.

        Args:
            username: Username
            conn_id: Connection identifier
        """
        self.ensure_auth()
        permissions = [{"op": "add", "path": f"/connectionPermissions/{conn_id}", "value": "READ"}]
        requests.patch(
            f"{self.base_url}/api/session/data/{self.data_source}/users/{username}/permissions",
            params={"token": self.token},
            json=permissions,
            timeout=10
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

        self.ensure_auth()
        home_name = BrokerConfig.get("guacamole", "home_connection_name", default="Home")
        conn_name = f"{home_name} - {username}"

        # Check if already exists
        try:
            conns = self.get_connections()
            for conn_id, conn in conns.items():
                if conn.get("name") == conn_name:
                    return None  # Already exists
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
            resp = requests.post(
                f"{self.base_url}/api/session/data/{self.data_source}/connections",
                params={"token": self.token},
                json=connection_data,
                timeout=10
            )
            if resp.status_code in (200, 201):
                conn_id = resp.json().get("identifier")
                self.grant_connection_permission(username, conn_id)
                return conn_id
        except Exception as e:
            logger.warning(f"Could not create home connection for {username}: {e}")
        return None

    def get_connections(self) -> dict:
        """
        Get all connections.

        Returns:
            Dictionary of connections {id: connection_data}
        """
        self.ensure_auth()
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/connections",
            params={"token": self.token},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        return {}

    def get_active_connections(self) -> dict:
        """
        Get active connections.

        Returns:
            Dictionary of active connections
        """
        self.ensure_auth()
        resp = requests.get(
            f"{self.base_url}/api/session/data/{self.data_source}/activeConnections",
            params={"token": self.token},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()


# Global instance
guac_api = GuacamoleAPI(GUACAMOLE_URL, GUAC_ADMIN_USER, GUAC_ADMIN_PASSWORD)
