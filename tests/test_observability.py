"""
Tests for the observability module (Prometheus metrics + JSON logging).
"""

import json
import logging

import pytest
from prometheus_client import REGISTRY


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    """Tests for the /metrics Prometheus endpoint."""

    def test_metrics_endpoint_accessible(self, app_client):
        """GET /metrics returns 200 with Prometheus text content."""
        resp = app_client.get("/metrics")
        assert resp.status_code == 200
        body = resp.data.decode()
        # Prometheus exposition format includes HELP/TYPE lines
        assert "# HELP" in body or "# TYPE" in body

    def test_metrics_no_auth_required(self, app_client):
        """GET /metrics without API key still returns 200 (not behind blueprint auth)."""
        resp = app_client.get("/metrics", headers={})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Custom business metrics
# ---------------------------------------------------------------------------

class TestBusinessMetrics:
    """Tests for custom Prometheus metrics."""

    def test_provisioning_histogram_exists(self):
        """broker_provisioning_duration_seconds metric is registered."""
        from broker.observability import PROVISIONING_DURATION
        # Histogram should have _bucket, _count, _sum families
        names = {m.name for m in REGISTRY.collect()}
        assert "broker_provisioning_duration_seconds" in names

    def test_error_counter_increments(self):
        """broker_errors_total counter increments correctly."""
        from broker.observability import ERRORS_TOTAL
        before = ERRORS_TOTAL.labels(endpoint="test")._value.get()
        ERRORS_TOTAL.labels(endpoint="test").inc()
        after = ERRORS_TOTAL.labels(endpoint="test")._value.get()
        assert after == before + 1

    def test_active_containers_gauge(self):
        """broker_active_containers gauge can be set."""
        from broker.observability import ACTIVE_CONTAINERS
        ACTIVE_CONTAINERS.set(5)
        assert ACTIVE_CONTAINERS._value.get() == 5.0
        ACTIVE_CONTAINERS.set(0)

    def test_collect_business_metrics(self, mock_orchestrator):
        """collect_business_metrics updates gauges from orchestrator."""
        from broker.observability import (
            collect_business_metrics,
            ACTIVE_CONTAINERS,
            POOL_CONTAINERS,
        )
        mock_orchestrator.get_running_count.return_value = 3
        mock_orchestrator.get_pool_containers.return_value = [{"id": "a"}, {"id": "b"}]

        collect_business_metrics()

        assert ACTIVE_CONTAINERS._value.get() == 3.0
        assert POOL_CONTAINERS._value.get() == 2.0

        # Cleanup
        ACTIVE_CONTAINERS.set(0)
        POOL_CONTAINERS.set(0)


# ---------------------------------------------------------------------------
# JSON logging
# ---------------------------------------------------------------------------

class TestJsonLogging:
    """Tests for structured JSON logging setup."""

    def test_json_logging_format(self, capfd):
        """After setup_json_logging, log output is valid JSON."""
        from broker.observability import setup_json_logging
        setup_json_logging(level="DEBUG")

        test_logger = logging.getLogger("test.json_format")
        test_logger.info("hello structured world")

        captured = capfd.readouterr()
        # The JSON output goes to stderr
        for line in captured.err.strip().splitlines():
            if "hello structured world" in line:
                parsed = json.loads(line)
                assert parsed["message"] == "hello structured world"
                assert "timestamp" in parsed
                assert parsed["level"] == "INFO"
                break
        else:
            pytest.fail("JSON log line with expected message not found in stderr")
