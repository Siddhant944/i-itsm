"""Shared fixtures. TEST_DATABASE_URL selects the database (SQLite in memory by default)."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """``live`` tests call real external APIs; they run only with RUN_LIVE_TESTS=1 (AGENTS.md)."""
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="calls a real external API; set RUN_LIVE_TESTS=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    default = f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    return os.environ.get("TEST_DATABASE_URL") or default


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(app_env=AppEnv.TEST, database_url=database_url, _env_file=None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
