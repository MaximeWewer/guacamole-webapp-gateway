"""
Container orchestration module.

Supports both Docker and Kubernetes backends for VNC container management.
"""

from broker.domain.orchestrator.base import ContainerInfo, ContainerOrchestrator
from broker.domain.orchestrator.factory import get_orchestrator

__all__ = ["ContainerInfo", "ContainerOrchestrator", "get_orchestrator"]
