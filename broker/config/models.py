"""
Pydantic models for broker configuration.

Mirrors the defaults dict in loader.py, providing typed access
to all broker.yml settings via BrokerConfig.settings().
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SyncConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interval: int = 60
    ignored_users: list[str] = ["guacadmin"]
    sync_config_on_restart: bool = False


class DockerOrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    network: str = "guacamole_vnc-network"


class KubernetesResourceSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    memory: str = "512Mi"
    cpu: str = "250m"


class KubernetesResources(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requests: KubernetesResourceSpec = KubernetesResourceSpec()
    limits: KubernetesResourceSpec = KubernetesResourceSpec(memory="2Gi", cpu="1000m")


class KubernetesSecurityContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_as_non_root: bool = False
    run_as_user: int = 1000


class KubernetesOrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    namespace: str = "guacamole"
    service_account: str = ""
    labels: dict[str, str] = {"app": "vnc-session", "managed-by": "guacamole-broker"}
    image_pull_policy: str = "IfNotPresent"
    image_pull_secrets: list[str] = []
    node_selector: dict[str, str] = {}
    tolerations: list[dict[str, str]] = []
    resources: KubernetesResources = KubernetesResources()
    security_context: KubernetesSecurityContext = KubernetesSecurityContext()


class OrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str = "docker"
    docker: DockerOrchestratorConfig = DockerOrchestratorConfig()
    kubernetes: KubernetesOrchestratorConfig = KubernetesOrchestratorConfig()


class ContainersConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image: str = "ghcr.io/maximewewer/docker-browser-vnc:latest"
    connection_name: str = "Virtual Desktop"
    network: str = "guacamole_vnc-network"
    memory_limit: str = "1g"
    shm_size: str = "128m"
    vnc_timeout: int = 30


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persist_after_disconnect: bool = True
    idle_timeout_minutes: int = 3
    force_kill_on_low_resources: bool = True


class PoolResourcesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min_free_memory_gb: float = 2.0
    max_total_memory_gb: float = 16.0
    max_memory_percent: float = 0.75


class PoolConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    init_containers: int = 2
    max_containers: int = 10
    batch_size: int = 3
    resources: PoolResourcesConfig = PoolResourcesConfig()


class RecordingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    path: str = "/recordings"
    name: str = "${GUAC_USERNAME}-${GUAC_DATE}-${GUAC_TIME}"
    include_keys: bool = False
    auto_create_path: bool = True


class GuacamoleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    force_home_page: bool = True
    home_connection_name: str = "Home"
    recording: RecordingConfig = RecordingConfig()


class RateLimitingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    default_limit: str = "200/minute"
    admin_limit: str = "10/minute"


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key: str = ""
    rate_limiting: RateLimitingConfig = RateLimitingConfig()


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: str = "INFO"


class BrokerSettings(BaseModel):
    """Root settings model mirroring broker.yml structure."""

    model_config = ConfigDict(extra="ignore")

    sync: SyncConfig = SyncConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()
    containers: ContainersConfig = ContainersConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()
    pool: PoolConfig = PoolConfig()
    guacamole: GuacamoleConfig = GuacamoleConfig()
    security: SecurityConfig = SecurityConfig()
    logging: LoggingConfig = LoggingConfig()
