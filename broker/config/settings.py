"""
Constants and settings for the Session Broker.
"""

import re

# =============================================================================
# Constants
# =============================================================================

VNC_PORT = 5901
VNC_CONTAINER_TIMEOUT = 30
VNC_PASSWORD_LENGTH = 32
SESSION_ID_LENGTH = 8

# Username validation pattern (alphanumeric, dash, underscore, dot)
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
MAX_USERNAME_LENGTH = 255

# Group name validation
GROUP_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
MAX_GROUP_NAME_LENGTH = 255

# URL validation (basic)
URL_PATTERN = re.compile(r'^https?://')


def get_env(key: str, default: str = None, required: bool = False) -> str:
    """
    Retrieve an environment variable with Vault support.

    Args:
        key: Configuration key
        default: Default value
        required: Whether the value is required

    Returns:
        Configuration value

    Raises:
        ValueError: If required value is missing
    """
    # Import here to avoid circular imports
    from broker.config.secrets import secrets_provider

    value = secrets_provider.get(key, default)
    if required and not value:
        raise ValueError(f"Required configuration missing: {key}")
    return value
