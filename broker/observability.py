"""
Observability module: Prometheus metrics and structured JSON logging.

- Custom business metrics (Gauges, Counters, Histogram)
- PrometheusMetrics integration for automatic Flask instrumentation
- JSON structured logging via python-json-logger
- Periodic business metrics collection (called from ConnectionMonitor)
"""

import logging
import sys

from flask import Flask
from prometheus_client import Counter, Gauge, Histogram
from prometheus_flask_exporter import PrometheusMetrics

# =============================================================================
# Prometheus Custom Metrics
# =============================================================================

ACTIVE_CONTAINERS = Gauge(
    "broker_active_containers",
    "Number of VNC containers currently running",
)

POOL_CONTAINERS = Gauge(
    "broker_pool_containers",
    "Number of pool containers available (unclaimed)",
)

ACTIVE_CONNECTIONS = Gauge(
    "broker_active_connections",
    "Number of active Guacamole connections",
)

PROVISIONING_DURATION = Histogram(
    "broker_provisioning_duration_seconds",
    "Latency of user connection provisioning",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)

ERRORS_TOTAL = Counter(
    "broker_errors_total",
    "Total number of errors by endpoint",
    ["endpoint"],
)


# =============================================================================
# Metrics Initialization
# =============================================================================

def init_metrics(app: Flask) -> PrometheusMetrics:
    """
    Initialize PrometheusMetrics on the Flask app.

    Auto-instruments all routes with flask_http_request_duration_seconds
    and flask_http_request_total. Exposes /metrics endpoint.
    """
    metrics = PrometheusMetrics(app, path="/metrics")

    # Exempt /metrics from rate limiting
    from broker.api.rate_limit import limiter
    metrics_view = app.view_functions.get("prometheus_metrics")
    if metrics_view is not None:
        limiter.exempt(metrics_view)

    return metrics


# =============================================================================
# JSON Structured Logging
# =============================================================================

def setup_json_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with JSON structured output.

    Uses python-json-logger's JsonFormatter. The existing SensitiveDataFilter
    remains compatible (it modifies record.msg before formatting).
    The 'audit' logger is unaffected (propagate=False, own handler).
    """
    from pythonjsonlogger.json import JsonFormatter

    handler = logging.StreamHandler(sys.stderr)
    formatter = JsonFormatter(
        fmt="%(timestamp)s %(name)s %(levelname)s %(message)s",
        rename_fields={"levelname": "level", "asctime": "timestamp"},
        timestamp=True,
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


# =============================================================================
# Business Metrics Collection
# =============================================================================

def collect_business_metrics() -> None:
    """
    Update Gauges from current system state.

    Uses lazy imports to avoid circular dependencies.
    Called periodically from the ConnectionMonitor loop.
    """
    try:
        from broker.domain.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        ACTIVE_CONTAINERS.set(orchestrator.get_running_count())
        POOL_CONTAINERS.set(len(orchestrator.get_pool_containers()))
    except Exception:
        pass
