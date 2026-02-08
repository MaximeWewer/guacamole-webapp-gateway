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

    rl = BrokerConfig.settings().security.rate_limiting

    if not rl.enabled:
        app.config["RATELIMIT_ENABLED"] = False

    default_limit = rl.default_limit
    admin_limit = rl.admin_limit
    limiter._default_limits = [default_limit]  # type: ignore[attr-defined]

    limiter.init_app(app)

    @app.errorhandler(429)
    def rate_limit_handler(e: Exception) -> tuple:
        return api_error("Rate limit exceeded. Try again later.", 429)
