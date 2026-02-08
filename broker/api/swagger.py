"""
OpenAPI / Swagger documentation for the Session Broker API.

Uses Flasgger to serve Swagger UI at /apidocs and the JSON spec at /apispec_1.json.
"""

from __future__ import annotations

from flask import Flask
from flasgger import Swagger


SWAGGER_TEMPLATE: dict = {
    "info": {
        "title": "Session Broker API",
        "version": "1.0.0",
        "description": (
            "REST API for managing Guacamole VNC session lifecycle, "
            "user synchronization, group configuration, and broker settings."
        ),
    },
    "securityDefinitions": {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key passed in the X-API-Key header.",
        },
        "BearerAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Bearer token passed as 'Authorization: Bearer <key>'.",
        },
    },
    "definitions": {
        "SuccessResponse": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean", "example": True},
                "data": {"type": "object"},
                "message": {"type": "string"},
            },
        },
        "ErrorResponse": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean", "example": False},
                "error": {"type": "string"},
            },
        },
        "HealthResponse": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
                "database": {"type": "boolean"},
                "database_pool": {"type": "object"},
                "guacamole": {"type": "boolean"},
                "services": {
                    "type": "object",
                    "properties": {
                        "monitor": {"type": "boolean"},
                        "user_sync": {"type": "boolean"},
                    },
                },
                "vault": {"type": "boolean"},
            },
        },
        "SessionItem": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "username": {"type": "string"},
                "container_id": {"type": "string"},
                "container_ip": {"type": "string"},
                "guac_connection_id": {"type": "string"},
                "created_at": {"type": "number"},
                "started_at": {"type": "number"},
                "last_activity": {"type": "number"},
                "active": {"type": "boolean"},
            },
        },
        "BookmarkInput": {
            "type": "object",
            "required": ["name", "url"],
            "properties": {
                "name": {"type": "string", "example": "Google"},
                "url": {"type": "string", "example": "https://google.com"},
            },
        },
        "SettingsPayload": {
            "type": "object",
            "properties": {
                "merge_bookmarks": {"type": "boolean"},
                "inherit_from_default": {"type": "boolean"},
            },
        },
        "GroupPayload": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "priority": {"type": "integer"},
                "bookmarks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}

SWAGGER_CONFIG: dict = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec_1",
            "route": "/apispec_1.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}


def init_swagger(app: Flask) -> Swagger:
    """Initialize Flasgger and exempt Swagger UI from the rate limiter."""
    swagger = Swagger(app, template=SWAGGER_TEMPLATE, config=SWAGGER_CONFIG)

    # Exempt Swagger UI and spec endpoints from rate limiting
    from broker.api.rate_limit import limiter
    from broker.api import auth

    for name in ("flasgger.apidocs", "flasgger.apispec_1"):
        view = app.view_functions.get(name)
        if view is not None:
            limiter.exempt(view)

    # Make Swagger UI endpoints public (no API key needed)
    auth.PUBLIC_ENDPOINTS.update({
        "flasgger.apidocs",
        "flasgger.apispec_1",
        "flasgger.static",
    })

    return swagger
