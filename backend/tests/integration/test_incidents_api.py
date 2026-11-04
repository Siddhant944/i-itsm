"""The incident endpoints over the real database (blueprint §4, §5, §7, §8).

One employee, one technician, one admin, and the workflows the demo will show. The app is the
production wiring except for the clock, the hasher and the mailer, which are fakes so lockouts,
SLA deadlines and emails are all exact.
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
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.sla import default_policies
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

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"
REPORTER, OTHER, TECH, LEAD, ADMIN = 1, 2, 3, 4, 5
WIFI, PORTAL = 1, 2
NETWORK, PAYMENTS = 1, 2


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
        _catalogue(uow)
        _people(uow)
        uow.commit()
    finally:
        uow.close()
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


def _catalogue(uow: SqlAlchemyUnitOfWork) -> None:
    uow.catalogue.save_skill(Skill(1, "networking"))
    uow.catalogue.save_category(
        Category(NETWORK, "Network", required_skill_id=1, keywords=("wifi", "network"))
    )
    uow.catalogue.save_category(
        Category(PAYMENTS, "Payments", keywords=("fee", "payment"), minimum_priority=Priority.P1)
    )
    uow.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=2))
    uow.catalogue.save_service(ITService(PORTAL, "Fee Payment Portal", criticality=3))
    uow.catalogue.save_service(ITService(3, "Retired Thing", criticality=1, active=False))
    uow.catalogue.save_policies(default_policies())
    uow.catalogue.save_team(Team(1, "Network Operations"))


def _people(uow: SqlAlchemyUnitOfWork) -> None:
    hasher = FakePasswordHasher()
    accounts = (
        (REPORTER, "devika@campus.edu", "Devika Rao", Role.EMPLOYEE, None),
        (OTHER, "other@campus.edu", "Other Person", Role.EMPLOYEE, None),
        (TECH, "arjun@campus.edu", "Arjun Menon", Role.TECHNICIAN, 1),
        (LEAD, "priya@campus.edu", "Priya Nair", Role.TEAM_LEAD, 1),
        (ADMIN, "rahul@campus.edu", "Rahul Verma", Role.ADMINISTRATOR, None),
    )
    for user_id, email, name, role, team_id in accounts:
        extra: dict[str, Any] = {}
        if UserFactory.is_support_role(role):
            extra = {"skills": SkillSet({"networking"}), "experience_level": 2, "team_id": team_id}
        uow.users.add(
            UserFactory.create(role, user_id=user_id, email=email, full_name=name, **extra)
        )
        credentials = uow.credentials.get(user_id)
        credentials.set_password_hash(hasher.hash(PASSWORD))
        uow.credentials.save(credentials)
    team = uow.catalogue.get_team(1)
    team.add_member(TECH)
    team.add_member(LEAD)
    team.set_lead(LEAD)
    uow.catalogue.save_team(team)


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
def reporter(api: TestClient) -> dict[str, str]:
    return token_for(api, "devika@campus.edu")


@pytest.fixture
def technician(api: TestClient) -> dict[str, str]:
    return token_for(api, "arjun@campus.edu")


@pytest.fixture
def lead(api: TestClient) -> dict[str, str]:
    return token_for(api, "priya@campus.edu")


@pytest.fixture
def admin(api: TestClient) -> dict[str, str]:
    return token_for(api, "rahul@campus.edu")


def report(api: TestClient, headers: dict[str, str], **overrides: object) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Wi-Fi keeps dropping",
        "description": "The wifi network drops every few minutes in the library",
        "service_id": WIFI,
        "impact": 2,
        "urgency": 2,
    }
    body.update(overrides)
    response = api.post("/incidents", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


# ---------------------------------------------------------------- reporting
def test_reporting_returns_the_incident_its_sla_and_what_the_system_decided(
    api: TestClient, reporter: dict[str, str]
) -> None:
    body = report(api, reporter)
    incident = body["incident"]
    assert incident["id"] == "INC-2026-0001"
    assert incident["status"] == S.ASSIGNED.value
    assert incident["category_id"] == NETWORK
    assert incident["priority"] == Priority.P3.value
    assert incident["sla"]["response_status"] == "on_track"
    assert incident["sla"]["response_deadline"]
    assert body["suggestion"]["source"] == "rules"
    assert body["suggestion"]["confidence"] > 0
    assert body["assignment"]["reasons"]
    assert body["needs_triage"] is False


def test_the_while_typing_suggestion_is_advice_only(
    api: TestClient, reporter: dict[str, str]
) -> None:
    response = api.post(
        "/incidents/classify",
        json={"text": "the fee payment portal rejects my payment"},
        headers=reporter,
    )
    assert response.status_code == 200
    assert response.json()["category_id"] == PAYMENTS
    # Nothing was created by asking.
    assert api.get("/incidents/mine", headers=reporter).json() == []


def test_an_unclassifiable_report_is_flagged_for_triage(
    api: TestClient, reporter: dict[str, str]
) -> None:
    body = report(
        api, reporter, title="Something is odd", description="I cannot describe it any better"
    )
    assert body["needs_triage"] is True
    assert body["incident"]["status"] == S.NEW.value
    assert body["assignment"] is None


def test_a_retired_service_is_404_and_bad_input_is_422(
    api: TestClient, reporter: dict[str, str]
) -> None:
    retired = api.post(
        "/incidents",
        json={
            "title": "Anything",
            "description": "Anything at all",
            "service_id": 3,
            "impact": 1,
            "urgency": 1,
        },
        headers=reporter,
    )
    assert retired.status_code == 404
    assert retired.json()["error"]["code"] == "service_not_found"

    invalid = api.post(
        "/incidents",
        json={"title": "", "description": "x", "service_id": WIFI, "impact": 9, "urgency": 1},
        headers=reporter,
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["details"]["fields"]) == {"title", "impact"}


def test_reporting_needs_a_token(api: TestClient) -> None:
    assert api.post("/incidents", json={}).status_code == 401


# ---------------------------------------------------------------- BR-01
def test_BR01_another_employee_gets_403_not_the_incident(
    api: TestClient, reporter: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    other = token_for(api, "other@campus.edu")
    refused = api.get(f"/incidents/{incident_id}", headers=other)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "unauthorized_operation"
    assert api.get(f"/incidents/{incident_id}", headers=reporter).status_code == 200


def test_BR01_mine_lists_only_my_own(api: TestClient, reporter: dict[str, str]) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    other = token_for(api, "other@campus.edu")
    report(api, other, title="Fee payment failed", description="My fee payment failed")

    mine = api.get("/incidents/mine", headers=reporter).json()
    assert [i["id"] for i in mine] == [incident_id]
    assert len(api.get("/incidents/mine", headers=other).json()) == 1


def test_an_unknown_incident_is_404(api: TestClient, admin: dict[str, str]) -> None:
    missing = api.get("/incidents/INC-2026-9999", headers=admin)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "incident_not_found"


# ---------------------------------------------------------------- the technician's workflow
def test_the_technician_queue_and_the_whole_lifecycle(
    api: TestClient, reporter: dict[str, str], clock: FakeClock
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    assignee_email = {TECH: "arjun@campus.edu", LEAD: "priya@campus.edu"}[
        api.get(f"/incidents/{incident_id}", headers=reporter).json()["assignee_id"]
    ]
    worker = token_for(api, assignee_email)

    queue = api.get("/incidents/queue", headers=worker).json()
    assert [i["id"] for i in queue] == [incident_id]

    clock.advance(timedelta(minutes=5))
    acknowledged = api.post(f"/incidents/{incident_id}/acknowledge", headers=worker)
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == S.ACKNOWLEDGED.value
    assert acknowledged.json()["sla"]["responded_at"] is not None

    assert api.post(f"/incidents/{incident_id}/start", headers=worker).status_code == 200
    noted = api.post(
        f"/incidents/{incident_id}/notes",
        json={"text": "Rebooted the access point"},
        headers=worker,
    )
    assert [n["text"] for n in noted.json()["notes"]] == ["Rebooted the access point"]

    held = api.post(
        f"/incidents/{incident_id}/request-information",
        json={"text": "Which floor are you on?"},
        headers=worker,
    )
    assert held.json()["status"] == S.ON_HOLD.value
    assert held.json()["sla"]["paused"] is True

    clock.advance(timedelta(hours=1))
    # §8: access tokens are short-lived, so an hour later the reporter signs in again.
    assert api.get("/incidents/mine", headers=reporter).status_code == 401
    reporter = token_for(api, "devika@campus.edu")
    answered = api.post(
        f"/incidents/{incident_id}/information",
        json={"text": "First floor, near the help desk"},
        headers=reporter,
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == S.IN_PROGRESS.value
    assert answered.json()["sla"]["paused"] is False

    worker = token_for(api, assignee_email)  # the technician's token has expired too
    resolved = api.post(
        f"/incidents/{incident_id}/resolve",
        json={"summary": "Replaced the access point"},
        headers=worker,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == S.RESOLVED.value
    assert resolved.json()["resolution"]["summary"] == "Replaced the access point"

    verified = api.post(
        f"/incidents/{incident_id}/verify",
        json={"rating": 5, "comment": "Quick work"},
        headers=reporter,
    )
    assert verified.json()["status"] == S.VERIFIED.value
    assert verified.json()["feedback"]["rating"] == 5

    closed = api.post(f"/incidents/{incident_id}/close", headers=worker)
    assert closed.json()["status"] == S.CLOSED.value


def test_BR02_a_stranger_technician_is_403_and_an_employee_has_no_queue(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    assignee = api.get(f"/incidents/{incident_id}", headers=admin).json()["assignee_id"]

    # Whoever is not the assignee and not in a position to act is refused.
    if assignee != TECH:
        stranger = token_for(api, "arjun@campus.edu")
        assert (
            api.post(f"/incidents/{incident_id}/acknowledge", headers=stranger).status_code == 403
        )
    assert api.post(f"/incidents/{incident_id}/acknowledge", headers=reporter).status_code == 403
    assert api.get("/incidents/queue", headers=reporter).status_code == 403


def test_resolving_too_early_is_409(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    """The lifecycle is checked first: an assigned incident cannot jump to resolved (§4)."""
    incident_id = report(api, reporter)["incident"]["id"]
    too_early = api.post(
        f"/incidents/{incident_id}/resolve", json={"summary": "Done"}, headers=admin
    )
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == "invalid_state_transition"
    assert too_early.json()["error"]["details"]["from_state"] == S.ASSIGNED.value
    assert too_early.json()["error"]["details"]["to_state"] == S.RESOLVED.value


def test_BR04_resolving_without_a_summary_is_422(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    api.post(f"/incidents/{incident_id}/acknowledge", headers=admin)
    api.post(f"/incidents/{incident_id}/start", headers=admin)

    empty = api.post(f"/incidents/{incident_id}/resolve", json={"summary": ""}, headers=admin)
    assert empty.status_code == 422
    blank = api.post(f"/incidents/{incident_id}/resolve", json={"summary": "   "}, headers=admin)
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "invalid_incident"

    assert api.get(f"/incidents/{incident_id}", headers=admin).json()["status"] == (
        S.IN_PROGRESS.value
    )


def test_BR03_only_the_reporter_verifies_or_rejects(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    api.post(f"/incidents/{incident_id}/acknowledge", headers=admin)
    api.post(f"/incidents/{incident_id}/start", headers=admin)
    api.post(f"/incidents/{incident_id}/resolve", json={"summary": "Done"}, headers=admin)

    assert (
        api.post(f"/incidents/{incident_id}/verify", json={"rating": 5}, headers=admin).status_code
        == 403
    )
    rejected = api.post(
        f"/incidents/{incident_id}/reject", json={"reason": "It came back"}, headers=reporter
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == S.IN_PROGRESS.value
    assert rejected.json()["reopen_count"] == 1
    assert rejected.json()["resolution"] is None


def test_a_rating_outside_one_to_five_is_422(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    api.post(f"/incidents/{incident_id}/acknowledge", headers=admin)
    api.post(f"/incidents/{incident_id}/start", headers=admin)
    api.post(f"/incidents/{incident_id}/resolve", json={"summary": "Done"}, headers=admin)
    assert (
        api.post(
            f"/incidents/{incident_id}/verify", json={"rating": 9}, headers=reporter
        ).status_code
        == 422
    )


# ---------------------------------------------------------------- overrides
def test_BR05_an_override_needs_a_reason_and_retargets_the_sla(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    before = api.get(f"/incidents/{incident_id}", headers=admin).json()["sla"]

    without = api.post(f"/incidents/{incident_id}/priority", json={"priority": "P1"}, headers=admin)
    assert without.status_code == 422

    overridden = api.post(
        f"/incidents/{incident_id}/priority",
        json={"priority": "P1", "reason": "Exam tomorrow"},
        headers=admin,
    )
    assert overridden.status_code == 200
    assert overridden.json()["priority"] == Priority.P1.value
    assert overridden.json()["priority_overridden"] is True
    assert overridden.json()["sla"]["response_deadline"] < before["response_deadline"]


def test_an_employee_may_not_override_anything(api: TestClient, reporter: dict[str, str]) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    assert (
        api.post(
            f"/incidents/{incident_id}/priority",
            json={"priority": "P1", "reason": "mine"},
            headers=reporter,
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/incidents/{incident_id}/category", json={"category_id": PAYMENTS}, headers=reporter
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/incidents/{incident_id}/reassign", json={"technician_id": TECH}, headers=reporter
        ).status_code
        == 403
    )


def test_BR06_reassignment_and_its_advice(
    api: TestClient, reporter: dict[str, str], lead: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    advice = api.get(f"/incidents/{incident_id}/assignment-advice", headers=lead)
    assert advice.status_code == 200
    assert advice.json()["strategy"] == "smart"
    assert advice.json()["ranked"][0]["reasons"]

    moved = api.post(
        f"/incidents/{incident_id}/reassign", json={"technician_id": TECH}, headers=lead
    )
    assert moved.status_code == 200
    assert moved.json()["assignee_id"] == TECH


def test_cancelling_and_duplicates(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    first = report(api, reporter)["incident"]["id"]
    second = report(api, reporter, title="Wi-Fi still dropping")["incident"]["id"]

    missing_parent = api.post(
        f"/incidents/{second}/cancel",
        json={"reason": "duplicate"},
        headers=admin,
    )
    assert missing_parent.status_code == 422  # a duplicate must name its parent

    linked = api.post(
        f"/incidents/{second}/cancel",
        json={"reason": "duplicate", "duplicate_of": first},
        headers=admin,
    )
    assert linked.status_code == 200
    assert linked.json()["status"] == S.CANCELLED.value
    assert linked.json()["parent_id"] == first

    withdrawn = api.post(f"/incidents/{first}/cancel", json={}, headers=reporter)
    assert withdrawn.json()["cancel_reason"] == "withdrawn"


# ---------------------------------------------------------------- the bell and the catalogue
def test_the_bell_shows_the_reporters_own_notifications(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    report(api, reporter)
    bell = api.get("/notifications", headers=reporter).json()
    assert bell["unread"] >= 2
    assert all(n["channel"] == "in_app" for n in bell["latest"])
    assert any("INC-2026-0001" in n["subject"] for n in bell["latest"])

    first = bell["latest"][0]["id"]
    read = api.post(f"/notifications/{first}/read", headers=reporter)
    assert read.status_code == 200
    assert read.json()["read_at"] is not None
    assert api.get("/notifications", headers=reporter).json()["unread"] == bell["unread"] - 1

    assert api.post(f"/notifications/{first}/read", headers=admin).status_code == 403


def test_the_catalogue_gives_the_report_form_what_it_needs(
    api: TestClient, reporter: dict[str, str]
) -> None:
    services = api.get("/catalogue/services", headers=reporter).json()
    assert {s["name"] for s in services} == {"Campus Wi-Fi", "Fee Payment Portal"}  # not retired
    assert all("sla_tier" in s for s in services)

    categories = api.get("/catalogue/categories", headers=reporter).json()
    assert {c["name"] for c in categories} == {"Network", "Payments"}
    assert any(c["minimum_priority"] == Priority.P1.value for c in categories)

    assert api.get("/catalogue/skills", headers=reporter).json()
    assert api.get("/catalogue/teams", headers=reporter).json()[0]["lead_id"] == LEAD
    assert api.get("/catalogue/services").status_code == 401


# ---------------------------------------------------------------- §8: no leaks
def test_no_response_ever_contains_a_stack_trace_or_a_hash(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    incident_id = report(api, reporter)["incident"]["id"]
    probes = [
        api.get("/incidents/INC-2026-9999", headers=admin),
        api.post(f"/incidents/{incident_id}/resolve", json={"summary": "x"}, headers=admin),
        api.get(f"/incidents/{incident_id}", headers=token_for(api, "other@campus.edu")),
        api.post("/auth/login", json={"email": "devika@campus.edu", "password": "wrong"}),
        api.get("/auth/me", headers={"Authorization": "Bearer nonsense"}),
    ]
    for response in probes:
        assert response.status_code >= 400
        assert "Traceback" not in response.text
        assert "argon2" not in response.text.lower()
        assert "sqlalchemy" not in response.text.lower()
        assert set(response.json()["error"]) <= {"code", "message", "details"}
