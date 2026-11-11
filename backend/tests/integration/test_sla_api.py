"""The SLA monitor through the API, on a clock the test moves (blueprint §5.2, D-009).

This is the demo in miniature: report a P1, move time forward, and watch the warning, the
breach and the escalation appear without waiting five minutes.
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
from app.core.config import AppEnv, ClockMode, Settings
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.permissions import Role
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.sla import ViolationKind, default_policies
from app.domain.states import IncidentStatus as S
from app.domain.users import UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.services.auth_service import AuthPolicy

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"
REPORTER, TECH, LEAD, ADMIN, MANAGER = 1, 2, 3, 4, 5
PORTAL = 1


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
        uow.catalogue.save_skill(Skill(1, "web"))
        uow.catalogue.save_category(
            Category(1, "Payments", required_skill_id=1, keywords=("payment", "fee"))
        )
        uow.catalogue.save_service(ITService(PORTAL, "Fee Payment Portal", criticality=3))
        uow.catalogue.save_policies(default_policies())
        uow.catalogue.save_team(Team(1, "Systems and Database"))
        hasher = FakePasswordHasher()
        for user_id, role, name in (
            (REPORTER, Role.EMPLOYEE, "Devika Rao"),
            (TECH, Role.TECHNICIAN, "Arjun Menon"),
            (LEAD, Role.TEAM_LEAD, "Priya Nair"),
            (ADMIN, Role.ADMINISTRATOR, "Rahul Verma"),
            (MANAGER, Role.IT_MANAGER, "Sunita Iyer"),
        ):
            support = UserFactory.is_support_role(role)
            uow.users.add(
                UserFactory.create(
                    role,
                    user_id=user_id,
                    email=f"u{user_id}@campus.edu",
                    full_name=name,
                    skills=SkillSet({"web"}) if support else None,
                    experience_level=2 if support else None,
                    team_id=1 if support else None,
                )
            )
            credentials = uow.credentials.get(user_id)
            credentials.set_password_hash(hasher.hash(PASSWORD))
            uow.credentials.save(credentials)
        team = uow.catalogue.get_team(1)
        team.add_member(TECH)
        team.add_member(LEAD)
        team.set_lead(LEAD)
        uow.catalogue.save_team(team)
        uow.commit()
    finally:
        uow.close()
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    """A test environment with a controllable clock and no background scheduler (D-009)."""
    return Settings(
        app_env=AppEnv.TEST,
        database_url=database_url,
        clock_mode=ClockMode.FAKE,
        sla_tick_seconds=0,
        _env_file=None,
    )


@pytest.fixture
def api(engine: Engine, clock: FakeClock, settings: Settings) -> Iterator[TestClient]:
    from app.main import create_app

    app: FastAPI = create_app(settings)
    sessions = make_session_factory(engine)
    app.state.services = Services(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(sessions, clock),
        clock=clock,
        hasher=FakePasswordHasher(),
        tokens=JwtTokenService("a-test-secret-of-adequate-length", timedelta(hours=8)),
        policy=AuthPolicy(),
        email=ConsoleEmailSender(),
        advisor=RuleBasedAdvisor(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def token_for(api: TestClient, user_id: int) -> dict[str, str]:
    response = api.post(
        "/auth/login", json={"email": f"u{user_id}@campus.edu", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def reporter(api: TestClient) -> dict[str, str]:
    return token_for(api, REPORTER)


@pytest.fixture
def admin(api: TestClient) -> dict[str, str]:
    return token_for(api, ADMIN)


def report_p1(api: TestClient, reporter: dict[str, str]) -> dict[str, Any]:
    response = api.post(
        "/incidents",
        json={
            "title": "Fee payment portal is down",
            "description": "Every payment is rejected right now",
            "service_id": PORTAL,
            "impact": 3,
            "urgency": 3,
        },
        headers=reporter,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["incident"]["priority"] == "P1"
    return body


# ---------------------------------------------------------------- the clock (D-009)
def test_the_clock_can_be_read_and_moved_in_the_test_environment(
    api: TestClient, admin: dict[str, str]
) -> None:
    read = api.get("/dev/clock", headers=admin)
    assert read.status_code == 200
    assert read.json()["controllable"] is True
    assert read.json()["mode"] == "FakeClock"
    assert "IST" in read.json()["now_ist"]

    moved = api.post("/dev/clock/advance", json={"seconds": 600}, headers=admin)
    assert moved.status_code == 200
    assert moved.json()["now"] > read.json()["now"]


def test_the_clock_cannot_be_moved_backwards_or_absurdly_far(
    api: TestClient, admin: dict[str, str]
) -> None:
    assert api.post("/dev/clock/advance", json={"seconds": 0}, headers=admin).status_code == 422
    assert api.post("/dev/clock/advance", json={"seconds": -60}, headers=admin).status_code == 422
    assert api.post("/dev/clock/advance", json={"seconds": 10**9}, headers=admin).status_code == 422


def test_the_clock_endpoints_need_a_token(api: TestClient) -> None:
    assert api.get("/dev/clock").status_code == 401
    assert api.post("/dev/clock/advance", json={"seconds": 60}).status_code == 401


def test_the_clock_endpoints_do_not_exist_in_production(database_url: str) -> None:
    """D-009: controlling time is for the test and demo environments only."""
    from app.main import create_app

    production = Settings(
        app_env=AppEnv.PROD,
        database_url=database_url,
        jwt_secret="a-production-secret-of-more-than-32-characters",
        sla_tick_seconds=0,
        _env_file=None,
    )
    paths = create_app(production).openapi()["paths"]
    assert "/dev/clock" not in paths
    assert "/dev/clock/advance" not in paths
    assert "/incidents" in paths


def test_production_refuses_a_fake_clock(database_url: str) -> None:
    with pytest.raises(ValueError, match="never for prod"):
        Settings(
            app_env=AppEnv.PROD,
            database_url=database_url,
            clock_mode=ClockMode.FAKE,
            jwt_secret="a-production-secret-of-more-than-32-characters",
            _env_file=None,
        )


# ---------------------------------------------------------------- the demo in miniature
def test_BR08_a_p1_warns_breaches_and_escalates_as_time_moves(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    """§5.2, §5.5: 75 % of five minutes warns, past five breaches, and it moves up a level."""
    incident_id = report_p1(api, reporter)["incident"]["id"]

    quiet = api.post("/sla/tick", headers=admin).json()
    assert quiet == {"warned": 0, "breached": 0, "escalated": [], "auto_closed": []}

    warning = api.post("/dev/clock/advance", json={"seconds": 230}, headers=admin).json()
    assert warning["warned"] == 1
    assert warning["breached"] == 0
    assert warning["escalated"] == []

    breach = api.post("/dev/clock/advance", json={"seconds": 120}, headers=admin).json()
    assert breach["breached"] >= 1
    assert breach["escalated"] == [incident_id]

    escalated = api.get(f"/incidents/{incident_id}", headers=admin).json()
    assert escalated["escalation_level"] == 1
    assert escalated["assignee_id"] == LEAD
    assert escalated["sla"]["response_status"] == "breached"


def test_the_violations_screen_shows_what_the_monitor_found(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report_p1(api, reporter)["incident"]["id"]
    api.post("/dev/clock/advance", json={"seconds": 400}, headers=admin)

    listed = api.get("/sla/violations", headers=admin)
    assert listed.status_code == 200
    kinds = {row["kind"] for row in listed.json()}
    assert ViolationKind.RESPONSE_BREACH.value in kinds
    assert all(row["incident_id"] == incident_id for row in listed.json())
    assert any(row["is_breach"] for row in listed.json())

    one = api.get(f"/sla/violations/{incident_id}", headers=admin).json()
    assert len(one) == len(listed.json())
    assert [row["detected_at"] for row in one] == sorted(row["detected_at"] for row in one)


def test_ticking_twice_reports_nothing_the_second_time(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    report_p1(api, reporter)
    api.post("/dev/clock/advance", json={"seconds": 400}, headers=admin)
    before = len(api.get("/sla/violations", headers=admin).json())

    again = api.post("/sla/tick", headers=admin).json()
    assert again["warned"] == 0
    assert again["breached"] == 0
    assert len(api.get("/sla/violations", headers=admin).json()) == before


def test_BR03_autoclose_through_the_api(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report_p1(api, reporter)["incident"]["id"]
    api.post(f"/incidents/{incident_id}/acknowledge", headers=admin)
    api.post(f"/incidents/{incident_id}/start", headers=admin)
    resolved = api.post(
        f"/incidents/{incident_id}/resolve",
        json={"summary": "Restarted the gateway"},
        headers=admin,
    )
    assert resolved.json()["status"] == S.RESOLVED.value

    # Just short of 72 hours: still waiting for the reporter.
    almost = api.post("/dev/clock/advance", json={"seconds": 72 * 3600 - 60}, headers=admin).json()
    assert almost["auto_closed"] == []
    # Three days of clock time have passed, so the access token has expired (§8).
    admin = token_for(api, ADMIN)
    assert api.get(f"/incidents/{incident_id}", headers=admin).json()["status"] == S.RESOLVED.value

    passed = api.post("/dev/clock/advance", json={"seconds": 120}, headers=admin).json()
    assert passed["auto_closed"] == [incident_id]
    closed = api.get(f"/incidents/{incident_id}", headers=admin).json()
    assert closed["status"] == S.CLOSED.value
    assert closed["closed_at"] is not None


def test_the_violations_screen_and_the_tick_are_not_for_everyone(
    api: TestClient, reporter: dict[str, str]
) -> None:
    assert api.get("/sla/violations", headers=reporter).status_code == 403
    assert api.post("/sla/tick", headers=reporter).status_code == 403
    assert api.get("/sla/violations").status_code == 401


def test_the_monitor_notifies_the_assignee_and_the_lead(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    """§5.4: an SLA warning goes to the assignee and the Team Lead."""
    report_p1(api, reporter)
    api.post("/dev/clock/advance", json={"seconds": 230}, headers=admin)

    lead_bell = api.get("/notifications", headers=token_for(api, LEAD)).json()
    assert any("close to its SLA" in n["subject"] for n in lead_bell["latest"])
