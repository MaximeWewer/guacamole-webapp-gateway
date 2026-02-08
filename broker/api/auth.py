"""
API Key authentication for the broker API.

Provides a before_request hook that enforces API key validation
on all /api/* endpoints. Health check remains public.

Fail-closed: if no API key is configured, all /api/* endpoints return 503.
"""

from __future__ import annotations

import hmac
import logging

from flask import Response, request

from broker.api.responses import api_error
from broker.config.settings import get_env

logger = logging.getLogger("session-broker")

# Endpoints that do not require authentication (use Flask endpoint names)
PUBLIC_ENDPOINTS = frozenset({"api.health"})


def _get_api_key() -> str | None:
    """
    Retrieve the configured API key from Vault or environment.

    Returns:
        The API key string, or None if not configured.
    """
    key = get_env("broker_api_key")
    return key if key else None


def _extract_request_key() -> str | None:
    """
    Extract the API key from the incoming request.

    Supported methods:
        - Header: X-API-Key: <key>
        - Header: Authorization: Bearer <key>

    Returns:
        The key string, or None if not provided.
    """
    # Check X-API-Key header first
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key

    # Check Authorization: Bearer <key>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    return None


def require_api_key() -> tuple[Response, int] | None:
    """
    Flask before_request hook that enforces API key authentication.

    - Skips public endpoints (health check).
    - Returns 503 if no API key is configured (fail-closed).
    - Returns 401 if the request key is missing or invalid.
    - Returns None (allows request) if the key is valid.
    """
    # Skip authentication for public endpoints
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    # Fail-closed: no configured key → service unavailable
    configured_key = _get_api_key()
    if configured_key is None:
        logger.warning("API key not configured — rejecting request (fail-closed)")
        return api_error("API key not configured. Service unavailable.", 503)

    # Extract key from request
    request_key = _extract_request_key()
    if request_key is None:
        return api_error("API key required. Use X-API-Key header or Authorization: Bearer <key>.", 401)

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(request_key, configured_key):
        logger.warning(f"Invalid API key from {request.remote_addr} on {request.path}")
        return api_error("Invalid API key.", 401)

    return None
