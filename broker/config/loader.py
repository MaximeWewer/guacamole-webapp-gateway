"""
Configuration loaders for broker.yml and profiles.yml.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import yaml

from broker.config.models import BrokerSettings
from broker.config.settings import get_env

logger = logging.getLogger("session-broker")

# Configuration paths
CONFIG_PATH = Path(get_env("config_path", "/data/config") or "/data/config")
PROFILES_CONFIG_FILE = CONFIG_PATH / "profiles.yml"
BROKER_CONFIG_FILE = CONFIG_PATH / "broker.yml"


class BrokerConfig:
    """Manages broker configuration from YAML file."""

    _lock = threading.Lock()
    _config: dict = {}
    _typed_config: BrokerSettings | None = None
    _last_load: float = 0
    _cache_duration: int = 60

    @classmethod
    def load(cls) -> dict:
        """Load broker configuration from YAML file."""
        now = time.time()
        if cls._config and (now - cls._last_load) < cls._cache_duration:
            return cls._config

        with cls._lock:
            # Double-check after acquiring the lock
            now = time.time()
            if cls._config and (now - cls._last_load) < cls._cache_duration:
                return cls._config
            return cls._load_locked(now)

    @classmethod
    def _load_locked(cls, now: float) -> dict:
        """Load config while holding ``_lock``. Called from :meth:`load`."""
        # Default configuration
        defaults = {
            "sync": {"interval": 60, "ignored_users": ["guacadmin"], "sync_config_on_restart": False},
            "orchestrator": {
                "backend": "docker",
                "docker": {
                    "network": "guacamole_vnc-network"
                },
                "kubernetes": {
                    "namespace": "guacamole",
                    "service_account": "",
                    "labels": {
                        "app": "vnc-session",
                        "managed-by": "guacamole-broker"
                    },
                    "image_pull_policy": "IfNotPresent",
                    "image_pull_secrets": [],
                    "node_selector": {},
                    "tolerations": [],
                    "resources": {
                        "requests": {
                            "memory": "512Mi",
                            "cpu": "250m"
                        },
                        "limits": {
                            "memory": "2Gi",
                            "cpu": "1000m"
                        }
                    },
                    "security_context": {
                        "run_as_non_root": False,
                        "run_as_user": 1000
                    }
                }
            },
            "containers": {
                "image": "ghcr.io/maximewewer/docker-browser-vnc:latest",
                "connection_name": "Virtual Desktop",
                "network": "guacamole_vnc-network",
                "memory_limit": "1g",
                "shm_size": "128m",
                "vnc_timeout": 30
            },
            "lifecycle": {
                "persist_after_disconnect": True,
                "idle_timeout_minutes": 3,
                "force_kill_on_low_resources": True
            },
            "pool": {
                "enabled": True,
                "init_containers": 2,
                "max_containers": 10,
                "batch_size": 3,
                "resources": {
                    "min_free_memory_gb": 2.0,
                    "max_total_memory_gb": 16.0,
                    "max_memory_percent": 0.75
                }
            },
            "guacamole": {
                "force_home_page": True,
                "home_connection_name": "Home",
                "recording": {
                    "enabled": False,
                    "path": "/recordings",
                    "name": "${GUAC_USERNAME}-${GUAC_DATE}-${GUAC_TIME}",
                    "include_keys": False,
                    "auto_create_path": True
                }
            },
            "security": {
                "api_key": "",
                "rate_limiting": {
                    "enabled": True,
                    "default_limit": "200/minute",
                    "admin_limit": "10/minute"
                }
            },
            "logging": {"level": "INFO"}
        }

        if not BROKER_CONFIG_FILE.exists():
            logger.info(f"Broker config not found, using defaults: {BROKER_CONFIG_FILE}")
            cls._config = defaults
            cls._typed_config = BrokerSettings.model_validate(cls._config)
            return cls._config

        try:
            with open(BROKER_CONFIG_FILE, "r") as f:
                file_config = yaml.safe_load(f) or {}

            # Deep merge with defaults
            cls._config = cls._deep_merge(defaults, file_config)
            cls._last_load = now
            logger.info(f"Loaded broker config from {BROKER_CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error loading broker config: {e}")
            cls._config = defaults

        cls._typed_config = BrokerSettings.model_validate(cls._config)
        return cls._config

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def get(cls, *keys: str, default: object = None) -> object:
        """Get a nested config value using dot notation or multiple keys."""
        config = cls.load()
        for key in keys:
            if isinstance(config, dict) and key in config:
                config = config[key]
            else:
                return default
        return config

    @classmethod
    def settings(cls) -> BrokerSettings:
        """Get typed configuration as a BrokerSettings instance."""
        if cls._typed_config is None:
            cls.load()
        assert cls._typed_config is not None
        return cls._typed_config

    @classmethod
    def get_browser_type(cls) -> str:
        """
        Detect browser type from the container image name.

        Returns:
            'firefox' or 'chromium'
        """
        image = str(cls.get("containers", "image", default=""))
        image_lower = image.lower()

        if "firefox" in image_lower:
            return "firefox"
        elif "chromium" in image_lower or "chrome" in image_lower:
            return "chromium"
        else:
            # Default to chromium if not detected
            logger.warning(f"Could not detect browser type from image '{image}', defaulting to chromium")
            return "chromium"


class ProfilesConfig:
    """Manages user profiles configuration from YAML file."""

    _lock = threading.Lock()
    _config: dict = {}
    _last_load: float = 0
    _cache_duration: int = 60  # Reload every 60 seconds

    @classmethod
    def load(cls) -> dict:
        """Load configuration from YAML file."""
        now = time.time()
        if cls._config and (now - cls._last_load) < cls._cache_duration:
            return cls._config

        with cls._lock:
            # Double-check after acquiring the lock
            now = time.time()
            if cls._config and (now - cls._last_load) < cls._cache_duration:
                return cls._config

            if not PROFILES_CONFIG_FILE.exists():
                logger.warning(f"Profiles config not found: {PROFILES_CONFIG_FILE}")
                cls._config = {"default": {"description": "Default", "priority": 0, "bookmarks": []}}
                return cls._config

            try:
                with open(PROFILES_CONFIG_FILE, "r") as f:
                    cls._config = yaml.safe_load(f) or {}
                cls._last_load = now
                logger.info(f"Loaded profiles from {PROFILES_CONFIG_FILE}: {len(cls._config)} profiles")
            except Exception as e:
                logger.error(f"Error loading profiles config: {e}")
                if not cls._config:
                    cls._config = {"default": {"description": "Default", "priority": 0, "bookmarks": []}}

        return cls._config

    @classmethod
    def get_profile(cls, profile_name: str) -> dict | None:
        """Get configuration for a specific profile."""
        config = cls.load()
        return config.get(profile_name)

    @classmethod
    def get_user_config(cls, user_groups: list[str]) -> dict[str, object]:
        """
        Get effective configuration for user based on their groups.
        Uses the highest priority profile that matches user's groups.
        """
        config = cls.load()
        groups: list[str] = []
        bookmarks: list[dict[str, str]] = []
        autofill: list[dict[str, str]] = []
        effective: dict[str, object] = {
            "homepage": "about:blank",
            "bookmarks": bookmarks,
            "autofill": autofill,
            "groups": groups,
        }

        # Find the highest priority matching profile
        best_profile = None
        best_priority = -1

        for group_name in user_groups:
            profile = config.get(group_name)
            if profile:
                priority = profile.get("priority", 0)
                if priority > best_priority:
                    best_priority = priority
                    best_profile = profile
                    groups.append(group_name)

        # Fall back to default if no matching profile
        if not best_profile and "default" in config:
            best_profile = config["default"]
            groups.append("default")

        if best_profile:
            effective["homepage"] = best_profile.get("homepage", "about:blank")
            effective["bookmarks"] = best_profile.get("bookmarks", [])
            effective["autofill"] = best_profile.get("autofill", [])

        return effective

    @classmethod
    def reload(cls) -> None:
        """Force reload configuration."""
        with cls._lock:
            cls._last_load = 0
        cls.load()


# Backward compatibility alias
YAMLConfig = ProfilesConfig
