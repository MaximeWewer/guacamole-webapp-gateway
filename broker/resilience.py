"""
Circuit breaker pattern for resilient external service calls.
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Any, Callable

from prometheus_client import Counter, Gauge


# =============================================================================
# Prometheus Metrics
# =============================================================================

CIRCUIT_STATE = Gauge(
    "broker_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["name"],
)

CIRCUIT_TRIPS = Counter(
    "broker_circuit_breaker_trips_total",
    "Number of times the circuit breaker tripped to OPEN",
    ["name"],
)


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitState(enum.Enum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and calls are rejected."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit '{name}' is OPEN (retry after {retry_after:.0f}s)")


class CircuitBreaker:
    """Thread-safe circuit breaker.

    - CLOSED: calls pass through; consecutive failures are counted.
    - After ``failure_threshold`` consecutive failures the circuit trips to OPEN.
    - OPEN: ``CircuitOpenError`` is raised immediately (no network call).
    - After ``recovery_timeout`` seconds the state moves to HALF_OPEN: one
      probe call is allowed through.
    - Probe success -> CLOSED; probe failure -> back to OPEN.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

        # Initialize metric
        CIRCUIT_STATE.labels(name=self.name).set(CircuitState.CLOSED.value)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    CIRCUIT_STATE.labels(name=self.name).set(CircuitState.HALF_OPEN.value)
            return self._state

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute *func* through the circuit breaker.

        The lock is **released** before the actual I/O call so that
        concurrent threads are not blocked while the network round-trip
        is in flight.
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    CIRCUIT_STATE.labels(name=self.name).set(CircuitState.HALF_OPEN.value)
                else:
                    retry_after = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
                    raise CircuitOpenError(self.name, max(0.0, retry_after))

        # Execute outside the lock (no lock held during I/O)
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._record_failure()
            raise

        self._record_success()
        return result

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED (admin / tests)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            CIRCUIT_STATE.labels(name=self.name).set(CircuitState.CLOSED.value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                CIRCUIT_STATE.labels(name=self.name).set(CircuitState.CLOSED.value)

    def _record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                CIRCUIT_STATE.labels(name=self.name).set(CircuitState.OPEN.value)
                CIRCUIT_TRIPS.labels(name=self.name).inc()
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                CIRCUIT_STATE.labels(name=self.name).set(CircuitState.OPEN.value)
                CIRCUIT_TRIPS.labels(name=self.name).inc()
