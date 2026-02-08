"""Initial schema — captures the tables previously created by init_database().

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sessions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS broker_sessions (
            session_id VARCHAR(36) PRIMARY KEY,
            username VARCHAR(255),
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

    # Groups table
    op.execute("""
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
    op.execute("""
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
    op.execute("""
        CREATE TABLE IF NOT EXISTS broker_settings (
            key VARCHAR(255) PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_username ON broker_sessions(username)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_connection ON broker_sessions(guac_connection_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_group ON broker_bookmarks(group_name)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_username_unique
        ON broker_sessions(username) WHERE username IS NOT NULL
    """)

    # Default settings
    op.execute("""
        INSERT INTO broker_settings (key, value)
        VALUES ('merge_bookmarks', 'true'), ('inherit_from_default', 'true')
        ON CONFLICT (key) DO NOTHING
    """)

    # Default group
    op.execute("""
        INSERT INTO broker_groups (group_name, description, priority)
        VALUES ('default', 'Default configuration for all users', 0)
        ON CONFLICT (group_name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS broker_bookmarks")
    op.execute("DROP TABLE IF EXISTS broker_settings")
    op.execute("DROP TABLE IF EXISTS broker_sessions")
    op.execute("DROP TABLE IF EXISTS broker_groups")
