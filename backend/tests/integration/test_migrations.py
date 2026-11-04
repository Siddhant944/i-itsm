"""``alembic upgrade head`` must build exactly the schema the models describe.

The models are the single description of the schema and the migration is generated from them,
so the two can drift silently. Alembic's own comparison is the guard: after an upgrade it must
find nothing to change, on SQLite and on PostgreSQL.
"""

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import TABLE_COUNT, Base

BACKEND = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND / "alembic.ini"


def alembic_config(database_url: str) -> Config:
    """An Alembic config pointed at ``database_url`` through ``-x url=`` (see alembic/env.py)."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.cmd_opts = argparse.Namespace(x=[f"url={database_url}"])
    return config


@pytest.fixture
def clean_engine(database_url: str) -> Iterator[Engine]:
    engine = make_engine(database_url)
    _drop_everything(engine)
    yield engine
    _drop_everything(engine)
    engine.dispose()


def _drop_everything(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        if "alembic_version" in inspect(connection).get_table_names():
            connection.exec_driver_sql("DROP TABLE alembic_version")


def test_upgrade_head_creates_every_table(clean_engine: Engine, database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
    tables = set(inspect(clean_engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    assert len(tables) == TABLE_COUNT


def test_the_migrations_and_the_models_do_not_drift(
    clean_engine: Engine, database_url: str
) -> None:
    command.upgrade(alembic_config(database_url), "head")
    with clean_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == [], f"Run `alembic revision --autogenerate`: {differences}"


def test_downgrade_removes_the_schema(clean_engine: Engine, database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    tables = set(inspect(clean_engine).get_table_names()) - {"alembic_version"}
    assert tables == set()


def test_there_is_exactly_one_head() -> None:
    """Two heads mean two people generated a migration from the same parent."""
    scripts = ScriptDirectory.from_config(alembic_config("sqlite://"))
    assert len(scripts.get_heads()) == 1
