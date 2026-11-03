"""Database engine factory. SQLite gets ``foreign_keys=ON`` and WAL mode (blueprint §9)."""

from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine.url import make_url


def make_engine(database_url: str) -> Engine:
    """Create an engine for SQLite or PostgreSQL with the project's connection settings."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _sqlite_pragmas)
        return engine
    return create_engine(url, pool_pre_ping=True)


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def ping(engine: Engine) -> bool:
    """Return True when the database answers a trivial query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
