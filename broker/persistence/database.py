"""
Database connection and initialization for the Session Broker.
"""

import logging
from contextlib import contextmanager

import psycopg2

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
    "port": int(DATABASE_PORT),
    "database": DATABASE_NAME,
    "user": DATABASE_USER,
    "password": DATABASE_PASSWORD
}


@contextmanager
def get_db_connection():
    """
    Context manager for database connections.

    Yields:
        Database connection

    Note:
        Commits on success, rolls back on exception.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    """Initialize database tables for the broker."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Sessions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_sessions (
                    session_id VARCHAR(36) PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    guac_connection_id VARCHAR(36),
                    vnc_password VARCHAR(64),
                    container_id VARCHAR(64),
                    container_ip VARCHAR(45),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    last_activity TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add last_activity column if it doesn't exist (migration)
            cur.execute("""
                ALTER TABLE broker_sessions
                ADD COLUMN IF NOT EXISTS last_activity TIMESTAMP
            """)

            # Groups table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_groups (
                    group_name VARCHAR(255) PRIMARY KEY,
                    description TEXT,
                    priority INTEGER DEFAULT 0,
                    wallpaper VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Bookmarks table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_bookmarks (
                    id SERIAL PRIMARY KEY,
                    group_name VARCHAR(255) REFERENCES broker_groups(group_name) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    url TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    UNIQUE(group_name, url)
                )
            """)

            # Settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes for performance
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_username ON broker_sessions(username)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_connection ON broker_sessions(guac_connection_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_group ON broker_bookmarks(group_name)")

            # Initialize default settings
            cur.execute("""
                INSERT INTO broker_settings (key, value)
                VALUES ('merge_bookmarks', 'true'), ('inherit_from_default', 'true')
                ON CONFLICT (key) DO NOTHING
            """)

            # Create default group if not exists
            cur.execute("""
                INSERT INTO broker_groups (group_name, description, priority)
                VALUES ('default', 'Default configuration for all users', 0)
                ON CONFLICT (group_name) DO NOTHING
            """)

    logger.info("Database initialized")
