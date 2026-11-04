"""The facade against a real database: one transaction, and a conflict when two writers race.

The unit tests prove the rules; these prove the transaction boundary. An audit record and the
change it describes must commit together or not at all (BR-10), and the second writer of one
incident must be told to reload rather than quietly overwrite (blueprint §9).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select

from app.core.clock import FakeClock
from app.domain.audit import AuditAction, verify_chain
from app.domain.errors import ConcurrentModificationError
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.states import IncidentStatus as S
from app.domain.users import User
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base, IncidentRow
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.seed import people, seed
from app.services.dispatcher import PostCommitDispatcher
from app.services.incident_service import IncidentService

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
HISTORY = 40


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    made = make_engine(database_url)
    Base.metadata.drop_all(made)
    create_schema(made)
    uow = SqlAlchemyUnitOfWork(make_session_factory(made), FakeClock(NOW))
    try:
        seed(uow, FakeClock(NOW), history=HISTORY)
    finally:
        uow.close()
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def uow(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    unit = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    yield unit
    unit.close()


def facade(unit: SqlAlchemyUnitOfWork) -> IncidentService:
    return IncidentService(unit, FakeClock(NOW), advisor=RuleBasedAdvisor())


def reporter(unit: SqlAlchemyUnitOfWork) -> User:
    return unit.users.get(people.EMPLOYEES[0].user_id)


def wifi_service_id(unit: SqlAlchemyUnitOfWork) -> int:
    return next(s.id for s in unit.catalogue.services() if s.name == "Campus Wi-Fi")


def test_reporting_over_the_seeded_catalogue_works_end_to_end(
    uow: SqlAlchemyUnitOfWork,
) -> None:
    service = facade(uow)
    result = service.report(
        reporter(uow),
        title="Wi-Fi keeps dropping",
        description="The wifi connection drops every few minutes in the library",
        service_id=wifi_service_id(uow),
        impact=2,
        urgency=3,
    )
    assert result.incident.status is S.ASSIGNED
    assert result.incident.category_id is not None
    assert result.incident.priority is not None
    assert result.assignment is not None

    stored = uow.incidents.get(result.incident.id)
    assert stored.assignee_id == result.incident.assignee_id
    assert stored.sla_clock is not None


def test_the_seeded_history_does_not_collide_with_a_new_report(
    uow: SqlAlchemyUnitOfWork,
) -> None:
    before = uow.session.scalar(select(func.count()).select_from(IncidentRow))
    reported = facade(uow).report(
        reporter(uow),
        title="Wi-Fi keeps dropping",
        description="No wifi signal at all",
        service_id=wifi_service_id(uow),
        impact=1,
        urgency=1,
    )
    assert reported.incident.id == f"INC-2026-{HISTORY + 1:04d}"
    assert uow.session.scalar(select(func.count()).select_from(IncidentRow)) == (before or 0) + 1


def test_BR10_the_audit_record_and_the_change_share_one_transaction(
    uow: SqlAlchemyUnitOfWork, engine: Engine
) -> None:
    incident_id = (
        facade(uow)
        .report(
            reporter(uow),
            title="Wi-Fi keeps dropping",
            description="No wifi signal in the library",
            service_id=wifi_service_id(uow),
            impact=2,
            urgency=2,
        )
        .incident.id
    )

    # A separate connection sees both, or it would see neither.
    other = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        assert other.incidents.get(incident_id).status is S.ASSIGNED
        actions = [r.action for r in other.audit.records(limit=200, incident_id=incident_id)]
        assert AuditAction.INCIDENT_CREATED in actions
        assert AuditAction.PRIORITY_ASSESSED in actions
        assert AuditAction.INCIDENT_STATE_CHANGED in actions
        assert verify_chain(other.audit.records(limit=1000)).intact is True
    finally:
        other.close()


def test_a_failed_commit_leaves_neither_the_change_nor_its_audit_record(
    uow: SqlAlchemyUnitOfWork, engine: Engine
) -> None:
    """BR-10: the trail must never record something the database rolled back."""
    service = facade(uow)
    incident_id = service.report(
        reporter(uow),
        title="Wi-Fi keeps dropping",
        description="No wifi signal in the library",
        service_id=wifi_service_id(uow),
        impact=2,
        urgency=2,
    ).incident.id
    committed_records = uow.audit.count()

    incident = uow.incidents.get(incident_id)
    assignee = incident.assignee_id
    assert assignee is not None

    delivered: list[object] = []
    failing = IncidentService(
        uow,
        FakeClock(NOW),
        dispatcher=PostCommitDispatcher([delivered.append]),
        advisor=RuleBasedAdvisor(),
    )
    with monkeypatched_commit(uow), pytest.raises(RuntimeError, match="database went away"):
        failing.add_note(uow.users.get(assignee), incident_id, "Never committed")
    uow.rollback()

    other = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        assert other.audit.count() == committed_records
        assert other.incidents.get(incident_id).notes == ()
        assert verify_chain(other.audit.records(limit=1000)).intact is True
    finally:
        other.close()
    assert delivered == [], "nothing may be notified about a change that was rolled back"


@contextmanager
def monkeypatched_commit(unit: SqlAlchemyUnitOfWork) -> Iterator[None]:
    """Make the next commit fail, as a dropped connection would."""
    original = unit.commit

    def explode() -> None:
        msg = "the database went away"
        raise RuntimeError(msg)

    object.__setattr__(unit, "commit", explode)
    try:
        yield
    finally:
        object.__setattr__(unit, "commit", original)


def test_a_second_writer_is_told_to_reload(uow: SqlAlchemyUnitOfWork, engine: Engine) -> None:
    """Optimistic locking surfaces as ConcurrentModificationError, which the API maps to 409."""
    incident_id = (
        facade(uow)
        .report(
            reporter(uow),
            title="Wi-Fi keeps dropping",
            description="No wifi signal in the library",
            service_id=wifi_service_id(uow),
            impact=2,
            urgency=2,
        )
        .incident.id
    )
    incident = uow.incidents.get(incident_id)
    assignee = incident.assignee_id
    assert assignee is not None

    second = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        theirs = facade(second)
        theirs.get(second.users.get(assignee), incident_id)  # they read it first

        facade(uow).acknowledge(uow.users.get(assignee), incident_id)  # we commit first

        with pytest.raises(ConcurrentModificationError):
            theirs.add_note(second.users.get(assignee), incident_id, "Stale write")
        second.rollback()
    finally:
        second.close()

    assert uow.incidents.get(incident_id).status is S.ACKNOWLEDGED
    assert verify_chain(uow.audit.records(limit=1000)).intact is True


def test_assignment_advice_uses_the_real_workloads(uow: SqlAlchemyUnitOfWork) -> None:
    """The seeded history gives the technicians real loads, so the ranking is not uniform."""
    loads = uow.incidents.workloads()
    assert loads, "the seeded history should leave some technicians carrying work"

    service = facade(uow)
    incident = service.report(
        reporter(uow),
        title="Wi-Fi keeps dropping",
        description="No wifi signal in the library",
        service_id=wifi_service_id(uow),
        impact=2,
        urgency=2,
    ).incident
    advice = service.assignment_advice(incident)
    assert advice.ranked
    assert advice.ranked[0].score >= advice.ranked[-1].score
    assert any("capacity free" in reason for reason in advice.ranked[0].reasons)
