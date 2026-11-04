"""Alembic environment.

The URL comes from the application's own settings, so ``alembic upgrade head`` and the running
app always point at the same database. ``render_as_batch`` lets SQLite alter tables by copying
them, which it cannot do in place; the constraint naming convention in the models makes the
copied constraints predictable.
"""

from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Connection

from app.core.config import get_settings
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base
from app.repositories.sqlalchemy.types import Seconds, UtcDateTime

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which would silence every logger the
    # application has already created when migrations run in the same process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    """``-x url=...`` wins, then the configured DATABASE_URL."""
    return str(context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url)


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    """Render the project's own column types by name, so migrations import them."""
    if type_ == "type" and isinstance(obj, UtcDateTime | Seconds):
        autogen_context.imports.add("from app.repositories.sqlalchemy import types as itsm")
        return f"itsm.{type(obj).__name__}()"
    return False


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade head --sql``)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_url())
    try:
        with engine.connect() as connection:
            do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
