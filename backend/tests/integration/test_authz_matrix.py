"""Every role against every endpoint (blueprint §8, BR-01, BR-02, BR-03; P2.9).

Authorisation is server-side, so it has to be proved server-side: for each operation the API
offers, this asserts which roles get through the gate and which get 403. "Through the gate"
means not 401 and not 403 — a 409 because the lifecycle refuses, or a 422 because the body is
thin, still counts as allowed, because the question here is only who may ask.

The last test compares the matrix with the OpenAPI document, so a new endpoint cannot be added
without saying who may call it.
"""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
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
from app.domain.sla import default_policies
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
SERVICE, CATEGORY = 1, 1
#: Path parameters that name seeded rows: the technician, the one service, the one category.
PATH_VALUES = {
    "{user_id}": "3",
    "{service_id}": str(SERVICE),
    "{category_id}": str(CATEGORY),
    "{tier}": "gold",
    "{priority}": "P1",
}

#: Who exists, and what they are. The Team Lead is marked unavailable so auto-assignment
#: always picks ``technician``: the matrix has to be deterministic to mean anything.
ACCOUNTS: tuple[tuple[str, Role], ...] = (
    ("employee", Role.EMPLOYEE),
    ("other", Role.EMPLOYEE),
    ("technician", Role.TECHNICIAN),
    ("lead", Role.TEAM_LEAD),
    ("admin", Role.ADMINISTRATOR),
    ("manager", Role.IT_MANAGER),
)
EVERYONE = tuple(name for name, _ in ACCOUNTS)
STAFF = ("technician", "lead", "admin", "manager")
#: BR-01: an employee sees only their own, so every other role can view and ``other`` cannot.
VIEWERS = ("employee", "technician", "lead", "admin", "manager")
LEADERSHIP = ("lead", "admin", "manager")
ADMINS = ("admin", "manager")
REPORTER_ONLY = ("employee",)


@dataclass(frozen=True, slots=True)
class Operation:
    """One API operation and the accounts that may call it."""

    method: str
    path: str
    allowed: tuple[str, ...]
    body: dict[str, Any] | None = None
    #: True when the path contains {incident_id} and needs a fresh incident per call.
    needs_incident: bool = False
    #: True when nobody needs to be signed in (blueprint §8: only these three).
    public: bool = False
    notes: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)


MATRIX: tuple[Operation, ...] = (
    # --- public
    Operation("GET", "/health", EVERYONE, public=True, notes="liveness"),
    Operation(
        "POST",
        "/auth/register",
        EVERYONE,
        body={"email": "fresh@campus.edu", "full_name": "Fresh Person", "password": PASSWORD},
        public=True,
        notes="D-008 self-registration",
    ),
    Operation(
        "POST",
        "/auth/login",
        EVERYONE,
        body={"email": "employee@campus.edu", "password": PASSWORD},
        public=True,
    ),
    # --- everyone signed in
    Operation("GET", "/auth/me", EVERYONE),
    Operation("GET", "/catalogue/services", EVERYONE),
    Operation("GET", "/catalogue/categories", EVERYONE),
    Operation("GET", "/catalogue/skills", EVERYONE),
    Operation("GET", "/catalogue/teams", EVERYONE),
    Operation("GET", "/notifications", EVERYONE),
    Operation("GET", "/incidents/mine", EVERYONE),
    Operation("POST", "/incidents/search", EVERYONE, body={}),
    Operation("POST", "/incidents/search/export", EVERYONE, body={}),
    Operation("GET", "/dev/clock", EVERYONE, notes="D-009: test and demo only"),
    Operation("POST", "/dev/clock/advance", EVERYONE, body={"seconds": 1, "tick": False}),
    # --- reporting
    Operation(
        "POST",
        "/incidents",
        EVERYONE,
        body={
            "title": "Wi-Fi down",
            "description": "No wifi signal at all",
            "service_id": SERVICE,
            "impact": 1,
            "urgency": 1,
        },
    ),
    Operation("POST", "/incidents/classify", EVERYONE, body={"text": "no wifi signal"}),
    Operation(
        "POST",
        "/incidents/similar",
        EVERYONE,
        body={"title": "no wifi signal"},
        notes="BR-09: the while-typing duplicate hint",
    ),
    # --- the reporter's own incident
    Operation(
        "GET",
        "/incidents/{incident_id}",
        VIEWERS,
        needs_incident=True,
        notes="BR-01: another employee is refused",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/information",
        REPORTER_ONLY,
        body={"text": "The library, first floor"},
        needs_incident=True,
        notes="D-006: the reporter answers",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/verify",
        REPORTER_ONLY,
        body={"rating": 5},
        needs_incident=True,
        notes="BR-03",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/reject",
        REPORTER_ONLY,
        body={"reason": "It came back"},
        needs_incident=True,
        notes="BR-03",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/cancel",
        ("employee", "admin", "manager"),
        body={},
        needs_incident=True,
        notes="the reporter withdraws; an admin cancels any",
    ),
    # --- working an incident (BR-02)
    Operation("GET", "/incidents/queue", STAFF),
    Operation("POST", "/incidents/{incident_id}/acknowledge", STAFF, needs_incident=True),
    Operation("POST", "/incidents/{incident_id}/start", STAFF, needs_incident=True),
    Operation(
        "POST",
        "/incidents/{incident_id}/notes",
        STAFF,
        body={"text": "Looking into it"},
        needs_incident=True,
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/request-information",
        STAFF,
        body={"text": "Which building?"},
        needs_incident=True,
    ),
    Operation("POST", "/incidents/{incident_id}/resume", STAFF, needs_incident=True),
    Operation(
        "POST",
        "/incidents/{incident_id}/resolve",
        STAFF,
        body={"summary": "Replaced the access point"},
        needs_incident=True,
        notes="BR-04",
    ),
    Operation("POST", "/incidents/{incident_id}/close", STAFF, needs_incident=True),
    Operation(
        "GET",
        "/incidents/{incident_id}/risk",
        VIEWERS,
        needs_incident=True,
        notes="§6.3; BR-01 as for the incident itself",
    ),
    Operation(
        "GET",
        "/incidents/{incident_id}/correlation",
        STAFF,
        needs_incident=True,
        notes="§6.2: names other people's incidents, so not for employees",
    ),
    Operation(
        "GET",
        "/incidents/{incident_id}/possible-duplicates",
        STAFF,
        needs_incident=True,
        notes="BR-09",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/confirm-duplicate",
        STAFF,
        body={"parent_id": "INC-2026-0001"},
        needs_incident=True,
        notes="BR-09: the technician confirms",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/priority",
        STAFF,
        body={"priority": "P1", "reason": "Exam tomorrow"},
        needs_incident=True,
        notes="BR-05",
    ),
    Operation(
        "POST",
        "/incidents/{incident_id}/category",
        STAFF,
        body={"category_id": CATEGORY},
        needs_incident=True,
    ),
    # --- a lead's and an admin's reach
    Operation("GET", "/incidents/{incident_id}/assignment-advice", LEADERSHIP, needs_incident=True),
    Operation(
        "POST",
        "/incidents/{incident_id}/reassign",
        LEADERSHIP,
        body={"technician_id": 3},
        needs_incident=True,
        notes="BR-06",
    ),
    Operation("GET", "/reports/workload", STAFF, notes="own row for a technician"),
    Operation("GET", "/reports/workload/export", STAFF),
    Operation("GET", "/sla/violations", ADMINS),
    Operation("GET", "/sla/violations/{incident_id}", ADMINS, needs_incident=True),
    Operation("POST", "/sla/tick", ADMINS),
    Operation("GET", "/reports/dashboard", ADMINS),
    Operation("GET", "/reports/overview", ADMINS),
    Operation("GET", "/reports/metrics", ADMINS),
    Operation("GET", "/reports/services", ADMINS),
    Operation("GET", "/reports/services/export", ADMINS),
    Operation("GET", "/reports/trend", ADMINS),
    # --- the bell: your own notification only, so the matrix covers it elsewhere
    Operation(
        "POST",
        "/notifications/{notification_id}/read",
        EVERYONE,
        notes="ownership checked in test_only_your_own_notification",
    ),
    # --- names beside ids (P3)
    Operation("GET", "/users/directory", EVERYONE, notes="BR-01: employees see staff only"),
    # --- administration (P3.4, P3.5)
    Operation("GET", "/users", ADMINS),
    Operation(
        "POST",
        "/users",
        ADMINS,
        body={
            "email": "hired@campus.edu",
            "full_name": "Newly Hired",
            "password": PASSWORD,
            "role": "technician",
        },
    ),
    Operation("PATCH", "/users/{user_id}", ADMINS, body={}),
    Operation(
        "PUT",
        "/users/{user_id}/technician",
        ADMINS,
        body={"skills": ["networking"], "experience_level": 2, "available": True, "team_id": 1},
    ),
    Operation(
        "POST",
        "/catalogue/categories",
        ADMINS,
        body={"name": "Printing", "keywords": ["printer"]},
    ),
    Operation(
        "PUT",
        "/catalogue/categories/{category_id}",
        ADMINS,
        body={"name": "Network", "required_skill_id": 1, "keywords": ["wifi", "network"]},
    ),
    Operation("POST", "/catalogue/services", ADMINS, body={"name": "LMS", "criticality": 2}),
    Operation(
        "PUT",
        "/catalogue/services/{service_id}",
        ADMINS,
        body={"name": "Campus Wi-Fi", "criticality": 2},
    ),
    Operation("GET", "/sla/policies", ADMINS),
    Operation(
        "PUT",
        "/sla/policies/{tier}/{priority}",
        ADMINS,
        body={"response_minutes": 5, "resolution_minutes": 30},
    ),
    Operation("GET", "/config/assignment", ADMINS),
    Operation(
        "PUT",
        "/config/assignment",
        ADMINS,
        body={
            "strategy": "smart",
            "weights": {"skills": 0.4, "capacity": 0.3, "experience": 0.15, "history": 0.15},
        },
    ),
    Operation("GET", "/audit", ADMINS),
    Operation("POST", "/audit/verify", ADMINS),
)


@dataclass
class World:
    """The signed-in accounts and a way to make a fresh incident for each call."""

    api: TestClient
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    ids: dict[str, int] = field(default_factory=dict)


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
        uow.catalogue.save_skill(Skill(1, "networking"))
        uow.catalogue.save_category(
            Category(CATEGORY, "Network", required_skill_id=1, keywords=("wifi", "network"))
        )
        uow.catalogue.save_service(ITService(SERVICE, "Campus Wi-Fi", criticality=2))
        uow.catalogue.save_policies(default_policies())
        uow.catalogue.save_team(Team(1, "Network Operations"))
        hasher = FakePasswordHasher()
        for index, (name, role) in enumerate(ACCOUNTS, start=1):
            support = UserFactory.is_support_role(role)
            uow.users.add(
                UserFactory.create(
                    role,
                    user_id=index,
                    email=f"{name}@campus.edu",
                    full_name=f"{name.title()} Person",
                    skills=SkillSet({"networking"}) if support else None,
                    experience_level=2 if support else None,
                    # The lead owns the queue rather than working it, which also makes
                    # auto-assignment deterministic for this matrix.
                    available=(name != "lead") if support else None,
                    team_id=1 if support else None,
                )
            )
            credentials = uow.credentials.get(index)
            credentials.set_password_hash(hasher.hash(PASSWORD))
            uow.credentials.save(credentials)
        team = uow.catalogue.get_team(1)
        for member, (_, role) in enumerate(ACCOUNTS, start=1):
            if UserFactory.is_support_role(role):
                team.add_member(member)
        team.set_lead(4)  # the Team Lead
        uow.catalogue.save_team(team)
        uow.commit()
    finally:
        uow.close()
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def api(engine: Engine, clock: FakeClock, database_url: str) -> Iterator[TestClient]:
    from app.main import create_app

    settings = Settings(
        app_env=AppEnv.TEST,
        database_url=database_url,
        clock_mode=ClockMode.FAKE,
        sla_tick_seconds=0,
        _env_file=None,
    )
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


@pytest.fixture
def world(api: TestClient) -> World:
    built = World(api)
    for name, _ in ACCOUNTS:
        response = api.post(
            "/auth/login", json={"email": f"{name}@campus.edu", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        built.tokens[name] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        built.ids[name] = response.json()["user_id"]
    return built


#: BR-09 refuses the same reporter's near-identical report within 30 minutes, so each fresh
#: incident is about something else.
FRESH_REPORTS: tuple[tuple[str, str], ...] = (
    ("Wi-Fi down in the library", "No wifi signal on the first floor"),
    ("Projector will not switch on", "Lecture hall F-105 before the ten o'clock class"),
    ("Printer jammed", "Paper stuck in tray two of the admin office printer"),
    ("Cannot open my mailbox", "Outlook asks for a password again and again"),
    ("Lab computer shows a black screen", "Machine fourteen in C-309 never boots"),
    ("VPN keeps disconnecting", "Drops every few minutes from home"),
    ("Keyboard keys are stuck", "The space bar on the reception desk keyboard"),
    ("Shared drive missing", "The accounts folder vanished from the network drive"),
)
_fresh_reports = itertools.count()


def fresh_incident(world: World) -> str:
    """An incident reported by ``employee`` and assigned by the system."""
    title, description = FRESH_REPORTS[next(_fresh_reports) % len(FRESH_REPORTS)]
    response = world.api.post(
        "/incidents",
        json={
            "title": title,
            # "wifi" is the seeded category's keyword, so each one is classified and assigned.
            "description": f"{description}. The wifi is also slow.",
            "service_id": SERVICE,
            "impact": 2,
            "urgency": 2,
        },
        headers=world.tokens["employee"],
    )
    assert response.status_code == 201, response.text
    incident_id: str = response.json()["incident"]["id"]
    return incident_id


def call(world: World, operation: Operation, account: str | None) -> int:
    """Make the call as ``account`` (or with no token) and return the status."""
    path = operation.path
    if operation.needs_incident:
        path = path.replace("{incident_id}", fresh_incident(world))
    if "{notification_id}" in path:
        bell = world.api.get("/notifications", headers=world.tokens[account or "employee"]).json()
        first = bell["latest"][0]["id"] if bell["latest"] else 1
        path = path.replace("{notification_id}", str(first))
    for name, value in PATH_VALUES.items():
        path = path.replace(name, value)
    headers = {} if account is None else world.tokens[account]
    response = world.api.request(operation.method, path, json=operation.body, headers=headers)
    return int(response.status_code)


REFUSED = (401, 403)


@pytest.mark.parametrize("operation", MATRIX, ids=[f"{op.method} {op.path}" for op in MATRIX])
def test_every_role_gets_the_answer_the_matrix_promises(world: World, operation: Operation) -> None:
    for account, _ in ACCOUNTS:
        status = call(world, operation, account)
        if account in operation.allowed:
            assert status not in REFUSED, (
                f"{account} should be allowed to {operation.method} {operation.path} "
                f"but got {status}"
            )
        else:
            assert status == 403, (
                f"{account} should be refused {operation.method} {operation.path} but got {status}"
            )


@pytest.mark.parametrize(
    "operation",
    [op for op in MATRIX if not op.public],
    ids=[f"{op.method} {op.path}" for op in MATRIX if not op.public],
)
def test_everything_but_the_three_public_endpoints_needs_a_token(
    world: World, operation: Operation
) -> None:
    assert call(world, operation, None) == 401


def test_BR01_another_employee_is_refused_someone_elses_incident(world: World) -> None:
    incident_id = fresh_incident(world)
    for path in (
        f"/incidents/{incident_id}",
        f"/sla/violations/{incident_id}",
    ):
        assert world.api.get(path, headers=world.tokens["other"]).status_code == 403

    for path, body in (
        (f"/incidents/{incident_id}/information", {"text": "not mine"}),
        (f"/incidents/{incident_id}/verify", {"rating": 5}),
        (f"/incidents/{incident_id}/reject", {"reason": "not mine"}),
        (f"/incidents/{incident_id}/cancel", {}),
    ):
        assert world.api.post(path, json=body, headers=world.tokens["other"]).status_code == 403, (
            path
        )


def test_BR02_a_technician_outside_the_incident_is_refused(
    world: World, engine: Engine, clock: FakeClock
) -> None:
    """Only the assignee, the escalation owner or an admin may work it (BR-02)."""
    incident_id = fresh_incident(world)
    assignee = world.api.get(f"/incidents/{incident_id}", headers=world.tokens["admin"]).json()[
        "assignee_id"
    ]
    assert assignee == world.ids["technician"], "the lead is unavailable, so this is fixed"

    stranger = _another_technician(engine, clock)
    refused = world.api.post("/auth/login", json={"email": stranger, "password": PASSWORD})
    assert refused.status_code == 200
    headers = {"Authorization": f"Bearer {refused.json()['access_token']}"}

    assert world.api.get(f"/incidents/{incident_id}", headers=headers).status_code == 403
    for path, body in (
        (f"/incidents/{incident_id}/acknowledge", None),
        (f"/incidents/{incident_id}/notes", {"text": "not mine"}),
        (f"/incidents/{incident_id}/resolve", {"summary": "not mine"}),
    ):
        assert world.api.post(path, json=body, headers=headers).status_code == 403, path

    # Their own queue is still theirs to see.
    assert world.api.get("/incidents/queue", headers=headers).status_code == 200


def _another_technician(engine: Engine, clock: FakeClock) -> str:
    """A technician in a different team, so they are outside every incident above."""
    email = "outsider@campus.edu"
    uow = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
    try:
        uow.catalogue.save_team(Team(2, "Service Desk"))
        user_id = uow.users.next_id()
        uow.users.add(
            UserFactory.create(
                Role.TECHNICIAN,
                user_id=user_id,
                email=email,
                full_name="Imran Shaikh",
                skills=SkillSet({"printing"}),
                experience_level=1,
                team_id=2,
            )
        )
        credentials = uow.credentials.get(user_id)
        credentials.set_password_hash(FakePasswordHasher().hash(PASSWORD))
        uow.credentials.save(credentials)
        uow.commit()
    finally:
        uow.close()
    return email


def test_only_your_own_notification_can_be_marked_read(world: World) -> None:
    fresh_incident(world)
    bell = world.api.get("/notifications", headers=world.tokens["employee"]).json()
    assert bell["latest"], "reporting should have notified the reporter"
    mine = bell["latest"][0]["id"]

    assert (
        world.api.post(f"/notifications/{mine}/read", headers=world.tokens["employee"]).status_code
        == 200
    )
    for account in ("other", "technician", "admin"):
        assert (
            world.api.post(f"/notifications/{mine}/read", headers=world.tokens[account]).status_code
            == 403
        ), account


def test_a_technician_sees_only_their_own_workload_row(world: World) -> None:
    rows = world.api.get("/reports/workload", headers=world.tokens["technician"]).json()
    assert [row["technician_id"] for row in rows] == [world.ids["technician"]]
    assert len(world.api.get("/reports/workload", headers=world.tokens["admin"]).json()) > 1


def test_the_matrix_covers_every_operation_the_api_offers(api: TestClient) -> None:
    """A new endpoint cannot be added without saying in this file who may call it."""
    document = api.get("/openapi.json").json()
    offered = {
        (method.upper(), path)
        for path, operations in document["paths"].items()
        for method in operations
    }
    covered = {operation.key for operation in MATRIX}
    assert offered - covered == set(), f"not in the matrix: {sorted(offered - covered)}"
    assert covered - offered == set(), f"no longer in the API: {sorted(covered - offered)}"
