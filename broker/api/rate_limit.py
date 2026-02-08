"""
Rate limiting for the broker API.

Uses Flask-Limiter with in-memory storage (suitable for single-worker gunicorn).
"""

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from broker.api.responses import api_error
from broker.config.loader import BrokerConfig

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
)

# Admin (write) limit — read from config at init time, used by route decorators
admin_limit = "10/minute"


def init_limiter(app: Flask) -> None:
    """Attach the limiter to the Flask app and configure from broker config."""
    global admin_limit

    rl_config = BrokerConfig.get("security", "rate_limiting", default={})
    enabled = rl_config.get("enabled", True)

    if not enabled:
        app.config["RATELIMIT_ENABLED"] = False

    default_limit = rl_config.get("default_limit", "200/minute")
    admin_limit = rl_config.get("admin_limit", "10/minute")
    limiter._default_limits = [default_limit]

    limiter.init_app(app)

    @app.errorhandler(429)
    def rate_limit_handler(e):
        return api_error("Rate limit exceeded. Try again later.", 429)
