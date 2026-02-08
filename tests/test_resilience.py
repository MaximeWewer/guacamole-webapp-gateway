"""
Tests for broker.resilience (CircuitBreaker) and graceful shutdown.
"""

import time
from unittest.mock import MagicMock

import pytest

from broker.resilience import CircuitBreaker, CircuitOpenError, CircuitState


# ---------------------------------------------------------------------------
# CircuitBreaker — CLOSED state
# ---------------------------------------------------------------------------

class TestCircuitBreakerClosed:

    def test_call_ok(self):
        """Successful call passes through and circuit stays CLOSED."""
        cb = CircuitBreaker(name="test-ok", failure_threshold=3)
        result = cb.call(lambda x: x * 2, 5)
        assert result == 10
        assert cb.state == CircuitState.CLOSED

    def test_single_failure_stays_closed(self):
        """One failure does not trip the circuit."""
        cb = CircuitBreaker(name="test-1fail", failure_threshold=3)

        with pytest.raises(ValueError):
            cb.call(_raise, ValueError("boom"))

        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_counter(self):
        """A success after failures resets the consecutive failure counter."""
        cb = CircuitBreaker(name="test-reset", failure_threshold=3)

        # 2 failures
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_raise, ValueError("x"))

        # 1 success → resets counter
        cb.call(lambda: "ok")

        # 2 more failures — should NOT trip (counter was reset)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_raise, ValueError("x"))

        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# CircuitBreaker — tripping to OPEN
# ---------------------------------------------------------------------------

class TestCircuitBreakerTrips:

    def test_trips_after_threshold(self):
        """Circuit trips to OPEN after failure_threshold consecutive failures."""
        cb = CircuitBreaker(name="test-trip", failure_threshold=3, recovery_timeout=60)

        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(_raise, ValueError("x"))

        assert cb.state == CircuitState.OPEN

    def test_open_raises_circuit_open_error(self):
        """Calls while OPEN raise CircuitOpenError immediately (no actual call)."""
        cb = CircuitBreaker(name="test-open", failure_threshold=2, recovery_timeout=60)

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_raise, ValueError("x"))

        spy = MagicMock()
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(spy)
        spy.assert_not_called()
        assert exc_info.value.retry_after > 0

    def test_circuit_open_error_attributes(self):
        """CircuitOpenError carries name and retry_after."""
        err = CircuitOpenError("guacamole", 15.5)
        assert err.name == "guacamole"
        assert err.retry_after == 15.5
        assert "guacamole" in str(err)


# ---------------------------------------------------------------------------
# CircuitBreaker — recovery (HALF_OPEN)
# ---------------------------------------------------------------------------

class TestCircuitBreakerRecovery:

    def test_half_open_after_timeout(self):
        """State becomes HALF_OPEN after recovery_timeout has elapsed."""
        cb = CircuitBreaker(name="test-ho", failure_threshold=1, recovery_timeout=0.05)

        with pytest.raises(ValueError):
            cb.call(_raise, ValueError("x"))
        assert cb.state == CircuitState.OPEN

        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

    def test_probe_success_closes(self):
        """Successful probe in HALF_OPEN → back to CLOSED."""
        cb = CircuitBreaker(name="test-close", failure_threshold=1, recovery_timeout=0.05)

        with pytest.raises(ValueError):
            cb.call(_raise, ValueError("x"))

        time.sleep(0.06)
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    def test_probe_failure_reopens(self):
        """Failed probe in HALF_OPEN → back to OPEN."""
        cb = CircuitBreaker(name="test-reopen", failure_threshold=1, recovery_timeout=0.05)

        with pytest.raises(ValueError):
            cb.call(_raise, ValueError("x"))

        time.sleep(0.06)
        with pytest.raises(RuntimeError):
            cb.call(_raise, RuntimeError("still broken"))

        assert cb.state == CircuitState.OPEN

    def test_reset_force_closes(self):
        """reset() brings the circuit back to CLOSED regardless of state."""
        cb = CircuitBreaker(name="test-force", failure_threshold=1)

        with pytest.raises(ValueError):
            cb.call(_raise, ValueError("x"))
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED

        # Calls work again
        assert cb.call(lambda: 42) == 42


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:

    def test_monitor_stop(self):
        """ConnectionMonitor.stop() sets the stop event and running=False."""
        from broker.services.connection_monitor import ConnectionMonitor

        monitor = ConnectionMonitor(interval=5)
        monitor._running = True
        monitor.stop()

        assert monitor.running is False
        assert monitor._stop_event.is_set()

    def test_user_sync_stop(self):
        """UserSyncService.stop() sets the stop event and running=False."""
        from broker.services.user_sync import UserSyncService

        sync = UserSyncService(interval=60)
        sync.running = True
        sync.stop()

        assert sync.running is False
        assert sync._stop_event.is_set()

    def test_container_shutdown(self):
        """ServiceContainer.shutdown() calls stop() on both services."""
        from broker.container import ServiceContainer

        container = ServiceContainer()
        mock_sync = MagicMock()
        mock_monitor = MagicMock()
        container._user_sync = mock_sync
        container._monitor = mock_monitor

        container.shutdown()

        mock_sync.stop.assert_called_once()
        mock_monitor.stop.assert_called_once()

    def test_container_shutdown_without_services(self):
        """shutdown() is safe when no services have been initialized."""
        from broker.container import ServiceContainer

        container = ServiceContainer()
        # Should not raise
        container.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raise(exc: Exception) -> None:
    """Helper: raise the given exception."""
    raise exc
