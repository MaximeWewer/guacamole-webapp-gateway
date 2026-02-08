"""
Flask API routes for the Session Broker.
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, request

from broker.config.settings import get_env
from broker.config.secrets import secrets_provider
from broker.config.loader import BrokerConfig
from broker.persistence.database import get_db_connection
from broker.api.validators import (
    ValidationError,
    validate_username,
    validate_group_name,
    validate_url,
)
from broker.api.responses import api_success, api_error
from broker.api.rate_limit import limiter, admin_limit
from broker.api.audit import audit_log_response
from broker.container import get_services
from broker.domain.session import SessionStore
from broker.domain.user_profile import UserProfile
from broker.domain.container import destroy_container
from broker.domain.group_config import group_config
from broker.services.provisioning import provision_user_connection

logger = logging.getLogger("session-broker")

# Type alias for Flask route returns
RouteResponse = tuple[Response, int]

# Create Blueprint
api = Blueprint("api", __name__)

from broker.api.auth import require_api_key
api.before_request(require_api_key)
api.after_request(audit_log_response)

# Configuration values for API
GUACD_HOSTNAME = get_env("guacd_hostname", "guacd")
DATABASE_HOST = get_env("database_host", "postgres")
DATABASE_NAME = get_env("database_name", "guacamole")


# =============================================================================
# Health and Status
# =============================================================================

@api.route("/health")
@limiter.exempt
def health() -> RouteResponse:
    """Health check endpoint."""
    db_ok = False
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                db_ok = True
    except Exception:
        pass

    from flask import jsonify
    status = "healthy" if db_ok else "degraded"
    return jsonify({
        "status": status,
        "database": db_ok,
        "vault": secrets_provider.use_vault
    }), 200 if db_ok else 503


@api.route("/api/secrets/status")
def secrets_status() -> RouteResponse:
    """Get secrets provider status."""
    return api_success(secrets_provider.get_status())


@api.route("/api/config")
def get_config() -> RouteResponse:
    """Get broker configuration (non-sensitive)."""
    settings = BrokerConfig.settings()
    return api_success({
        "vnc_image": settings.containers.image,
        "vnc_network": settings.containers.network,
        "guacd_hostname": GUACD_HOSTNAME,
        "connection_name": settings.containers.connection_name,
        "user_sync_interval": settings.sync.interval,
        "ignored_users": settings.sync.ignored_users,
        "database_host": DATABASE_HOST,
        "database_name": DATABASE_NAME,
        "secrets_provider": secrets_provider.get_status()
    })


# =============================================================================
# Sessions
# =============================================================================

@api.route("/api/sessions")
def list_sessions() -> RouteResponse:
    """List all sessions."""
    sessions = []
    for s in SessionStore.list_sessions():
        if s is None:
            continue
        d = s.to_dict()
        d.pop("vnc_password", None)
        d["active"] = bool(s.container_id)
        sessions.append(d)
    return api_success({"sessions": sessions})


@api.route("/api/sessions/<session_id>", methods=["DELETE"])
@limiter.limit(lambda: admin_limit)
def force_cleanup(session_id: str) -> RouteResponse:
    """Force cleanup a session."""
    session = SessionStore.get_session(session_id)
    if not session:
        return api_error("Session not found", 404)

    if session.container_id:
        destroy_container(session.container_id)

    session.container_id = None
    session.container_ip = None
    SessionStore.save_session(session_id, session)
    return api_success(message="Session cleaned up")


# =============================================================================
# User Sync
# =============================================================================

@api.route("/api/sync", methods=["GET"])
def get_sync_status() -> RouteResponse:
    """Get sync service status."""
    return api_success(get_services().user_sync.get_stats())


@api.route("/api/sync", methods=["POST"])
@limiter.limit(lambda: admin_limit)
def trigger_sync() -> RouteResponse:
    """Trigger manual user sync."""
    user_sync = get_services().user_sync
    new_users = user_sync.sync_users()
    return api_success({"new_users": new_users, "stats": user_sync.get_stats()})


# =============================================================================
# User Operations
# =============================================================================

@api.route("/api/users/<username>/provision", methods=["POST"])
@limiter.limit(lambda: admin_limit)
def provision_user(username: str) -> RouteResponse:
    """Provision a user connection."""
    try:
        username = validate_username(username)
        conn_id = provision_user_connection(username)
        return api_success({"connection_id": conn_id})
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Provisioning error for {username}: {e}")
        return api_error("Provisioning failed", 500)


@api.route("/api/users/<username>/refresh-config", methods=["POST"])
@limiter.limit(lambda: admin_limit)
def refresh_user_config(username: str) -> RouteResponse:
    """Refresh user configuration from groups."""
    try:
        username = validate_username(username)
        user_groups = get_services().guac_api.get_user_groups(username)
        config = UserProfile.apply_group_config(username, user_groups)
        return api_success(config, "Configuration refreshed")
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Config refresh error for {username}: {e}")
        return api_error("Configuration refresh failed", 500)


@api.route("/api/users/<username>/groups")
def get_user_groups_api(username: str) -> RouteResponse:
    """Get user's groups and effective configuration."""
    try:
        username = validate_username(username)
        user_groups = get_services().guac_api.get_user_groups(username)
        config = group_config.get_user_config(user_groups)
        return api_success({
            "username": username,
            "guacamole_groups": user_groups,
            "effective_config": config
        })
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Error getting groups for {username}: {e}")
        return api_error("Failed to get user groups", 500)


@api.route("/api/users/<username>/bookmarks", methods=["POST"])
@limiter.limit(lambda: admin_limit)
def add_user_bookmark(username: str) -> RouteResponse:
    """Add a bookmark for user."""
    try:
        username = validate_username(username)
        data = request.get_json() or {}

        name = data.get("name")
        url = data.get("url")

        if not name or not url:
            return api_error("name and url are required", 400)

        validate_url(url)
        UserProfile.add_bookmark(username, name, url)
        return api_success(message=f"Bookmark added: {name}")
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Error adding bookmark for {username}: {e}")
        return api_error("Failed to add bookmark", 500)


@api.route("/api/users/<username>/profile")
def get_user_profile(username: str) -> RouteResponse:
    """Get user profile information."""
    try:
        username = validate_username(username)
        user_path = UserProfile.get_user_path(username)

        if not user_path.exists():
            return api_error("Profile not found", 404)

        # Check if Firefox policies exist
        policies_file = user_path / "firefox-policies" / "policies.json"
        has_policies = policies_file.exists()

        return api_success({
            "username": username,
            "has_firefox_policies": has_policies
        })
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Error getting profile for {username}: {e}")
        return api_error("Failed to get profile", 500)


# =============================================================================
# Group Config API
# =============================================================================

@api.route("/api/groups")
def list_groups() -> RouteResponse:
    """List all groups."""
    return api_success({"groups": group_config.get_all_groups()})


@api.route("/api/groups/<group_name>")
def get_group(group_name: str) -> RouteResponse:
    """Get a specific group configuration."""
    try:
        group_name = validate_group_name(group_name)
        cfg = group_config.get_group_config(group_name)
        if not cfg:
            return api_error("Group not found", 404)
        return api_success({group_name: cfg})
    except ValidationError as e:
        return api_error(str(e), 400)


@api.route("/api/groups/<group_name>", methods=["PUT"])
@limiter.limit(lambda: admin_limit)
def update_group_api(group_name: str) -> RouteResponse:
    """Create or update a group."""
    try:
        group_name = validate_group_name(group_name)
        data = request.get_json()
        if not data:
            return api_error("Request body required", 400)

        # Validate bookmarks if provided
        if "bookmarks" in data:
            for bm in data["bookmarks"]:
                if "url" in bm:
                    validate_url(bm["url"])

        if group_config.create_or_update_group(group_name, data):
            return api_success({"config": data}, f"Group '{group_name}' updated")
        return api_error("Failed to save group", 500)
    except ValidationError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.error(f"Error updating group {group_name}: {e}")
        return api_error("Failed to update group", 500)


@api.route("/api/groups/<group_name>", methods=["DELETE"])
@limiter.limit(lambda: admin_limit)
def delete_group_api(group_name: str) -> RouteResponse:
    """Delete a group."""
    try:
        group_name = validate_group_name(group_name)
        if group_name == "default":
            return api_error("Cannot delete default group", 400)

        if group_config.delete_group(group_name):
            return api_success(message=f"Group '{group_name}' deleted")
        return api_error("Group not found", 404)
    except ValidationError as e:
        return api_error(str(e), 400)


# =============================================================================
# Settings
# =============================================================================

@api.route("/api/settings")
def get_settings() -> RouteResponse:
    """Get broker settings."""
    return api_success({
        "merge_bookmarks": group_config.get_setting("merge_bookmarks", "true") == "true",
        "inherit_from_default": group_config.get_setting("inherit_from_default", "true") == "true"
    })


@api.route("/api/settings", methods=["PUT"])
@limiter.limit(lambda: admin_limit)
def update_settings() -> RouteResponse:
    """Update broker settings."""
    data = request.get_json() or {}
    if "merge_bookmarks" in data:
        group_config.set_setting("merge_bookmarks", "true" if data["merge_bookmarks"] else "false")
    if "inherit_from_default" in data:
        group_config.set_setting("inherit_from_default", "true" if data["inherit_from_default"] else "false")
    return api_success(message="Settings updated")


# =============================================================================
# Guacamole Integration
# =============================================================================

@api.route("/api/guacamole/groups")
def list_guacamole_groups() -> RouteResponse:
    """List Guacamole user groups."""
    try:
        return api_success({"groups": get_services().guac_api.get_all_user_groups()})
    except Exception as e:
        logger.error(f"Error getting Guacamole groups: {e}")
        return api_error("Failed to get Guacamole groups", 500)


# =============================================================================
# Error Handlers
# =============================================================================

@api.errorhandler(ValidationError)
def handle_validation_error(e: ValidationError) -> RouteResponse:
    """Handle validation errors."""
    return api_error(str(e), 400)


@api.errorhandler(404)
def handle_not_found(e: Exception) -> RouteResponse:
    """Handle 404 errors."""
    return api_error("Resource not found", 404)


@api.errorhandler(500)
def handle_server_error(e: Exception) -> RouteResponse:
    """Handle 500 errors."""
    from broker.observability import ERRORS_TOTAL
    ERRORS_TOTAL.labels(endpoint=request.endpoint or "unknown").inc()
    logger.error(f"Internal server error: {e}")
    return api_error("Internal server error", 500)
