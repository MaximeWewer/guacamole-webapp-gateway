"""
API response helpers for standardized responses.
"""

from typing import Any

from flask import jsonify, Response


def api_success(data: Any = None, message: str = None, status_code: int = 200) -> tuple[Response, int]:
    """
    Create a standardized success API response.

    Args:
        data: Response data
        message: Optional success message
        status_code: HTTP status code

    Returns:
        Tuple of (response, status_code)
    """
    response = {"success": True}
    if data is not None:
        response["data"] = data
    if message:
        response["message"] = message
    return jsonify(response), status_code


def api_error(message: str, status_code: int = 400, details: Any = None) -> tuple[Response, int]:
    """
    Create a standardized error API response.

    Args:
        message: Error message
        status_code: HTTP status code
        details: Optional error details

    Returns:
        Tuple of (response, status_code)
    """
    response = {"success": False, "error": message}
    if details:
        response["details"] = details
    return jsonify(response), status_code
