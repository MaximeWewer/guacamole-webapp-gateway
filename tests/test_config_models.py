"""
Tests for broker.config.models (Pydantic settings).
"""

import pytest

from broker.config.models import BrokerSettings


class TestBrokerSettingsDefaults:
    """BrokerSettings() with no args should match the defaults dict in loader.py."""

    def test_default_lifecycle(self):
        s = BrokerSettings()
        assert s.lifecycle.persist_after_disconnect is True
        assert s.lifecycle.idle_timeout_minutes == 3
        assert s.lifecycle.force_kill_on_low_resources is True

    def test_default_sync(self):
        s = BrokerSettings()
        assert s.sync.interval == 60
        assert s.sync.ignored_users == ["guacadmin"]
        assert s.sync.sync_config_on_restart is False

    def test_default_containers(self):
        s = BrokerSettings()
        assert "vnc" in s.containers.image.lower() or "browser" in s.containers.image.lower()
        assert s.containers.connection_name == "Virtual Desktop"
        assert s.containers.memory_limit == "1g"
        assert s.containers.shm_size == "128m"
        assert s.containers.vnc_timeout == 30

    def test_default_pool(self):
        s = BrokerSettings()
        assert s.pool.enabled is True
        assert s.pool.init_containers == 2
        assert s.pool.max_containers == 10
        assert s.pool.resources.min_free_memory_gb == 2.0
        assert s.pool.resources.max_total_memory_gb == 16.0

    def test_default_guacamole(self):
        s = BrokerSettings()
        assert s.guacamole.force_home_page is True
        assert s.guacamole.recording.enabled is False
        assert s.guacamole.recording.path == "/recordings"

    def test_default_security(self):
        s = BrokerSettings()
        assert s.security.rate_limiting.enabled is True
        assert s.security.rate_limiting.default_limit == "200/minute"

    def test_default_orchestrator(self):
        s = BrokerSettings()
        assert s.orchestrator.backend == "docker"
        assert s.orchestrator.docker.network == "guacamole_vnc-network"
        assert s.orchestrator.kubernetes.namespace == "guacamole"


class TestBrokerSettingsPartial:
    """Partial config dicts should merge with defaults."""

    def test_partial_lifecycle(self):
        s = BrokerSettings(lifecycle={"persist_after_disconnect": False})
        assert s.lifecycle.persist_after_disconnect is False
        # Other fields keep defaults
        assert s.lifecycle.idle_timeout_minutes == 3

    def test_partial_pool_resources(self):
        s = BrokerSettings(pool={"resources": {"min_free_memory_gb": 4.0}})
        assert s.pool.resources.min_free_memory_gb == 4.0
        # Defaults preserved
        assert s.pool.resources.max_total_memory_gb == 16.0
        assert s.pool.enabled is True

    def test_partial_recording(self):
        s = BrokerSettings(guacamole={"recording": {"enabled": True}})
        assert s.guacamole.recording.enabled is True
        assert s.guacamole.recording.path == "/recordings"

    def test_extra_keys_ignored(self):
        """Unknown keys in YAML should not raise errors."""
        s = BrokerSettings(
            lifecycle={"persist_after_disconnect": True, "unknown_key": "ignored"}
        )
        assert s.lifecycle.persist_after_disconnect is True


class TestBrokerSettingsFromYaml:
    """Simulate loading from broker.yml dict."""

    def test_full_yaml_dict(self):
        yaml_dict = {
            "sync": {"interval": 30, "ignored_users": ["guacadmin", "svc-account"]},
            "orchestrator": {
                "backend": "kubernetes",
                "kubernetes": {"namespace": "prod", "resources": {"limits": {"memory": "4Gi"}}},
            },
            "containers": {"image": "my-registry/vnc:1.0", "memory_limit": "2g"},
            "lifecycle": {"persist_after_disconnect": False, "idle_timeout_minutes": 10},
            "pool": {"enabled": False},
            "guacamole": {"recording": {"enabled": True, "path": "/data/rec"}},
            "security": {"rate_limiting": {"admin_limit": "5/minute"}},
            "logging": {"level": "DEBUG"},
        }
        s = BrokerSettings(**yaml_dict)
        assert s.sync.interval == 30
        assert s.orchestrator.backend == "kubernetes"
        assert s.orchestrator.kubernetes.namespace == "prod"
        assert s.orchestrator.kubernetes.resources.limits.memory == "4Gi"
        assert s.containers.image == "my-registry/vnc:1.0"
        assert s.lifecycle.persist_after_disconnect is False
        assert s.pool.enabled is False
        assert s.guacamole.recording.enabled is True
        assert s.guacamole.recording.path == "/data/rec"
        assert s.security.rate_limiting.admin_limit == "5/minute"
        assert s.logging.level == "DEBUG"
