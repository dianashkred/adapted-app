"""Alembic environment.

Migrations run as the login role ``adapted_migrator`` and switch to the group role ``admin``
(``SET ROLE``), so every object is owned by ``admin`` and the default privileges of migration 0002
apply automatically to new tables, sequences and views.

URL: env var MIGRATOR_DATABASE_URL (from .env), or ``alembic -x url=...``.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  (registers all tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
MIGRATION_ROLE = os.environ.get("MIGRATION_ROLE", "admin")


def _url() -> str:
    return context.get_x_argument(as_dictionary=True).get("url") or get_settings().migrator_database_url


def run_migrations_offline() -> None:
    """``alembic upgrade head --sql`` prints the DDL without a database."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.execute(f"SET ROLE {MIGRATION_ROLE}")
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        if MIGRATION_ROLE:
            connection.execute(text(f"SET ROLE {MIGRATION_ROLE}"))
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():   # each upgrade runs in ONE transaction (all or nothing)
            context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
