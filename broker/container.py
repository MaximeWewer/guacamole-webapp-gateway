"""
Lightweight DI container for broker services.

Stored in ``app.extensions['services']`` during Flask context,
with a global fallback for background threads that run outside
Flask request context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from broker.domain.guacamole import GuacamoleAPI
    from broker.services.connection_monitor import ConnectionMonitor
    from broker.services.user_sync import UserSyncService


class ServiceContainer:
    """Lightweight service container holding shared service instances."""

    def __init__(self) -> None:
        self._guac_api: GuacamoleAPI | None = None
        self._user_sync: UserSyncService | None = None
        self._monitor: ConnectionMonitor | None = None

    @property
    def guac_api(self) -> GuacamoleAPI:
        if self._guac_api is None:
            from broker.config.settings import get_env
            from broker.domain.guacamole import GuacamoleAPI

            url = get_env("guacamole_url", "http://guacamole:8080/guacamole")
            user = get_env("guacamole_admin_user", "guacadmin")
            password = get_env("guacamole_admin_password", required=True)
            self._guac_api = GuacamoleAPI(
                url or "http://guacamole:8080/guacamole",
                user or "guacadmin",
                password or "",
            )
        return self._guac_api

    @property
    def user_sync(self) -> UserSyncService:
        if self._user_sync is None:
            from broker.config.loader import BrokerConfig
            from broker.services.user_sync import UserSyncService

            self._user_sync = UserSyncService(
                interval=BrokerConfig.settings().sync.interval,
            )
        return self._user_sync

    @property
    def monitor(self) -> ConnectionMonitor:
        if self._monitor is None:
            from broker.services.connection_monitor import ConnectionMonitor

            self._monitor = ConnectionMonitor(interval=5)
        return self._monitor


# Fallback for background threads (set once at startup in app.py)
_global_container: ServiceContainer | None = None


def get_services() -> ServiceContainer:
    """Return the service container.

    Tries ``current_app.extensions['services']`` first, then falls back
    to the module-level ``_global_container`` (same instance, set at
    startup for use by background threads that lack Flask context).
    """
    try:
        from flask import current_app

        return current_app.extensions["services"]
    except (RuntimeError, KeyError):
        pass
    if _global_container is not None:
        return _global_container
    raise RuntimeError("ServiceContainer not initialized")
