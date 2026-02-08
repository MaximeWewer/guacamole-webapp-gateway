"""
Factory for creating container orchestrators.
"""

from __future__ import annotations

import logging
import threading

from typing import Any

from broker.config.loader import BrokerConfig
from broker.domain.orchestrator.base import ContainerOrchestrator

logger = logging.getLogger("session-broker")

# Singleton instance
_lock = threading.Lock()
_orchestrator: Any = None


def get_orchestrator() -> ContainerOrchestrator:
    """
    Get the configured container orchestrator.

    Uses double-checked locking to ensure only one orchestrator instance
    exists even when accessed concurrently from multiple threads.

    Returns:
        ContainerOrchestrator instance (Docker or Kubernetes)
    """
    global _orchestrator

    if _orchestrator is not None:
        return _orchestrator

    with _lock:
        if _orchestrator is not None:
            return _orchestrator

        backend = BrokerConfig.settings().orchestrator.backend
        logger.info(f"Initializing {backend} orchestrator")

        if backend == "kubernetes":
            from broker.domain.orchestrator.kubernetes_orchestrator import (
                KubernetesOrchestrator,
            )

            _orchestrator = KubernetesOrchestrator()
        else:
            from broker.domain.orchestrator.docker_orchestrator import DockerOrchestrator

            _orchestrator = DockerOrchestrator()

    return _orchestrator


def reset_orchestrator() -> None:
    """
    Reset the orchestrator singleton.

    Useful for testing or configuration changes.
    """
    global _orchestrator
    with _lock:
        _orchestrator = None
