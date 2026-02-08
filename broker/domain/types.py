"""
Typed data structures for the broker domain.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class SessionData:
    """Typed representation of a broker session."""

    session_id: str
    username: str | None = None
    guac_connection_id: str | None = None
    vnc_password: str | None = None
    container_id: str | None = None
    container_ip: str | None = None
    created_at: float | None = None
    started_at: float | None = None
    last_activity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionData:
        # Only pass keys that match dataclass fields
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
