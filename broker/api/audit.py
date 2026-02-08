"""
Audit logging for admin API actions.

Logs all write operations (POST, PUT, DELETE) as structured JSON to stdout
via a dedicated 'audit' logger. GET requests are not audited.
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone

from flask import request, Response

# Dedicated audit logger
audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

# JSON formatter for structured output
_handler = logging.StreamHandler(sys.stdout)


class _JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.msg, ensure_ascii=False)


_handler.setFormatter(_JsonFormatter())
audit_logger.addHandler(_handler)

# Only audit write methods
AUDIT_METHODS = frozenset({"POST", "PUT", "DELETE"})

# Pattern to extract username from URL paths like /api/users/<username>/...
_USERNAME_RE = re.compile(r"/api/users/([^/]+)")


def audit_log_response(response: Response) -> Response:
    """
    after_request hook that logs admin actions (POST/PUT/DELETE).

    Attach to a Blueprint via: blueprint.after_request(audit_log_response)
    """
    if request.method not in AUDIT_METHODS:
        return response

    # Extract username from path if present
    username = None
    match = _USERNAME_RE.search(request.path)
    if match:
        username = match.group(1)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "api_admin_action",
        "method": request.method,
        "path": request.path,
        "endpoint": request.endpoint,
        "status_code": response.status_code,
        "remote_addr": request.remote_addr,
    }

    if username:
        entry["username"] = username

    audit_logger.info(entry)
    return response
