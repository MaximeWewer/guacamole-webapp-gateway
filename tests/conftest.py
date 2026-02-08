"""
Shared pytest fixtures for the broker test suite.
"""

import os
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Environment stubs – must be set BEFORE any broker module is imported so
# that module-level calls to get_env / SecretsProvider don't fail.
# ---------------------------------------------------------------------------

os.environ.setdefault("GUACAMOLE_ADMIN_PASSWORD", "test-password")
os.environ.setdefault("DATABASE_PASSWORD", "test-db-password")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test_guacamole")
os.environ.setdefault("DATABASE_USER", "test_user")
os.environ.setdefault("BROKER_API_KEY", "test-api-key-secret")
os.environ.setdefault("USER_DATA_PATH", "/tmp/broker-tests/users")
os.environ.setdefault("CONFIG_PATH", "/tmp/broker-tests/config")

# Import broker modules AFTER env vars are set (they trigger module-level code)
from broker.config.models import BrokerSettings  # noqa: E402
from broker.domain.types import SessionData  # noqa: E402


# ---------------------------------------------------------------------------
# Database mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db(mocker):
    """Patch get_db_connection → mock context manager with cursor."""
    mock_cursor = MagicMock()
    mock_cursor.execute = MagicMock()
    mock_cursor.fetchone = MagicMock(return_value=None)
    mock_cursor.fetchall = MagicMock(return_value=[])
    mock_cursor.rowcount = 0
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.commit = MagicMock()
    mock_conn.rollback = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    @contextmanager
    def _fake_conn():
        yield mock_conn

    # Patch at every import site
    _targets = [
        "broker.persistence.database.get_db_connection",
        "broker.domain.session.get_db_connection",
        "broker.domain.group_config.get_db_connection",
        "broker.api.routes.get_db_connection",
    ]
    for target in _targets:
        try:
            mocker.patch(target, _fake_conn)
        except AttributeError:
            pass

    return mock_cursor


# ---------------------------------------------------------------------------
# Guacamole API mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_guac_api(mocker):
    """Return a mock GuacamoleAPI instance and inject it into the DI container."""
    mock_api = MagicMock()
    mock_api.authenticate.return_value = "fake-token"
    mock_api.ensure_auth.return_value = None
    mock_api._get_auth_params.return_value = ("fake-token", "postgresql")
    mock_api.get_users.return_value = ["alice", "bob"]
    mock_api.get_user_groups.return_value = ["developers"]
    mock_api.get_all_user_groups.return_value = {"developers": {}, "admins": {}}
    mock_api.create_connection.return_value = "42"
    mock_api.update_connection.return_value = None
    mock_api.sync_connection_config.return_value = True
    mock_api.delete_connection.return_value = None
    mock_api.grant_connection_permission.return_value = None
    mock_api.create_home_connection.return_value = "99"
    mock_api.get_connections.return_value = {}
    mock_api.get_active_connections.return_value = {}
    mock_api.circuit_healthy = True

    return mock_api


# ---------------------------------------------------------------------------
# Service container mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_services(mocker, mock_guac_api):
    """Create and inject a ServiceContainer with pre-mocked services."""
    from broker.container import ServiceContainer

    container = ServiceContainer()
    container._guac_api = mock_guac_api

    # Mock user_sync and monitor as MagicMock instances
    mock_user_sync = MagicMock()
    mock_user_sync.start = MagicMock()
    mock_user_sync.init_pool = MagicMock()
    mock_user_sync.sync_users = MagicMock(return_value=["newuser"])
    mock_user_sync.get_stats = MagicMock(return_value={
        "last_sync": None, "total_synced": 0, "errors": 0,
    })
    mock_user_sync.running = True
    mock_user_sync.stop = MagicMock()
    container._user_sync = mock_user_sync

    mock_monitor = MagicMock()
    mock_monitor.start = MagicMock()
    mock_monitor.active_connections = set()
    mock_monitor.running = True
    mock_monitor.stop = MagicMock()
    container._monitor = mock_monitor

    # Inject as global fallback
    mocker.patch("broker.container._global_container", container)

    return container


# ---------------------------------------------------------------------------
# Orchestrator mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_orchestrator(mocker):
    """Patch get_orchestrator → mock with standard container methods."""
    from broker.domain.orchestrator.base import ContainerInfo

    mock_orch = MagicMock()
    mock_orch.spawn_container.return_value = ContainerInfo(
        container_id="cnt-abc123",
        container_ip="172.18.0.5",
        backend="docker",
    )
    mock_orch.destroy_container.return_value = None
    mock_orch.is_container_running.return_value = True
    mock_orch.claim_container.return_value = True
    mock_orch.get_pool_containers.return_value = []
    mock_orch.get_running_count.return_value = 1
    mock_orch.list_managed_containers.return_value = []

    mocker.patch("broker.domain.orchestrator.factory.get_orchestrator", return_value=mock_orch)
    mocker.patch("broker.domain.orchestrator.get_orchestrator", return_value=mock_orch)
    mocker.patch("broker.domain.container.get_orchestrator", return_value=mock_orch)

    return mock_orch


# ---------------------------------------------------------------------------
# BrokerConfig mock
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "lifecycle": {"persist_after_disconnect": True, "idle_timeout_minutes": 3},
    "guacamole": {
        "force_home_page": False,
        "home_connection_name": "Home",
        "recording": {"enabled": False},
    },
    "containers": {
        "image": "ghcr.io/maximewewer/docker-browser-vnc:latest",
        "connection_name": "Virtual Desktop",
        "network": "guac-net",
        "memory_limit": "1g",
        "shm_size": "128m",
    },
    "pool": {"enabled": True, "init_containers": 2, "max_containers": 10},
    "sync": {"interval": 60, "ignored_users": ["guacadmin"]},
    "security": {"rate_limiting": {"enabled": True, "default_limit": "200/minute", "admin_limit": "10/minute"}},
}


@pytest.fixture
def mock_broker_config(mocker):
    """Patch BrokerConfig.get and BrokerConfig.settings to return sensible defaults."""

    def _get(*keys, default=None):
        node = _DEFAULT_CONFIG
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    _typed_settings = BrokerSettings(**_DEFAULT_CONFIG)

    mocker.patch("broker.config.loader.BrokerConfig.get", side_effect=_get)
    mocker.patch("broker.config.loader.BrokerConfig.load", return_value=_DEFAULT_CONFIG)
    mocker.patch("broker.config.loader.BrokerConfig.settings", return_value=_typed_settings)
    mocker.patch("broker.config.loader.BrokerConfig.get_browser_type", return_value="firefox")
    return _get


# ---------------------------------------------------------------------------
# Sample session factory
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_session():
    """Factory for a realistic SessionData instance."""
    def _make(**overrides) -> SessionData:
        now = time.time()
        defaults = {
            "session_id": "abcd1234",
            "username": "alice",
            "container_id": "cnt-abc123",
            "container_ip": "172.18.0.5",
            "guac_connection_id": "42",
            "vnc_password": "s3cure-p4ss",
            "created_at": now - 600,
            "started_at": now - 300,
            "last_activity": now - 10,
        }
        defaults.update(overrides)
        return SessionData(**defaults)
    return _make


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(mocker, mock_db, mock_orchestrator, mock_guac_api, mock_broker_config, mock_services):
    """Create a Flask test_client with all external deps mocked."""
    mocker.patch("broker.persistence.database.init_database")

    # Patch routes-level imports that access DB / orchestrator
    mocker.patch("broker.api.routes.destroy_container")
    mocker.patch("broker.api.routes.provision_user_connection", return_value="42")

    # group_config mock
    mock_gc = MagicMock()
    mock_gc.get_all_groups.return_value = {"default": {"bookmarks": []}}
    mock_gc.get_group_config.return_value = {"bookmarks": [], "description": "test"}
    mock_gc.create_or_update_group.return_value = True
    mock_gc.delete_group.return_value = True
    mock_gc.get_setting.return_value = "true"
    mock_gc.set_setting.return_value = None
    mock_gc.get_user_config.return_value = {"bookmarks": [], "groups": ["default"]}
    mocker.patch("broker.api.routes.group_config", mock_gc)

    # SessionStore mocks for routes
    mocker.patch("broker.api.routes.SessionStore.list_sessions", return_value=[])
    mocker.patch("broker.api.routes.SessionStore.get_session", return_value=None)

    from broker.app import app
    app.config["TESTING"] = True
    # Ensure container is in app.extensions
    app.extensions["services"] = mock_services
    # Disable rate limiting for most tests
    app.config["RATELIMIT_ENABLED"] = False

    client = app.test_client()
    # Wrap client to add default API key header
    _original_open = client.open

    def _open_with_key(*args, **kwargs):
        headers = kwargs.pop("headers", {})
        if isinstance(headers, dict) and "X-API-Key" not in headers and "Authorization" not in headers:
            headers["X-API-Key"] = "test-api-key-secret"
        kwargs["headers"] = headers
        return _original_open(*args, **kwargs)

    client.open = _open_with_key
    return client
