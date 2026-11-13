"""The incident endpoints over the real database (blueprint §4, §5, §7, §8).

One employee, one technician, one admin, and the workflows the demo will show. The app is the
production wiring except for the clock, the hasher and the mailer, which are fakes so lockouts,
SLA deadlines and emails are all exact.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from starlette.websockets import WebSocketDisconnect

from app.adapters.smtp_email import ConsoleEmailSender
from app.api.deps import Services
from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.permissions import Role
from app.domain.ports import IdentityVerifier, VerifiedIdentity
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


def test_BR01_every_refusal_is_on_the_audit_trail(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    """§8: a 403 is audited, though the request that caused it rolls back (issue #8).

    Both kinds: a role without the permission, and a user who does not own the incident.
    """
    incident_id = report(api, reporter)["incident"]["id"]
    other = token_for(api, "other@campus.edu")
    assert api.get("/audit", headers=reporter).status_code == 403  # the role refuses
    assert api.get(f"/incidents/{incident_id}", headers=other).status_code == 403  # ownership

    page = api.get("/audit", params={"limit": 100}, headers=admin).json()
    refused = [r for r in page["items"] if r["action"] == "authorization.refused"]
    assert len(refused) == 2
    assert {r["incident_id"] for r in refused} == {None, incident_id}
    assert api.post("/audit/verify", headers=admin).json()["intact"] is True


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
    second = report(
        api, reporter, title="Projector is dim", description="Lecture hall F-105, yellow tint"
    )["incident"]["id"]

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

    # Another report now follows the first, so it cannot simply be withdrawn (P4 review).
    refused = api.post(f"/incidents/{first}/cancel", json={}, headers=reporter)
    assert refused.status_code == 422

    third = report(api, reporter, title="Printer out of toner", description="Admin office printer")[
        "incident"
    ]["id"]
    withdrawn = api.post(f"/incidents/{third}/cancel", json={}, headers=reporter)
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


# ---------------------------------------------------------------- duplicates (§6.2, BR-09)
PORTAL_DOWN = {
    "title": "Fee portal down",
    "description": "The fee payment portal shows error 503 when I try to pay",
    "service_id": PORTAL,
}


def test_BR09_the_form_is_shown_a_similar_open_incident_and_nothing_more_than_its_title(
    api: TestClient, reporter: dict[str, str], clock: FakeClock
) -> None:
    existing = report(api, reporter, **PORTAL_DOWN)["incident"]
    clock.advance(timedelta(minutes=5))
    other = token_for(api, "other@campus.edu")

    hint = api.post(
        "/incidents/similar",
        json={"title": "Fee payment portal error 503", "service_id": PORTAL},
        headers=other,
    )
    assert hint.status_code == 200, hint.text
    assert hint.json()["provider"] == "tfidf"
    (candidate,) = hint.json()["candidates"]
    # BR-01: enough to recognise and follow it; not its description, reporter or notes.
    assert set(candidate) == {"id", "title", "status", "created_at", "score", "reasons"}
    assert candidate["id"] == existing["id"]
    assert candidate["score"] >= 0.49
    assert "same service" in candidate["reasons"]
    assert api.get(f"/incidents/{existing['id']}", headers=other).status_code == 403

    unrelated = api.post("/incidents/similar", json={"title": "Projector is dim"}, headers=other)
    assert unrelated.json()["candidates"] == []
    assert api.post("/incidents/similar", json={"title": ""}, headers=other).status_code == 422


def test_BR09_a_repeat_by_the_same_reporter_is_409_with_a_link_to_the_first(
    api: TestClient, reporter: dict[str, str], clock: FakeClock
) -> None:
    first = report(api, reporter, **PORTAL_DOWN)["incident"]["id"]
    clock.advance(timedelta(minutes=10))
    body = {**PORTAL_DOWN, "impact": 2, "urgency": 2}

    repeat = api.post("/incidents", json=body, headers=reporter)
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "duplicate_incident"
    assert repeat.json()["error"]["details"] == {"existing_incident_id": first}
    assert len(api.get("/incidents/mine", headers=reporter).json()) == 1

    clock.advance(timedelta(minutes=21))  # 31 minutes after the first
    signed_in_again = token_for(api, "devika@campus.edu")  # the 30-minute token has expired
    later = api.post("/incidents", json=body, headers=signed_in_again)
    assert later.status_code == 201
    assert [c["id"] for c in later.json()["possible_duplicates"]] == [first]


def test_BR09_following_a_suggested_incident_links_the_report_to_it(
    api: TestClient, reporter: dict[str, str], technician: dict[str, str], clock: FakeClock
) -> None:
    parent = report(api, reporter, **PORTAL_DOWN)["incident"]["id"]
    clock.advance(timedelta(minutes=5))
    other = token_for(api, "other@campus.edu")
    body = {
        "title": "Fee payment portal error 503",
        "description": "Cannot pay my fees",
        "service_id": PORTAL,
        "impact": 2,
        "urgency": 2,
    }

    not_suggested = api.post("/incidents", json={**body, "follow": "INC-2026-9999"}, headers=other)
    assert not_suggested.status_code == 422

    followed = api.post("/incidents", json={**body, "follow": parent}, headers=other)
    assert followed.status_code == 201, followed.text
    payload = followed.json()
    assert payload["incident"]["status"] == S.CANCELLED.value
    assert payload["incident"]["cancel_reason"] == "duplicate"
    assert payload["followed"]["id"] == parent

    # The follower's own page names the incident it follows and how that one stands.
    child = api.get(f"/incidents/{payload['incident']['id']}", headers=other).json()
    assert child["duplicate_of"] == {"id": parent, "title": "Fee portal down", "status": "ASSIGNED"}
    assert api.get(f"/incidents/{parent}", headers=other).status_code == 403  # still BR-01
    assert api.get(f"/incidents/{parent}", headers=reporter).json()["duplicate_count"] == 1

    # ...and they hear when it is fixed (D-005).
    for step, json in (("acknowledge", None), ("start", None), ("resolve", {"summary": "Fixed"})):
        assert (
            api.post(f"/incidents/{parent}/{step}", json=json, headers=technician).status_code
            == 200
        )
    bell = api.get("/notifications", headers=other).json()["latest"]
    assert any(parent in n["subject"] and "resolved" in n["subject"] for n in bell)


def test_BR09_whoever_works_the_incident_confirms_a_possible_duplicate(
    api: TestClient, reporter: dict[str, str], lead: dict[str, str], clock: FakeClock
) -> None:
    parent = report(api, reporter, **PORTAL_DOWN)["incident"]["id"]
    clock.advance(timedelta(minutes=5))
    other = token_for(api, "other@campus.edu")
    child = report(
        api,
        other,
        title="Fee payment portal error 503",
        description="Cannot pay my fees",
        service_id=PORTAL,
    )
    child_id = child["incident"]["id"]
    assert [c["id"] for c in child["possible_duplicates"]] == [parent]

    seen = api.get(f"/incidents/{child_id}/possible-duplicates", headers=lead)
    assert seen.status_code == 200, seen.text
    assert [c["id"] for c in seen.json()["candidates"]] == [parent]
    assert api.get(f"/incidents/{child_id}/possible-duplicates", headers=other).status_code == 403

    refused = api.post(
        f"/incidents/{child_id}/confirm-duplicate", json={"parent_id": parent}, headers=other
    )
    assert refused.status_code == 403
    itself = api.post(
        f"/incidents/{child_id}/confirm-duplicate", json={"parent_id": child_id}, headers=lead
    )
    assert itself.status_code == 422
    missing = api.post(
        f"/incidents/{child_id}/confirm-duplicate",
        json={"parent_id": "INC-2026-9999"},
        headers=lead,
    )
    assert missing.status_code == 404

    confirmed = api.post(
        f"/incidents/{child_id}/confirm-duplicate", json={"parent_id": parent}, headers=lead
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == S.CANCELLED.value
    assert confirmed.json()["duplicate_of"]["id"] == parent
    again = api.post(
        f"/incidents/{child_id}/confirm-duplicate", json={"parent_id": parent}, headers=lead
    )
    assert again.status_code == 409  # CANCELLED is terminal (§4)

    bell = api.get("/notifications", headers=other).json()["latest"]
    assert any(f"handled as part of {parent}" in n["subject"] for n in bell)


# ---------------------------------------------------------------- correlation (§6.2)
def test_the_fee_portal_incident_names_the_database_outage_as_its_likely_root_cause(
    api: TestClient, engine: Engine, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    uow = SqlAlchemyUnitOfWork(make_session_factory(engine))
    try:
        uow.catalogue.save_service(ITService(4, "Database Cluster", criticality=3))
        portal = uow.catalogue.get_service(PORTAL)
        portal.add_dependency(4)
        uow.catalogue.save_service(portal)
        uow.commit()
    finally:
        uow.close()

    database = report(
        api,
        reporter,
        title="Database cluster unreachable",
        description="Every network query times out",
        service_id=4,
        impact=3,
        urgency=3,
    )["incident"]
    assert database["priority"] in ("P1", "P2")
    fees = report(
        api,
        reporter,
        title="Cannot pay hostel fees",
        description="The payment page spins and then errors",
        service_id=PORTAL,
    )["incident"]

    found = api.get(f"/incidents/{fees['id']}/correlation", headers=admin)
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["hint"] == (
        f"Likely related to {database['id']} (Database Cluster): possible root cause."
    )
    (cause,) = body["root_causes"]
    assert cause["path"] == ["Fee Payment Portal", "Database Cluster"]
    assert cause["hops"] == 1

    reverse = api.get(f"/incidents/{database['id']}/correlation", headers=admin).json()
    assert reverse["hint"] is None
    assert [i["id"] for i in reverse["impacted"]] == [fees["id"]]

    # BR-01: the reporter of both still may not read the graph's view of other incidents.
    assert api.get(f"/incidents/{fees['id']}/correlation", headers=reporter).status_code == 403

    # Once the database incident is withdrawn, the hint goes with it.
    api.post(f"/incidents/{database['id']}/cancel", json={}, headers=reporter)
    after = api.get(f"/incidents/{fees['id']}/correlation", headers=admin).json()
    assert after == {"hint": None, "root_causes": [], "impacted": []}


# ---------------------------------------------------------------- live updates (P4.8)
def test_a_socket_without_a_valid_token_is_closed_with_4401(api: TestClient) -> None:
    for first in ({"token": "not-a-token"}, {"hello": "there"}):
        with api.websocket_connect("/ws") as socket:
            socket.send_json(first)
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 4401


def test_the_reporter_and_the_admin_hear_about_a_change_after_it_commits(
    api: TestClient, reporter: dict[str, str], admin: dict[str, str]
) -> None:
    def bearer(headers: dict[str, str]) -> str:
        return headers["Authorization"].removeprefix("Bearer ")

    with (
        api.websocket_connect("/ws") as mine,
        api.websocket_connect("/ws") as watching,
    ):
        mine.send_json({"token": bearer(reporter)})
        watching.send_json({"token": bearer(admin)})
        assert mine.receive_json() == {"type": "ready"}
        assert watching.receive_json() == {"type": "ready"}

        incident_id = report(api, reporter)["incident"]["id"]

        pushed = mine.receive_json()
        assert pushed == {"type": "incident", "incident_id": incident_id, "status": "ASSIGNED"}
        assert watching.receive_json()["incident_id"] == incident_id
        # Only the id and status travel; the content is read through the API (BR-01).
        assert set(pushed) == {"type", "incident_id", "status"}


# ---------------------------------------------------------------- Telegram linking (P4.9)
def test_a_user_links_and_unlinks_telegram_and_without_a_bot_a_test_is_503(
    api: TestClient, reporter: dict[str, str]
) -> None:
    me = api.get("/auth/me", headers=reporter).json()
    assert (me["telegram_chat_id"], me["telegram_available"]) == (None, False)

    assert (
        api.put("/auth/me/telegram", json={"chat_id": "@me"}, headers=reporter).status_code == 422
    )
    linked = api.put("/auth/me/telegram", json={"chat_id": "123456789"}, headers=reporter)
    assert linked.status_code == 200
    assert linked.json()["telegram_chat_id"] == "123456789"
    assert api.get("/auth/me", headers=reporter).json()["telegram_chat_id"] == "123456789"

    refused = api.post("/auth/me/telegram/test", headers=reporter)
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "network_failure"

    assert api.delete("/auth/me/telegram", headers=reporter).json()["telegram_chat_id"] is None


# ---------------------------------------------------------------- Google Sign-In (P4.10)
def test_google_sign_in_signs_a_campus_account_in_and_refuses_others(api: TestClient) -> None:
    class Google(IdentityVerifier):
        def __init__(self) -> None:
            self.hd: str | None = "campus.edu"

        def verify(self, token: str) -> VerifiedIdentity:
            return VerifiedIdentity("meera@campus.edu", "Meera Iyer", self.hd, "g-77")

    google = Google()
    app_services: Services = api.app.state.services  # type: ignore[attr-defined]
    api.app.state.services = replace(  # type: ignore[attr-defined]
        app_services, google=google, policy=AuthPolicy(google_hosted_domain="campus.edu")
    )
    body = {"credential": "a-google-id-token-of-some-length"}

    signed_in = api.post("/auth/google", json=body)
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["role"] == "employee"
    me = api.get(
        "/auth/me", headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    ).json()
    assert (me["email"], me["full_name"]) == ("meera@campus.edu", "Meera Iyer")

    google.hd = "gmail.com"
    refused = api.post("/auth/google", json=body)
    assert refused.status_code == 401
    assert "campus.edu" in refused.json()["error"]["message"]


def test_a_socket_closes_with_4401_once_its_token_has_expired(
    api: TestClient, reporter: dict[str, str], clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P4 review: a socket must not keep receiving pushes after the sign-in lapses."""
    monkeypatch.setattr("app.api.routers.ws.RECHECK_SECONDS", 0.05)
    with api.websocket_connect("/ws") as socket:
        socket.send_json({"token": reporter["Authorization"].removeprefix("Bearer ")})
        assert socket.receive_json() == {"type": "ready"}
        clock.advance(timedelta(minutes=31))  # the test tokens last 30 minutes
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4401
