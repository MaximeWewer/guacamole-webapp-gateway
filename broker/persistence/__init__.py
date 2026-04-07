"""Persistence module for database operations."""

import importlib
import types

from broker.persistence.database import (
    DB_CONFIG,
    close_pool,
    get_db_connection,
    get_pool_stats,
    init_pool,
)

__all__ = [
    "DB_CONFIG",
    "close_pool",
    "get_db_connection",
    "get_pool_stats",
    "init_pool",
    "migrations",
]


def __getattr__(name: str) -> types.ModuleType:
    if name == "migrations":
        return importlib.import_module("broker.persistence.migrations")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
