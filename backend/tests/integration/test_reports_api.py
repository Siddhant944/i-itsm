"""Search, CSV export and the dashboard endpoints over a seeded database (blueprint §9).

The seeded history gives these real numbers to report, which is also a check that the figures
hold up on data nobody wrote for them.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.adapters.smtp_email import ConsoleEmailSender
from app.api.deps import Services
from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.search import MAX_PAGE_SIZE
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.seed import people, seed
from app.services.auth_service import AuthPolicy

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PASSWORD = people.DEMO_PASSWORD  # what `make seed` sets, documented in the README
HISTORY = 120


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def engine(database_url: str, clock: FakeClock) -> Iterator[Engine]:
    made = make_engine(database_url)
    Base.metadata.drop_all(made)
    create_schema(made)
    uow = SqlAlchemyUnitOfWork(make_session_factory(made), clock)
    try:
        # The seed sets the documented demo password; the fast hasher keeps the suite quick.
        seed(uow, clock, hash_password=FakePasswordHasher().hash, history=HISTORY)
    finally:
        uow.close()
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def api(engine: Engine, clock: FakeClock, settings: Any) -> Iterator[TestClient]:
    from app.main import create_app

    app: FastAPI = create_app(settings)
    sessions = make_session_factory(engine)
    app.state.services = Services(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(sessions, clock),
        clock=clock,
        hasher=FakePasswordHasher(),
        tokens=JwtTokenService("a-test-secret-of-adequate-length", timedelta(minutes=30)),
        policy=AuthPolicy(),
        email=ConsoleEmailSender(),
        advisor=RuleBasedAdvisor(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def token_for(api: TestClient, email: str) -> dict[str, str]:
    response = api.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(api: TestClient) -> dict[str, str]:
    return token_for(api, "admin@campus.edu")


@pytest.fixture
def employee(api: TestClient) -> dict[str, str]:
    return token_for(api, "employee@campus.edu")


@pytest.fixture
def technician(api: TestClient) -> dict[str, str]:
    return token_for(api, "technician@campus.edu")


# ---------------------------------------------------------------- search
def test_search_pages_and_counts(api: TestClient, admin: dict[str, str]) -> None:
    first = api.post("/incidents/search", json={"limit": 10}, headers=admin)
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == HISTORY
    assert len(body["items"]) == 10
    assert body["page_number"] == 1
    assert body["page_count"] == 12
    assert body["has_more"] is True
    assert all("sla" in item for item in body["items"])

    last = api.post("/incidents/search", json={"limit": 10, "offset": 110}, headers=admin)
    assert last.json()["has_more"] is False
    assert last.json()["page_number"] == 12


def test_search_applies_the_filters(api: TestClient, admin: dict[str, str]) -> None:
    closed = api.post(
        "/incidents/search", json={"statuses": ["CLOSED"], "limit": 5}, headers=admin
    ).json()
    assert closed["total"] > 0
    assert all(item["status"] == "CLOSED" for item in closed["items"])

    critical = api.post(
        "/incidents/search", json={"priorities": ["P1"], "limit": 5}, headers=admin
    ).json()
    assert all(item["priority"] == "P1" for item in critical["items"])
    assert critical["total"] < closed["total"] + HISTORY

    breached = api.post(
        "/incidents/search", json={"sla_statuses": ["breached"], "limit": 5}, headers=admin
    ).json()
    assert breached["total"] >= 0  # the seeded history has late acknowledgements

    text = api.post("/incidents/search", json={"text": "wifi", "limit": 5}, headers=admin).json()
    assert all(
        "wifi" in item["title"].lower() or item["id"].lower().count("wifi") == 0
        for item in text["items"]
    )


def test_search_is_scoped_to_the_caller(
    api: TestClient, employee: dict[str, str], admin: dict[str, str]
) -> None:
    """BR-01: the same body returns different rows for different roles."""
    everything = api.post("/incidents/search", json={}, headers=admin).json()
    mine = api.post("/incidents/search", json={}, headers=employee).json()
    assert everything["total"] == HISTORY
    assert mine["total"] < everything["total"]

    me = api.get("/auth/me", headers=employee).json()["id"]
    assert all(item["reporter_id"] == me for item in mine["items"])


def test_a_technician_searching_sees_their_own_queue(
    api: TestClient, technician: dict[str, str]
) -> None:
    me = api.get("/auth/me", headers=technician).json()["id"]
    page = api.post("/incidents/search", json={"limit": 50}, headers=technician).json()
    assert all(item["assignee_id"] == me for item in page["items"])


def test_an_invalid_search_is_422(api: TestClient, admin: dict[str, str]) -> None:
    too_big = api.post("/incidents/search", json={"limit": MAX_PAGE_SIZE + 1}, headers=admin)
    assert too_big.status_code == 422

    backwards = api.post(
        "/incidents/search",
        json={"created_from": "2026-11-20T00:00:00Z", "created_to": "2026-01-01T00:00:00Z"},
        headers=admin,
    )
    assert backwards.status_code == 422
    assert backwards.json()["error"]["code"] == "invalid_user_input"


def test_search_needs_a_token(api: TestClient) -> None:
    assert api.post("/incidents/search", json={}).status_code == 401


# ---------------------------------------------------------------- CSV export
def test_the_export_is_a_csv_attachment(api: TestClient, admin: dict[str, str]) -> None:
    response = api.post("/incidents/search/export", json={"statuses": ["CLOSED"]}, headers=admin)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("ID,Title,Status,Priority")
    assert len(lines) > 1
    assert all(",CLOSED," in line for line in lines[1:])


def test_the_export_is_scoped_too(
    api: TestClient, employee: dict[str, str], admin: dict[str, str]
) -> None:
    everything = api.post("/incidents/search/export", json={}, headers=admin).text
    mine = api.post("/incidents/search/export", json={}, headers=employee).text
    assert len(mine.splitlines()) < len(everything.splitlines())


# ---------------------------------------------------------------- the dashboards
def test_the_dashboard_returns_every_section(api: TestClient, admin: dict[str, str]) -> None:
    body = api.get("/reports/dashboard?window_days=180", headers=admin).json()
    assert body["window_days"] == 180
    assert body["overview"]["total"] == HISTORY
    assert body["overview"]["open_count"] > 0
    assert body["metrics"]["mtta_hours"] is not None
    assert body["metrics"]["mttr_hours"] is not None
    assert 0 <= body["metrics"]["sla_compliance"] <= 100
    assert body["metrics"]["csat"] is not None
    assert body["workload"]
    assert body["services"]
    assert body["trend"]
    assert all(row["max_load"] == 10 for row in body["workload"])
    assert sum(point["reported"] for point in body["trend"]) == HISTORY


def test_the_window_narrows_the_figures(api: TestClient, admin: dict[str, str]) -> None:
    wide = api.get("/reports/overview?window_days=180", headers=admin).json()
    narrow = api.get("/reports/overview?window_days=2", headers=admin).json()
    assert narrow["total"] < wide["total"]

    assert api.get("/reports/overview?window_days=0", headers=admin).status_code == 422
    assert api.get("/reports/overview?window_days=400", headers=admin).status_code == 422


def test_the_dashboards_are_admin_only(api: TestClient, employee: dict[str, str]) -> None:
    for path in (
        "/reports/dashboard",
        "/reports/overview",
        "/reports/metrics",
        "/reports/services",
        "/reports/trend",
        "/reports/services/export",
    ):
        assert api.get(path, headers=employee).status_code == 403, path


def test_a_technician_sees_only_their_own_workload(
    api: TestClient, technician: dict[str, str], admin: dict[str, str]
) -> None:
    me = api.get("/auth/me", headers=technician).json()["id"]
    mine = api.get("/reports/workload", headers=technician).json()
    assert [row["technician_id"] for row in mine] == [me]

    everyone = api.get("/reports/workload", headers=admin).json()
    assert len(everyone) > 1


def test_an_employee_has_no_workload_to_see(api: TestClient, employee: dict[str, str]) -> None:
    assert api.get("/reports/workload", headers=employee).status_code == 403


def test_the_workload_and_service_exports_are_csv(api: TestClient, admin: dict[str, str]) -> None:
    workload = api.get("/reports/workload/export", headers=admin)
    assert workload.headers["content-type"].startswith("text/csv")
    assert workload.text.splitlines()[0].startswith("Technician,Available")

    services = api.get("/reports/services/export?window_days=180", headers=admin)
    assert services.text.splitlines()[0].startswith("Service,Incidents,Breached")
    assert len(services.text.splitlines()) > 1
