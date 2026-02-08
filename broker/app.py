"""
Session Broker for Guacamole VNC Container Management.

This service manages the lifecycle of VNC containers for Guacamole users:
- Automatic synchronization of Guacamole users
- Group-based configuration (bookmarks, wallpaper) stored in PostgreSQL
- Pre-provisions a "Virtual Desktop" connection for each user
- Spawns VNC container on connection start
- Destroys container on connection end
- Persists Firefox bookmarks and wallpaper between sessions
- Secret management via Vault (OpenBao/HashiCorp) or environment variables
- Session and group storage in PostgreSQL
- Network isolation via Docker networks
"""

import logging
import os
import re

from flask import Flask

# =============================================================================
# Logging Setup
# =============================================================================

from broker.observability import setup_json_logging

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
setup_json_logging(level=_log_level)
logger = logging.getLogger("session-broker")


# Filter sensitive data from logs
class SensitiveDataFilter(logging.Filter):
    """Filter to mask sensitive data in log messages."""

    SENSITIVE_PATTERNS = [
        (re.compile(r'password["\']?\s*[:=]\s*["\']?[^"\'}\s]+', re.I), 'password=***'),
        (re.compile(r'token["\']?\s*[:=]\s*["\']?[^"\'}\s]+', re.I), 'token=***'),
        (re.compile(r'secret["\']?\s*[:=]\s*["\']?[^"\'}\s]+', re.I), 'secret=***'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in self.SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


logger.addFilter(SensitiveDataFilter())

# =============================================================================
# Flask Application
# =============================================================================

app = Flask(__name__)

# Initialize rate limiter
from broker.api.rate_limit import init_limiter
init_limiter(app)

# Initialize Prometheus metrics (auto-instruments all routes, exposes /metrics)
from broker.observability import init_metrics
init_metrics(app)

# =============================================================================
# Import and Initialize Modules
# =============================================================================

# Initialize database (must be done before other imports that use DB)
from broker.persistence.database import init_database

try:
    init_database()
except Exception as e:
    logger.error(f"Database initialization error: {e}")
    raise

# Import API routes and register blueprint
from broker.api.routes import api
from broker.api.validators import ValidationError
from broker.api.responses import api_error

app.register_blueprint(api)

# Initialize DI container (must be after database init)
from broker.container import ServiceContainer
import broker.container as container_mod
from broker.domain.orchestrator import get_orchestrator
from broker.config.loader import BrokerConfig
from broker.domain.session import SessionStore

container = ServiceContainer()
app.extensions["services"] = container
container_mod._global_container = container

# =============================================================================
# Startup Functions
# =============================================================================

def cleanup_orphaned_containers() -> None:
    """Clean up orphaned VNC containers/pods from previous runs."""
    try:
        orchestrator = get_orchestrator()
        for container in orchestrator.list_managed_containers():
            logger.info(f"Cleaning up orphaned container: {container['name']}")
            try:
                orchestrator.destroy_container(container["id"])
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")


def sync_existing_connections() -> None:
    """
    Synchronize existing Guacamole connections with current broker config.
    Updates recording settings, connection names, etc.
    """
    if not BrokerConfig.settings().sync.sync_config_on_restart:
        return

    logger.info("Syncing existing connections with current config...")
    sessions = SessionStore.list_sessions()
    synced = 0

    guac_api = container.guac_api
    for session in sessions:
        if session is None:
            continue
        conn_id = session.guac_connection_id
        username = session.username or ""
        if conn_id:
            if guac_api.sync_connection_config(conn_id, username):
                synced += 1

    if synced > 0:
        logger.info(f"Synced {synced} existing connections with current config")


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(ValidationError)
def handle_validation_error(e: ValidationError) -> tuple:
    """Handle validation errors."""
    return api_error(str(e), 400)


@app.errorhandler(404)
def handle_not_found(e: Exception) -> tuple:
    """Handle 404 errors."""
    return api_error("Resource not found", 404)


@app.errorhandler(500)
def handle_server_error(e: Exception) -> tuple:
    """Handle 500 errors."""
    from broker.observability import ERRORS_TOTAL
    ERRORS_TOTAL.labels(endpoint="app_500").inc()
    logger.error(f"Internal server error: {e}")
    return api_error("Internal server error", 500)


# =============================================================================
# Startup
# =============================================================================

# Start background services (works with both gunicorn and direct execution)
cleanup_orphaned_containers()
sync_existing_connections()
container.user_sync.start()

# Initialize container pool at startup
container.user_sync.init_pool()
container.monitor.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
