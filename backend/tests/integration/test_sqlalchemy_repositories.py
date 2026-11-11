"""Behaviour only the database can show: optimistic locking, UTC storage and the ID counter.

The contract suite (``tests/contract``) proves the SQL repositories behave like the in-memory
ones. These tests cover what memory cannot: two transactions racing on one row, timestamps
crossing a driver that has no time zone, and a counter that outlives the session.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError, StatementError

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService, Skill
from app.domain.errors import ConcurrentModificationError
from app.domain.incident import Incident, IncidentFactory
from app.domain.permissions import Role
from app.domain.users import Technician, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base, IncidentRow, UserRow
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    made = make_engine(database_url)
    Base.metadata.drop_all(made)
    create_schema(made)
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def unit_of_work(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    sessions = make_session_factory(engine)
    uow = SqlAlchemyUnitOfWork(sessions, FakeClock(NOW))
    yield uow
    uow.close()


def seeded_incident(uow: SqlAlchemyUnitOfWork, clock: FakeClock) -> Incident:
    uow.catalogue.save_service(ITService(1, "Campus Wi-Fi", criticality=3))
    uow.catalogue.save_category(Category(1, "Network"))
    uow.users.add(UserFactory.create(Role.EMPLOYEE, user_id=1, email="e@campus.edu", full_name="E"))
    uow.users.add(
        UserFactory.create(Role.TECHNICIAN, user_id=2, email="t@campus.edu", full_name="T")
    )
    incident = IncidentFactory.create(
        sequence=uow.incidents.next_sequence(2026),
        clock=clock,
        reporter_id=1,
        title="Wi-Fi down",
        description="No signal in the library",
        service_id=1,
        impact=2,
        urgency=2,
    )
    uow.incidents.add(incident)
    uow.commit()
    return incident


def test_a_second_writer_gets_a_conflict_instead_of_overwriting(engine: Engine) -> None:
    """Optimistic locking on ``incidents.version`` (blueprint §9; the API answers 409)."""
    sessions = make_session_factory(engine)
    clock = FakeClock(NOW)
    first = SqlAlchemyUnitOfWork(sessions, clock)
    incident = seeded_incident(first, clock)
    second = SqlAlchemyUnitOfWork(sessions, clock)

    mine = first.incidents.get(incident.id)
    theirs = second.incidents.get(incident.id)

    mine.classify(1, None, clock)
    first.incidents.save(mine)
    first.commit()

    theirs.add_note(2, clock, "Looking into it")
    with pytest.raises(ConcurrentModificationError):
        second.incidents.save(theirs)
    second.rollback()

    assert first.incidents.get(incident.id).category_id == 1
    first.close()
    second.close()


def test_timestamps_come_back_as_aware_utc(unit_of_work: SqlAlchemyUnitOfWork) -> None:
    clock = FakeClock(NOW)
    incident = seeded_incident(unit_of_work, clock)
    stored = unit_of_work.incidents.get(incident.id)
    assert stored.created_at == NOW
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == timedelta(0)


def test_a_naive_timestamp_is_refused_by_the_column_type(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    clock = FakeClock(NOW)
    seeded_incident(unit_of_work, clock)
    row = unit_of_work.session.scalars(select(IncidentRow)).one()
    row.acknowledged_at = datetime(2026, 11, 6, 9, 30)  # noqa: DTZ001 - the point of the test
    with pytest.raises(StatementError, match="timezone-aware"):
        unit_of_work.session.flush()
    unit_of_work.rollback()


def test_the_incident_counter_survives_a_new_session(engine: Engine) -> None:
    sessions = make_session_factory(engine)
    first = SqlAlchemyUnitOfWork(sessions, FakeClock(NOW))
    assert [first.incidents.next_sequence(2026) for _ in range(3)] == [1, 2, 3]
    first.commit()
    first.close()

    second = SqlAlchemyUnitOfWork(sessions, FakeClock(NOW))
    assert second.incidents.next_sequence(2026) == 4
    assert second.incidents.next_sequence(2027) == 1
    second.close()


def test_an_uncommitted_change_is_rolled_back(engine: Engine) -> None:
    sessions = make_session_factory(engine)
    clock = FakeClock(NOW)
    uow = SqlAlchemyUnitOfWork(sessions, clock)
    incident = seeded_incident(uow, clock)

    loaded = uow.incidents.get(incident.id)
    loaded.classify(1, None, clock)
    uow.incidents.save(loaded)
    uow.rollback()
    uow.close()

    fresh = SqlAlchemyUnitOfWork(sessions, clock)
    assert fresh.incidents.get(incident.id).category_id is None
    fresh.close()


def test_a_technicians_new_skill_joins_the_catalogue_without_colliding(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    """``technician_skills`` is a real foreign key, so a new skill becomes a catalogue row.

    The catalogue is seeded with explicit ids, and on PostgreSQL an explicit insert leaves the
    table's sequence at the start — so the id has to be chosen by the application, or the first
    skill a technician brings would collide with a seeded one.
    """
    unit_of_work.catalogue.save_skill(Skill(1, "networking"))
    unit_of_work.catalogue.save_skill(Skill(2, "database"))
    unit_of_work.commit()

    unit_of_work.users.add(
        UserFactory.create(
            Role.TECHNICIAN,
            user_id=40,
            email="t40@campus.edu",
            full_name="New Technician",
            skills=SkillSet({"printing", "networking"}),
        )
    )
    unit_of_work.commit()

    assert dict(unit_of_work.catalogue.skill_names()) == {
        1: "networking",
        2: "database",
        3: "printing",
    }
    stored = unit_of_work.users.get(40)
    assert isinstance(stored, Technician)
    assert stored.skills.names == ("networking", "printing")


def test_a_database_fault_becomes_a_503_not_a_500(unit_of_work: SqlAlchemyUnitOfWork) -> None:
    """§8: InfrastructureError → DatabaseFailure → 503 with rollback.

    Without the translation in SqlAlchemyUnitOfWork.commit, SQLAlchemy's own exception reaches
    the catch-all handler as an opaque 500 and the frontend's offline banner never fires.
    """
    from app.api.errors import status_for
    from app.domain.errors import DatabaseFailureError

    clock = FakeClock(NOW)
    seeded_incident(unit_of_work, clock)

    # Fail the commit the way a dropped connection would.
    original = unit_of_work.session.commit

    def broken() -> None:
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

    object.__setattr__(unit_of_work.session, "commit", broken)
    try:
        with pytest.raises(DatabaseFailureError) as caught:
            unit_of_work.commit()
    finally:
        object.__setattr__(unit_of_work.session, "commit", original)

    assert status_for(caught.value) == 503
    assert caught.value.code == "database_failure"
    assert "server closed the connection" not in caught.value.message


def test_a_key_collision_becomes_a_conflict_the_caller_can_retry(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    """Two writers racing for the same key is a 409, not a 500."""
    from app.api.errors import status_for
    from app.domain.errors import ConcurrentModificationError

    clock = FakeClock(NOW)
    seeded_incident(unit_of_work, clock)
    unit_of_work.users.add(
        UserFactory.create(Role.EMPLOYEE, user_id=77, email="race@campus.edu", full_name="R")
    )
    unit_of_work.commit()

    # A second account claiming the same email, as a lost race would produce.
    unit_of_work.session.add(
        UserRow(id=78, email="race@campus.edu", full_name="R2", role=Role.EMPLOYEE, created_at=NOW)
    )
    with pytest.raises(ConcurrentModificationError) as caught:
        unit_of_work.commit()
    assert status_for(caught.value) == 409
