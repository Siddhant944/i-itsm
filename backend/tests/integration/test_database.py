from pathlib import Path

from sqlalchemy import text

from app.repositories.database import make_engine, ping


def test_engine_connects_to_configured_database(database_url: str) -> None:
    engine = make_engine(database_url)
    try:
        assert ping(engine)
    finally:
        engine.dispose()


def test_sqlite_enables_foreign_keys_and_wal(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'pragma.db'}")
    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
    engine.dispose()

    assert foreign_keys == 1
    assert journal_mode == "wal"
