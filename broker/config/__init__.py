"""Configuration module for the Session Broker."""

from broker.config.settings import (
    VNC_PORT,
    VNC_CONTAINER_TIMEOUT,
    VNC_PASSWORD_LENGTH,
    SESSION_ID_LENGTH,
    USERNAME_PATTERN,
    MAX_USERNAME_LENGTH,
    GROUP_NAME_PATTERN,
    MAX_GROUP_NAME_LENGTH,
    URL_PATTERN,
    get_env,
)
from broker.config.secrets import secrets_provider, SecretsProvider
from broker.config.loader import (
    BrokerConfig,
    ProfilesConfig,
    YAMLConfig,  # Backward compatibility alias
    CONFIG_PATH,
    PROFILES_CONFIG_FILE,
    BROKER_CONFIG_FILE,
)

__all__ = [
    "VNC_PORT",
    "VNC_CONTAINER_TIMEOUT",
    "VNC_PASSWORD_LENGTH",
    "SESSION_ID_LENGTH",
    "USERNAME_PATTERN",
    "MAX_USERNAME_LENGTH",
    "GROUP_NAME_PATTERN",
    "MAX_GROUP_NAME_LENGTH",
    "URL_PATTERN",
    "get_env",
    "secrets_provider",
    "SecretsProvider",
    "BrokerConfig",
    "ProfilesConfig",
    "YAMLConfig",
    "CONFIG_PATH",
    "PROFILES_CONFIG_FILE",
    "BROKER_CONFIG_FILE",
]
