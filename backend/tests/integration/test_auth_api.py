"""The auth endpoints end to end, over the real database (blueprint §8).

The app is built with a FakeClock and the fast hasher so lockouts and token expiry can be
driven exactly; everything else — routing, Pydantic validation, the error handlers, the
session per request — is the production wiring.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.adapters.smtp_email import ConsoleEmailSender
from app.api.deps import Services
from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.audit import AuditAction
from app.domain.catalogue import Team
from app.domain.credentials import MAX_FAILED_ATTEMPTS
from app.domain.permissions import Permission, Role
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.users import UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import AuditRecordRow, Base
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.services.auth_service import AuthPolicy

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    made = make_engine(database_url)
    Base.metadata.drop_all(made)
    create_schema(made)
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def app(engine: Engine, clock: FakeClock, settings: Any) -> FastAPI:
    from app.main import create_app

    built = create_app(settings)
    sessions = make_session_factory(engine)
    built.state.services = Services(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(sessions, clock),
        clock=clock,
        hasher=FakePasswordHasher(),
        tokens=JwtTokenService("a-test-secret-of-adequate-length", timedelta(minutes=30)),
        policy=AuthPolicy(),
        email=ConsoleEmailSender(),
        advisor=RuleBasedAdvisor(),
    )
    return built


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def register(api: TestClient, email: str = "devika@campus.edu") -> dict[str, Any]:
    response = api.post(
        "/auth/register",
        json={"email": email, "full_name": "Devika Rao", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- registration
def test_registering_returns_a_token_and_the_portal(api: TestClient) -> None:
    body = register(api)
    assert body["role"] == Role.EMPLOYEE.value
    assert body["portal"] == "employee"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert body["access_token"]


def test_a_duplicate_registration_is_422_with_the_field(api: TestClient) -> None:
    register(api)
    response = api.post(
        "/auth/register",
        json={"email": "devika@campus.edu", "full_name": "Someone", "password": PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_user_input"
    assert "email" in response.json()["error"]["details"]["field_errors"]


def test_a_malformed_registration_is_422_from_pydantic(api: TestClient) -> None:
    response = api.post(
        "/auth/register", json={"email": "not-an-email", "full_name": "", "password": "short"}
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert set(fields) == {"email", "full_name", "password"}


def test_the_role_cannot_be_chosen_at_registration(api: TestClient) -> None:
    """An extra field must not promote the new account (blueprint §8)."""
    response = api.post(
        "/auth/register",
        json={
            "email": "sneaky@campus.edu",
            "full_name": "Sneaky Person",
            "password": PASSWORD,
            "role": "administrator",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == Role.EMPLOYEE.value


# ---------------------------------------------------------------- sign-in
def test_signing_in_and_reading_me(api: TestClient) -> None:
    register(api)
    token = api.post(
        "/auth/login", json={"email": "DEVIKA@campus.edu", "password": PASSWORD}
    ).json()["access_token"]

    response = api.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "devika@campus.edu"
    assert body["role"] == Role.EMPLOYEE.value
    assert body["portal"] == "employee"
    assert body["escalation_level"] is None
    assert body["technician"] is None
    assert Permission.INCIDENT_CREATE.value in body["permissions"]
    assert Permission.INCIDENT_VIEW_ALL.value not in body["permissions"]


def test_a_wrong_password_is_401_without_a_stack_trace(api: TestClient) -> None:
    register(api)
    response = api.post(
        "/auth/login", json={"email": "devika@campus.edu", "password": "wrong password"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "invalid_login"
    assert "Traceback" not in response.text


def test_me_without_a_token_is_401(api: TestClient) -> None:
    assert api.get("/auth/me").status_code == 401
    assert api.get("/auth/me", headers=auth_header("not-a-token")).status_code == 401
    assert api.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_an_expired_token_is_401(api: TestClient, clock: FakeClock) -> None:
    token = register(api)["access_token"]
    assert api.get("/auth/me", headers=auth_header(token)).status_code == 200
    clock.advance(timedelta(minutes=30))
    assert api.get("/auth/me", headers=auth_header(token)).status_code == 401


# ---------------------------------------------------------------- lockout
def test_the_fifth_failure_locks_the_account_and_time_unlocks_it(
    api: TestClient, clock: FakeClock
) -> None:
    register(api)
    wrong = {"email": "devika@campus.edu", "password": "wrong password"}
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert api.post("/auth/login", json=wrong).status_code == 401

    locked = api.post("/auth/login", json=wrong)
    assert locked.status_code == 401
    assert "Try again in 15 minute" in locked.json()["error"]["message"]

    right = {"email": "devika@campus.edu", "password": PASSWORD}
    assert api.post("/auth/login", json=right).status_code == 401
    clock.advance(timedelta(minutes=15))
    assert api.post("/auth/login", json=right).status_code == 200


# ---------------------------------------------------------------- audit
def test_registrations_and_sign_ins_are_audited(api: TestClient, engine: Engine) -> None:
    register(api)
    api.post("/auth/login", json={"email": "devika@campus.edu", "password": PASSWORD})
    api.post("/auth/login", json={"email": "devika@campus.edu", "password": "wrong password"})

    with make_session_factory(engine)() as session:
        actions = [
            row.action
            for row in session.scalars(select(AuditRecordRow).order_by(AuditRecordRow.id)).all()
        ]
    assert AuditAction.USER_REGISTERED.value in actions
    assert AuditAction.LOGIN_SUCCEEDED.value in actions
    assert AuditAction.LOGIN_FAILED.value in actions


def test_a_failed_sign_in_is_still_recorded_after_the_response(
    api: TestClient, engine: Engine
) -> None:
    """The counters and the audit record must be committed even though the request failed."""
    user_id = register(api)["user_id"]
    api.post("/auth/login", json={"email": "devika@campus.edu", "password": "wrong password"})

    uow = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        assert uow.credentials.get(user_id).failed_attempts == 1
        assert uow.audit.count() > 0
    finally:
        uow.close()


def test_a_technician_sees_their_profile_and_their_portal(api: TestClient, engine: Engine) -> None:
    """A seeded staff account signs in once an admin or the seed sets its password."""
    uow = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        uow.catalogue.save_team(Team(1, "Network Operations"))
        uow.users.add(
            UserFactory.create(
                Role.TEAM_LEAD,
                user_id=40,
                email="lead@campus.edu",
                full_name="Priya Nair",
                skills=SkillSet({"networking", "database"}),
                experience_level=3,
                team_id=1,
            )
        )
        credentials = uow.credentials.get(40)
        credentials.set_password_hash(FakePasswordHasher().hash(PASSWORD))
        uow.credentials.save(credentials)
        uow.commit()
    finally:
        uow.close()

    token = api.post("/auth/login", json={"email": "lead@campus.edu", "password": PASSWORD}).json()[
        "access_token"
    ]
    body = api.get("/auth/me", headers=auth_header(token)).json()

    assert body["role"] == Role.TEAM_LEAD.value
    assert body["portal"] == "technician"
    assert body["escalation_level"] == 1
    assert body["technician"] == {
        "skills": ["database", "networking"],
        "experience_level": 3,
        "available": True,
        "team_id": 1,
    }
    assert Permission.INCIDENT_VIEW_TEAM.value in body["permissions"]


# ---------------------------------------------------------------- documentation
def test_the_openapi_document_describes_the_new_routes(api: TestClient) -> None:
    """The typed frontend client is generated from this document."""
    document = api.get("/openapi.json").json()
    assert "/auth/register" in document["paths"]
    assert "/auth/login" in document["paths"]
    assert "/auth/me" in document["paths"]
    assert document["paths"]["/auth/me"]["get"]["security"]
