"""
Alembic environment configuration using raw psycopg2 (no SQLAlchemy).

Reads database connection parameters from broker.persistence.database.DB_CONFIG.
"""

from alembic import context

from broker.persistence.database import DB_CONFIG


def _build_url() -> str:
    """Build a PostgreSQL URL from DB_CONFIG for offline mode."""
    return (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live connection)."""
    context.configure(
        url=_build_url(),
        target_metadata=None,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live psycopg2 connection."""
    import psycopg2

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        # Alembic needs autocommit for DDL when using raw DBAPI connections
        conn.autocommit = True
        context.configure(
            connection=conn,
            target_metadata=None,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        conn.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
