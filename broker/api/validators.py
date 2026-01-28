"""
Input validation functions for the API.
"""

import html

from broker.config.settings import (
    USERNAME_PATTERN,
    MAX_USERNAME_LENGTH,
    GROUP_NAME_PATTERN,
    MAX_GROUP_NAME_LENGTH,
    URL_PATTERN,
)


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def validate_username(username: str) -> str:
    """
    Validate and sanitize username.

    Args:
        username: The username to validate

    Returns:
        Sanitized username

    Raises:
        ValidationError: If username is invalid
    """
    if not username:
        raise ValidationError("Username is required")

    if len(username) > MAX_USERNAME_LENGTH:
        raise ValidationError(f"Username exceeds maximum length of {MAX_USERNAME_LENGTH}")

    if not USERNAME_PATTERN.match(username):
        raise ValidationError("Username contains invalid characters")

    return username


def validate_group_name(group_name: str) -> str:
    """
    Validate and sanitize group name.

    Args:
        group_name: The group name to validate

    Returns:
        Sanitized group name

    Raises:
        ValidationError: If group name is invalid
    """
    if not group_name:
        raise ValidationError("Group name is required")

    if len(group_name) > MAX_GROUP_NAME_LENGTH:
        raise ValidationError(f"Group name exceeds maximum length of {MAX_GROUP_NAME_LENGTH}")

    if not GROUP_NAME_PATTERN.match(group_name):
        raise ValidationError("Group name contains invalid characters")

    return group_name


def validate_url(url: str) -> str:
    """
    Validate URL format.

    Args:
        url: The URL to validate

    Returns:
        Validated URL

    Raises:
        ValidationError: If URL is invalid
    """
    if not url:
        raise ValidationError("URL is required")

    if not URL_PATTERN.match(url):
        raise ValidationError("Invalid URL format (must start with http:// or https://)")

    return url


def sanitize_for_path(value: str) -> str:
    """
    Sanitize a string for use in file paths.

    Args:
        value: String to sanitize

    Returns:
        Safe string for file paths
    """
    return "".join(c for c in value if c.isalnum() or c in "-_")


def escape_html_content(text: str) -> str:
    """
    Escape HTML special characters to prevent XSS.

    Args:
        text: Text to escape

    Returns:
        HTML-escaped text
    """
    return html.escape(text, quote=True)
