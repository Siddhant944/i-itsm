"""The admin screens' endpoints over a seeded database (blueprint §3, §5.2, §5.3, §8; P3.4-5).

Each test goes through HTTP, so it also proves the wiring: a change made on a configuration
screen is what the next reported incident actually uses.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.adapters.smtp_email import ConsoleEmailSender
from app.api.deps import Services
from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.rule_advisor import RuleBasedAdvisor
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
PASSWORD = people.DEMO_PASSWORD
ADMIN, EMPLOYEE, TECHNICIAN = "admin@campus.edu", "employee@campus.edu", "technician@campus.edu"


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
        seed(uow, clock, hash_password=FakePasswordHasher().hash, history=20)
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


def token_for(api: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = api.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(api: TestClient) -> dict[str, str]:
    return token_for(api, ADMIN)


def activity(api: TestClient) -> str:
    """Enough audited activity to page through: sign-ins and one reported incident."""
    employee = token_for(api, EMPLOYEE)
    for _ in range(6):
        token_for(api, TECHNICIAN)
    service = api.get("/catalogue/services", headers=employee).json()[0]["id"]
    reported = api.post(
        "/incidents",
        json={
            "title": "Cannot connect",
            "description": "No wifi signal in the library",
            "service_id": service,
            "impact": 2,
            "urgency": 2,
        },
        headers=employee,
    )
    assert reported.status_code == 201, reported.text
    incident_id: str = reported.json()["incident"]["id"]
    return incident_id


def last_audit(api: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    newest: dict[str, Any] = api.get("/audit?limit=1", headers=admin).json()["items"][0]
    return newest


# ---------------------------------------------------------------- users
def test_the_directory_gives_names_and_hides_other_employees_from_an_employee(
    api: TestClient, admin: dict[str, str]
) -> None:
    everyone = api.get("/users/directory", headers=admin).json()
    mine = api.get("/users/directory", headers=token_for(api, EMPLOYEE)).json()
    assert {"id", "full_name", "role"} == set(everyone[0])
    assert len(mine) < len(everyone)
    employees = [entry for entry in mine if entry["role"] == "employee"]
    assert [entry["full_name"] for entry in employees] == ["Devika Rao"]


def test_an_admin_creates_a_technician_who_can_then_sign_in(
    api: TestClient, admin: dict[str, str]
) -> None:
    created = api.post(
        "/users",
        json={
            "email": "new.tech@campus.edu",
            "full_name": "New Tech",
            "password": "a long enough password",
            "role": "technician",
            "technician": {"skills": ["networking"], "experience_level": 2, "team_id": 1},
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["role"] == "technician"
    assert body["skills"] == ["networking"]
    me = api.get(
        "/auth/me", headers=token_for(api, "new.tech@campus.edu", "a long enough password")
    ).json()
    assert me["portal"] == "technician"
    assert last_audit(api, admin)["action"] == "login.succeeded"
    listed = {user["email"] for user in api.get("/users", headers=admin).json()}
    assert "new.tech@campus.edu" in listed


def test_a_deactivated_account_can_no_longer_sign_in(
    api: TestClient, admin: dict[str, str]
) -> None:
    employee = api.get("/auth/me", headers=token_for(api, EMPLOYEE)).json()
    changed = api.patch(f"/users/{employee['id']}", json={"active": False}, headers=admin)
    assert changed.status_code == 200
    assert changed.json()["active"] is False
    assert last_audit(api, admin)["details"]["change"] == "deactivated"
    refused = api.post("/auth/login", json={"email": EMPLOYEE, "password": PASSWORD})
    assert refused.status_code == 401


def test_an_admin_cannot_deactivate_or_demote_themselves(
    api: TestClient, admin: dict[str, str]
) -> None:
    me = api.get("/auth/me", headers=admin).json()
    assert api.patch(f"/users/{me['id']}", json={"active": False}, headers=admin).status_code == 403
    assert (
        api.patch(f"/users/{me['id']}", json={"role": "employee"}, headers=admin).status_code == 403
    )


def test_a_role_change_moves_the_person_to_another_portal(
    api: TestClient, admin: dict[str, str]
) -> None:
    employee = api.get("/auth/me", headers=token_for(api, EMPLOYEE)).json()
    changed = api.patch(f"/users/{employee['id']}", json={"role": "technician"}, headers=admin)
    assert changed.status_code == 200, changed.text
    assert changed.json()["experience_level"] == 1
    assert api.get("/auth/me", headers=token_for(api, EMPLOYEE)).json()["portal"] == "technician"


def test_a_technicians_profile_is_edited_and_unknown_skills_are_refused(
    api: TestClient, admin: dict[str, str]
) -> None:
    tech = api.get("/auth/me", headers=token_for(api, TECHNICIAN)).json()
    path = f"/users/{tech['id']}/technician"
    updated = api.put(
        path,
        json={
            "skills": ["email", "networking"],
            "experience_level": 3,
            "available": False,
            "team_id": tech["technician"]["team_id"],
        },
        headers=admin,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["skills"] == ["email", "networking"]
    assert updated.json()["available"] is False
    refused = api.put(path, json={"skills": ["juggling"]}, headers=admin)
    assert refused.status_code == 422
    assert "skills" in refused.json()["error"]["details"]["field_errors"]


# ---------------------------------------------------------------- catalogue
def test_a_new_category_takes_effect_live_for_the_classifier(
    api: TestClient, admin: dict[str, str]
) -> None:
    employee = token_for(api, EMPLOYEE)
    text_ = {"text": "the zorblatt machine is humming"}
    before = api.post("/incidents/classify", json=text_, headers=employee).json()
    created = api.post(
        "/catalogue/categories",
        json={"name": "Zorblatt", "keywords": ["zorblatt"], "minimum_priority": "P2"},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    after = api.post("/incidents/classify", json=text_, headers=employee).json()
    assert (before or {}).get("category_id") != created.json()["id"]
    assert after["category_id"] == created.json()["id"]
    assert last_audit(api, admin)["details"]["change"] == "category.created"


def test_a_retired_category_is_hidden_from_everyone_but_the_admin_screen(
    api: TestClient, admin: dict[str, str]
) -> None:
    first = api.get("/catalogue/categories", headers=admin).json()[0]
    retired = api.put(
        f"/catalogue/categories/{first['id']}", json={**first, "active": False}, headers=admin
    )
    assert retired.status_code == 200, retired.text
    employee = token_for(api, EMPLOYEE)
    for headers in (employee, admin):
        visible = api.get("/catalogue/categories", headers=headers).json()
        assert first["id"] not in {c["id"] for c in visible}
    # Asking for retired rows only works for someone who can manage the catalogue.
    asked = api.get("/catalogue/categories?include_inactive=true", headers=employee).json()
    assert first["id"] not in {c["id"] for c in asked}
    everything = api.get("/catalogue/categories?include_inactive=true", headers=admin).json()
    assert first["id"] in {c["id"] for c in everything}


def test_a_service_is_created_edited_and_kept_acyclic(
    api: TestClient, admin: dict[str, str]
) -> None:
    services = api.get("/catalogue/services", headers=admin).json()
    dependent = next(s for s in services if s["depends_on"])
    upstream = dependent["depends_on"][0]

    created = api.post(
        "/catalogue/services",
        json={"name": "Hostel Laundry App", "criticality": 1, "depends_on": [upstream]},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    assert created.json()["sla_tier"] == "bronze"
    assert created.json()["tier_overridden"] is False

    pinned = api.put(
        f"/catalogue/services/{created.json()['id']}",
        json={"name": "Hostel Laundry App", "criticality": 1, "sla_tier": "gold"},
        headers=admin,
    )
    assert pinned.json()["sla_tier"] == "gold"
    assert pinned.json()["depends_on"] == []

    target = next(s for s in services if s["id"] == upstream)
    cycle = api.put(
        f"/catalogue/services/{upstream}",
        json={
            "name": target["name"],
            "criticality": target["criticality"],
            "depends_on": [dependent["id"]],
        },
        headers=admin,
    )
    assert cycle.status_code == 422
    assert "depends_on" in cycle.json()["error"]["details"]["field_errors"]


# ---------------------------------------------------------------- SLA policies
def test_an_edited_sla_policy_sets_the_deadline_of_the_next_incident(
    api: TestClient, admin: dict[str, str], clock: FakeClock
) -> None:
    grid = api.get("/sla/policies", headers=admin).json()
    assert len(grid) == 12
    for cell in grid:
        changed = api.put(
            f"/sla/policies/{cell['tier']}/{cell['priority']}",
            json={"response_minutes": 7, "resolution_minutes": 77},
            headers=admin,
        )
        assert changed.status_code == 200, changed.text
    service = api.get("/catalogue/services", headers=admin).json()[0]["id"]
    reported = api.post(
        "/incidents",
        json={
            "title": "Cannot connect",
            "description": "No wifi signal in the library",
            "service_id": service,
            "impact": 2,
            "urgency": 2,
        },
        headers=token_for(api, EMPLOYEE),
    )
    assert reported.status_code == 201, reported.text
    sla = reported.json()["incident"]["sla"]
    assert datetime.fromisoformat(sla["response_deadline"]) == NOW + timedelta(minutes=7)
    assert datetime.fromisoformat(sla["resolution_deadline"]) == NOW + timedelta(minutes=77)


def test_a_response_target_longer_than_the_resolution_target_is_refused(
    api: TestClient, admin: dict[str, str]
) -> None:
    refused = api.put(
        "/sla/policies/gold/P1",
        json={"response_minutes": 60, "resolution_minutes": 30},
        headers=admin,
    )
    assert refused.status_code == 422
    assert api.put("/sla/policies/platinum/P1", json={}, headers=admin).status_code == 422


# ---------------------------------------------------------------- assignment strategy
def test_the_strategy_is_switched_at_runtime_and_the_advice_names_it(
    api: TestClient, admin: dict[str, str]
) -> None:
    settings = api.get("/config/assignment", headers=admin).json()
    assert settings["strategy"] == "smart"
    assert settings["weights"] == {
        "skills": 0.4,
        "capacity": 0.3,
        "experience": 0.15,
        "history": 0.15,
    }
    assert set(settings["available"]) == {"smart", "skill_based", "load_based"}

    service = api.get("/catalogue/services", headers=admin).json()[0]["id"]
    incident = api.post(
        "/incidents",
        json={
            "title": "Cannot connect",
            "description": "No wifi signal in the library",
            "service_id": service,
            "impact": 2,
            "urgency": 2,
        },
        headers=token_for(api, EMPLOYEE),
    ).json()["incident"]["id"]
    advice = f"/incidents/{incident}/assignment-advice"
    assert api.get(advice, headers=admin).json()["strategy"] == "smart"

    switched = api.put(
        "/config/assignment",
        json={"strategy": "load_based", "weights": settings["weights"]},
        headers=admin,
    )
    assert switched.status_code == 200, switched.text
    assert api.get(advice, headers=admin).json()["strategy"] == "load_based"
    assert last_audit(api, admin)["details"]["change"] == "assignment.updated"


def test_weights_must_sum_to_one_and_the_strategy_must_exist(
    api: TestClient, admin: dict[str, str]
) -> None:
    weights = {"skills": 0.5, "capacity": 0.5, "experience": 0.5, "history": 0.5}
    bad_weights = api.put(
        "/config/assignment", json={"strategy": "smart", "weights": weights}, headers=admin
    )
    assert bad_weights.status_code == 422
    even = {"skills": 0.25, "capacity": 0.25, "experience": 0.25, "history": 0.25}
    unknown = api.put(
        "/config/assignment", json={"strategy": "coin_toss", "weights": even}, headers=admin
    )
    assert unknown.status_code == 422


# ---------------------------------------------------------------- audit
def test_the_audit_log_pages_newest_first_and_filters_by_incident(
    api: TestClient, admin: dict[str, str]
) -> None:
    incident = activity(api)
    first = api.get("/audit?limit=5", headers=admin).json()
    assert first["total"] > 5
    sequences = [item["sequence"] for item in first["items"]]
    assert sequences == sorted(sequences, reverse=True)
    assert sequences[0] == first["total"]
    second = api.get("/audit?limit=5&offset=5", headers=admin).json()
    assert second["items"][0]["sequence"] == sequences[-1] - 1
    beyond = api.get(f"/audit?offset={first['total']}", headers=admin).json()
    assert beyond["items"] == []

    only = api.get(f"/audit?incident_id={incident}", headers=admin).json()
    assert only["total"] >= 1
    assert {item["incident_id"] for item in only["items"]} == {incident}


def test_BR10_the_integrity_check_passes_then_fails_after_tampering(
    api: TestClient, admin: dict[str, str], engine: Engine
) -> None:
    activity(api)
    intact = api.post("/audit/verify", headers=admin).json()
    assert intact["intact"] is True
    assert intact["broken_at"] is None

    with engine.begin() as connection:
        victim = connection.execute(text("SELECT MIN(id) + 3 FROM audit_log")).scalar_one()
        connection.execute(
            text("UPDATE audit_log SET actor_id = NULL WHERE id = :id"), {"id": victim}
        )
    broken = api.post("/audit/verify", headers=admin).json()
    assert broken["intact"] is False
    assert broken["broken_at"] is not None
    assert "breaks at record" in broken["summary"]


# ---------------------------------------------------------------- the application clock
def test_every_response_says_what_time_the_application_clock_reads(
    api: TestClient, clock: FakeClock
) -> None:
    first = api.get("/health")
    assert first.headers["X-Server-Time"] == NOW.isoformat()
    assert first.headers["X-Clock-Rate"] == "0.0"
    clock.advance(timedelta(minutes=5))
    later = api.get("/health").headers["X-Server-Time"]
    assert datetime.fromisoformat(later) == NOW + timedelta(minutes=5)
