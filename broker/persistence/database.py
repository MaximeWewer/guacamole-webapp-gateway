"""
Database connection pooling for the Session Broker.

Uses psycopg2's ThreadedConnectionPool for thread-safe connection reuse.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from broker.config.settings import get_env

logger = logging.getLogger("session-broker")

# Database configuration
DATABASE_HOST = get_env("database_host", "postgres")
DATABASE_PORT = get_env("database_port", "5432")
DATABASE_NAME = get_env("database_name", "guacamole")
DATABASE_USER = get_env("database_user", "guacamole")
DATABASE_PASSWORD = get_env("database_password", required=True)

DB_CONFIG = {
    "host": DATABASE_HOST,
    "port": int(DATABASE_PORT or "5432"),
    "database": DATABASE_NAME,
    "user": DATABASE_USER,
    "password": DATABASE_PASSWORD,
}

# Pool configuration
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "8"))

# Module-level pool and lock
_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def init_pool() -> None:
    """Initialize the connection pool (idempotent).

    Raises on failure so the application fails fast at startup
    if the database is unreachable.
    """
    global _pool
    if _pool is not None:
        return
    with _pool_lock:
        if _pool is not None:
            return
        _pool = ThreadedConnectionPool(
            DB_POOL_MIN,
            DB_POOL_MAX,
            **DB_CONFIG,
        )
        logger.info(
            "Database connection pool initialized (min=%d, max=%d)",
            DB_POOL_MIN,
            DB_POOL_MAX,
        )


def close_pool() -> None:
    """Close all connections in the pool (idempotent)."""
    global _pool
    if _pool is None:
        return
    with _pool_lock:
        if _pool is None:
            return
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


def get_pool_stats() -> dict[str, int]:
    """Return current pool statistics.

    Returns zeros when the pool is not initialized.
    """
    if _pool is None:
        return {"pool_size": 0, "pool_used": 0}
    # _pool._used is a dict of connections currently checked out
    # _pool._pool is a list of idle connections
    used = len(getattr(_pool, "_used", {}))
    idle = len(getattr(_pool, "_pool", []))
    return {"pool_size": used + idle, "pool_used": used}


@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context manager for database connections from the pool.

    Yields:
        Database connection

    Note:
        Commits on success, rolls back on exception.
        The connection is always returned to the pool.

    Raises:
        RuntimeError: If the pool has not been initialized.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call init_pool() first."
        )
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
