"""
Programmatic Alembic migration runner.

Detects whether the database already has tables (pre-Alembic) and stamps
the initial revision before running upgrade("head").
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
from alembic import command
from alembic.config import Config

from broker.persistence.database import DB_CONFIG

logger = logging.getLogger("session-broker")

_INITIAL_REVISION = "001"


def _get_alembic_config() -> Config:
    """Resolve and return an Alembic Config object."""
    ini_path = os.environ.get("ALEMBIC_INI")
    if ini_path is None:
        ini_path = str(Path(__file__).resolve().parent.parent / "alembic.ini")
    cfg = Config(ini_path)
    return cfg


def _is_pre_existing_database() -> bool:
    """Check if the DB has broker tables but no alembic_version table.

    Uses a direct connection (not from the pool) so this can run
    before the pool is ready or independently of it.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # Check for broker_sessions table
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'broker_sessions'"
            )
            has_tables = cur.fetchone() is not None

            # Check for alembic_version table
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
            has_alembic = cur.fetchone() is not None
        return has_tables and not has_alembic
    finally:
        conn.close()


def run_migrations() -> None:
    """Run Alembic migrations to bring the database to the latest revision.

    If the database already has broker tables but no ``alembic_version``
    table (pre-existing database), the initial revision is stamped
    without executing its SQL, then ``upgrade("head")`` applies any
    subsequent migrations.
    """
    cfg = _get_alembic_config()

    if _is_pre_existing_database():
        logger.info(
            "Pre-existing database detected — stamping revision %s",
            _INITIAL_REVISION,
        )
        command.stamp(cfg, _INITIAL_REVISION)

    logger.info("Running database migrations (upgrade to head)")
    command.upgrade(cfg, "head")
    logger.info("Database migrations complete")
