"""
Secrets Provider for Vault and environment variables.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import requests

logger = logging.getLogger("session-broker")


class SecretsProvider:
    """
    Manages secrets with Vault (OpenBao/HashiCorp) support.

    Priority: Vault > Environment Variables

    Supports two authentication methods:
    - Token authentication (simpler)
    - AppRole authentication (recommended for production)
    """

    def __init__(self) -> None:
        self.vault_addr = os.environ.get("VAULT_ADDR")
        self.vault_token = os.environ.get("VAULT_TOKEN")
        self.vault_role_id = os.environ.get("VAULT_ROLE_ID")
        self.vault_secret_id = os.environ.get("VAULT_SECRET_ID")
        self.vault_mount = os.environ.get("VAULT_MOUNT", "secret")
        self.vault_path = os.environ.get("VAULT_PATH", "guacamole/broker")
        self.use_vault = False
        self._vault_token_expires: float = 0
        self._secrets_cache: dict[str, str] = {}
        self._cache_ttl = 300
        self._cache_time: float = 0
        self._lock = threading.Lock()

        if self.vault_addr:
            self._init_vault()

    def _init_vault(self) -> None:
        """Initialize Vault connection."""
        try:
            if self.vault_role_id and self.vault_secret_id:
                resp = requests.post(
                    f"{self.vault_addr}/v1/auth/approle/login",
                    json={"role_id": self.vault_role_id, "secret_id": self.vault_secret_id},
                    timeout=5
                )
                resp.raise_for_status()
                data = resp.json()
                self.vault_token = data["auth"]["client_token"]
                # Refresh 60 seconds before expiry
                self._vault_token_expires = time.time() + data["auth"]["lease_duration"] - 60
                logger.info("Vault: AppRole authentication successful")

            if self.vault_token:
                resp = requests.get(
                    f"{self.vault_addr}/v1/auth/token/lookup-self",
                    headers={"X-Vault-Token": self.vault_token},
                    timeout=5
                )
                resp.raise_for_status()
                self.use_vault = True
                logger.info(f"Vault connected: {self.vault_addr}")
        except requests.RequestException as e:
            logger.warning(f"Vault unavailable ({e}), using environment variables")
            self.use_vault = False

    def _refresh_vault_token(self) -> None:
        """Refresh Vault token if expired."""
        if self.vault_role_id and self.vault_secret_id and time.time() > self._vault_token_expires:
            self._init_vault()

    def _get_from_vault(self, key: str) -> str | None:
        """
        Retrieve a secret from Vault.

        Args:
            key: Secret key name

        Returns:
            Secret value or None if not found
        """
        if not self.use_vault:
            return None

        with self._lock:
            self._refresh_vault_token()

            # Check cache
            if time.time() - self._cache_time < self._cache_ttl and key in self._secrets_cache:
                return self._secrets_cache.get(key)

            try:
                resp = requests.get(
                    f"{self.vault_addr}/v1/{self.vault_mount}/data/{self.vault_path}",
                    headers={"X-Vault-Token": self.vault_token},
                    timeout=5
                )
                resp.raise_for_status()
                secrets_data = resp.json().get("data", {}).get("data", {})

                # Update cache
                self._secrets_cache = secrets_data
                self._cache_time = time.time()

                return secrets_data.get(key)
            except requests.RequestException as e:
                logger.error(f"Error reading from Vault for key '{key}': {e}")
                return None

    def get(self, key: str, default: str | None = None) -> str | None:
        """
        Retrieve a secret: Vault > env > default.

        Args:
            key: Secret key name
            default: Default value if not found

        Returns:
            Secret value
        """
        if self.use_vault:
            value = self._get_from_vault(key)
            if value:
                return value

        # Convert key to environment variable format
        env_key = key.upper().replace("-", "_")
        return os.environ.get(env_key, default)

    def get_status(self) -> dict:
        """
        Get secrets provider status.

        Returns:
            Status dictionary
        """
        return {
            "vault_configured": bool(self.vault_addr),
            "vault_connected": self.use_vault,
            "vault_addr": self.vault_addr if self.use_vault else None,
            "auth_method": "approle" if self.vault_role_id else "token" if self.vault_token else None
        }


# Global instance
secrets_provider = SecretsProvider()
