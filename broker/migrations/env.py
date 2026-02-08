"""
Alembic environment configuration.

Reads database connection parameters from broker.persistence.database.DB_CONFIG
and uses SQLAlchemy (bundled with Alembic) for the connection layer.
"""

from alembic import context
from sqlalchemy import create_engine

from broker.persistence.database import DB_CONFIG


def _build_url() -> str:
    """Build a PostgreSQL URL from DB_CONFIG."""
    return (
        f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
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
    """Run migrations in 'online' mode with a live database connection."""
    engine = create_engine(_build_url())
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=None,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
