"""Contract every repository implementation must satisfy (P2 adds the SQLAlchemy variant)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.core.clock import FakeClock
from app.domain.errors import IncidentNotFoundError, NotFoundError
from app.domain.incident import IncidentFactory
from app.domain.permissions import Role
from app.domain.repositories import UnitOfWork
from app.domain.users import UserFactory
from app.domain.value_objects import EmailAddress, SkillSet
from app.repositories.memory import InMemoryUnitOfWork

FACTORIES: dict[str, Callable[[], UnitOfWork]] = {"memory": InMemoryUnitOfWork}


@pytest.fixture(params=sorted(FACTORIES))
def uow(request: pytest.FixtureRequest) -> UnitOfWork:
    return FACTORIES[request.param]()


def test_incidents_round_trip_and_are_listed_by_reporter(uow: UnitOfWork) -> None:
    clock = FakeClock(datetime(2026, 11, 5, tzinfo=UTC))
    with uow:
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
    assert uow.incidents.get(incident.id).title == "Wi-Fi down"
    assert [i.id for i in uow.incidents.list_by_reporter(1)] == [incident.id]
    assert uow.incidents.list_by_reporter(2) == ()


def test_sequences_are_per_year(uow: UnitOfWork) -> None:
    assert [uow.incidents.next_sequence(2026) for _ in range(2)] == [1, 2]
    assert uow.incidents.next_sequence(2027) == 1


def test_missing_entities_raise_not_found(uow: UnitOfWork) -> None:
    with pytest.raises(IncidentNotFoundError):
        uow.incidents.get("INC-2026-9999")
    with pytest.raises(NotFoundError):
        uow.users.get(404)


def test_users_by_email_and_technician_listing(uow: UnitOfWork) -> None:
    uow.users.add(UserFactory.create(Role.EMPLOYEE, user_id=1, email="e@campus.edu", full_name="E"))
    uow.users.add(
        UserFactory.create(
            Role.TEAM_LEAD,
            user_id=2,
            email="l@campus.edu",
            full_name="L",
            skills=SkillSet({"networking"}),
        )
    )
    found = uow.users.find_by_email(EmailAddress("E@campus.edu"))
    assert found is not None
    assert found.id == 1
    assert uow.users.find_by_email(EmailAddress("x@campus.edu")) is None
    assert [t.id for t in uow.users.technicians()] == [2]
