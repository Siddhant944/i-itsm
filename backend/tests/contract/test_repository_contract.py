"""The contract every repository implementation must satisfy.

The same tests run against the in-memory repositories and the SQLAlchemy ones on SQLite, and
against PostgreSQL as well when TEST_DATABASE_URL points at one, so a rule proved in a unit
test cannot quietly break in the database.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.errors import IncidentNotFoundError, NotFoundError, ServiceNotFoundError
from app.domain.incident import Incident, IncidentFactory
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.repositories import UnitOfWork
from app.domain.sla import GOLD_TARGETS, SLATarget, SLATier, default_policies
from app.domain.states import IncidentStatus
from app.domain.users import Technician, UserFactory
from app.domain.value_objects import EmailAddress, SkillSet
from app.repositories.database import make_engine
from app.repositories.memory import InMemoryUnitOfWork
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
TARGET = SLATarget(timedelta(minutes=15), timedelta(hours=2))


class Backend(ABC):
    """One repository implementation, plus whatever rows its foreign keys require."""

    name: str

    @abstractmethod
    def unit_of_work(self) -> UnitOfWork: ...

    def close(self) -> None:
        """Release resources; only the SQL backends have an engine to dispose of."""
        return

    def with_catalogue(self, uow: UnitOfWork) -> UnitOfWork:
        """Insert the service and category an incident refers to, and commit them."""
        uow.catalogue.save_skill(Skill(1, "networking"))
        uow.catalogue.save_category(Category(1, "Network", required_skill_id=1))
        uow.catalogue.save_service(ITService(1, "Campus Wi-Fi", criticality=3))
        uow.commit()
        return uow


class MemoryBackend(Backend):
    name = "memory"

    def unit_of_work(self) -> UnitOfWork:
        return InMemoryUnitOfWork()


class SqlBackend(Backend):
    """SQLAlchemy on the database TEST_DATABASE_URL names, or a throwaway SQLite file."""

    name = "sqlalchemy"

    def __init__(self, database_url: str) -> None:
        self.__engine: Engine = make_engine(database_url)
        self.__drop_first(database_url)
        create_schema(self.__engine)
        self.__sessions = make_session_factory(self.__engine)

    def __drop_first(self, database_url: str) -> None:
        if not database_url.startswith("sqlite"):  # a shared PostgreSQL needs a clean slate
            from app.repositories.sqlalchemy.models import Base

            Base.metadata.drop_all(self.__engine)

    def unit_of_work(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self.__sessions, FakeClock(NOW))

    def close(self) -> None:
        self.__engine.dispose()


@pytest.fixture(params=["memory", "sqlalchemy"])
def backend(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Backend]:
    if request.param == "memory":
        made: Backend = MemoryBackend()
    else:
        url = os.environ.get("TEST_DATABASE_URL") or (
            f"sqlite:///{tmp_path_factory.mktemp('contract') / 'contract.db'}"
        )
        made = SqlBackend(url)
    yield made
    made.close()


@pytest.fixture
def uow(backend: Backend) -> Iterator[UnitOfWork]:
    unit = backend.unit_of_work()
    yield unit
    unit.rollback()


def reporter(uow: UnitOfWork, user_id: int = 1) -> None:
    uow.users.add(
        UserFactory.create(
            Role.EMPLOYEE, user_id=user_id, email=f"e{user_id}@campus.edu", full_name="E"
        )
    )


def new_incident(uow: UnitOfWork, clock: FakeClock, reporter_id: int = 1) -> Incident:
    return IncidentFactory.create(
        sequence=uow.incidents.next_sequence(2026),
        clock=clock,
        reporter_id=reporter_id,
        title="Wi-Fi down",
        description="No signal in the library",
        service_id=1,
        impact=2,
        urgency=2,
    )


# ---------------------------------------------------------------- incidents
def test_incidents_round_trip_and_are_listed_by_reporter(backend: Backend, uow: UnitOfWork) -> None:
    clock = FakeClock(NOW)
    backend.with_catalogue(uow)
    with uow:
        reporter(uow)
        incident = new_incident(uow, clock)
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
    with pytest.raises(ServiceNotFoundError):
        uow.catalogue.get_service(404)
    with pytest.raises(NotFoundError):
        uow.catalogue.get_category(404)
    with pytest.raises(NotFoundError):
        uow.catalogue.get_team(404)


def test_a_saved_incident_keeps_its_whole_history(backend: Backend, uow: UnitOfWork) -> None:
    clock = FakeClock(NOW)
    backend.with_catalogue(uow)
    reporter(uow)
    uow.users.add(
        UserFactory.create(Role.TECHNICIAN, user_id=2, email="t@campus.edu", full_name="T")
    )
    incident = new_incident(uow, clock)
    incident.apply_sla(TARGET)
    uow.incidents.add(incident)
    uow.commit()

    loaded = uow.incidents.get(incident.id)
    loaded.classify(1, None, clock)
    loaded.assign(2, None, clock)
    clock.advance(timedelta(minutes=10))
    loaded.acknowledge(2, clock)
    loaded.start(2, clock)
    loaded.add_note(2, clock, "Rebooted the access point")
    loaded.hold(2, clock, "Which building?")
    clock.advance(timedelta(minutes=20))
    loaded.provide_info(1, clock, "Library, first floor")
    loaded.resolve(2, clock, "Replaced the access point")
    uow.incidents.save(loaded)
    uow.commit()

    stored = uow.incidents.get(incident.id)
    assert stored.status is IncidentStatus.RESOLVED
    assert [note.text for note in stored.notes] == [
        "Rebooted the access point",
        "Which building?",
        "Library, first floor",
    ]
    assert stored.resolution is not None
    assert stored.resolution.summary == "Replaced the access point"
    assert stored.acknowledged_at == NOW + timedelta(minutes=10)
    assert stored.sla_clock is not None
    assert stored.sla_clock.paused_accumulated == timedelta(minutes=20)
    assert stored.sla_clock.response_met is True
    assert stored.sla_clock.resolution_elapsed(clock.now()) == timedelta(minutes=10)


def test_a_rejected_fix_clears_the_stored_resolution(backend: Backend, uow: UnitOfWork) -> None:
    clock = FakeClock(NOW)
    backend.with_catalogue(uow)
    reporter(uow)
    uow.users.add(
        UserFactory.create(Role.TECHNICIAN, user_id=2, email="t@campus.edu", full_name="T")
    )
    incident = new_incident(uow, clock)
    incident.classify(1, None, clock)
    incident.assign(2, None, clock)
    incident.acknowledge(2, clock)
    incident.start(2, clock)
    incident.resolve(2, clock, "Rebooted")
    uow.incidents.add(incident)
    uow.commit()
    assert uow.incidents.get(incident.id).resolution is not None

    loaded = uow.incidents.get(incident.id)
    loaded.reject(1, clock, "Still broken")
    uow.incidents.save(loaded)
    uow.commit()

    stored = uow.incidents.get(incident.id)
    assert stored.resolution is None
    assert stored.resolved_at is None
    assert stored.reopen_count == 1
    assert stored.status is IncidentStatus.IN_PROGRESS
    assert [note.text for note in stored.notes] == ["Fix rejected: Still broken"]


def test_verified_feedback_is_stored_once(backend: Backend, uow: UnitOfWork) -> None:
    clock = FakeClock(NOW)
    backend.with_catalogue(uow)
    reporter(uow)
    uow.users.add(
        UserFactory.create(Role.TECHNICIAN, user_id=2, email="t@campus.edu", full_name="T")
    )
    incident = new_incident(uow, clock)
    incident.classify(1, None, clock)
    incident.assign(2, None, clock)
    incident.acknowledge(2, clock)
    incident.start(2, clock)
    incident.resolve(2, clock, "Rebooted")
    incident.verify(1, clock, rating=4, comment="Quick")
    uow.incidents.add(incident)
    uow.commit()

    stored = uow.incidents.get(incident.id)
    assert stored.feedback is not None
    assert (stored.feedback.rating, stored.feedback.comment) == (4, "Quick")

    stored.close(2, clock)
    uow.incidents.save(stored)
    uow.commit()
    assert uow.incidents.get(incident.id).feedback == stored.feedback


def test_saving_an_unknown_incident_or_user_raises_not_found(uow: UnitOfWork) -> None:
    clock = FakeClock(NOW)
    ghost = IncidentFactory.create(
        sequence=999,
        clock=clock,
        reporter_id=1,
        title="Ghost",
        description="Never stored",
        service_id=1,
        impact=1,
        urgency=1,
    )
    with pytest.raises(IncidentNotFoundError):
        uow.incidents.save(ghost)
    with pytest.raises(NotFoundError):
        uow.users.save(
            UserFactory.create(Role.EMPLOYEE, user_id=404, email="g@campus.edu", full_name="G")
        )


# ---------------------------------------------------------------- users
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
    uow.commit()
    found = uow.users.find_by_email(EmailAddress("E@campus.edu"))
    assert found is not None
    assert found.id == 1
    assert uow.users.find_by_email(EmailAddress("x@campus.edu")) is None
    assert [t.id for t in uow.users.technicians()] == [2]


def test_a_technicians_skills_experience_and_availability_round_trip(uow: UnitOfWork) -> None:
    uow.users.add(
        UserFactory.create(
            Role.TECHNICIAN,
            user_id=3,
            email="t@campus.edu",
            full_name="T",
            skills=SkillSet({"networking", "database"}),
            experience_level=3,
            team_id=None,
        )
    )
    uow.commit()
    loaded = uow.users.get(3)
    assert isinstance(loaded, Technician)
    assert loaded.skills.names == ("database", "networking")
    assert (loaded.experience_level, loaded.available, loaded.role) == (3, True, Role.TECHNICIAN)

    loaded.update_skills(SkillSet({"networking", "printers"}))
    loaded.set_experience_level(2)
    loaded.mark_unavailable()
    loaded.deactivate()
    uow.users.save(loaded)
    uow.commit()

    stored = uow.users.get(3)
    assert isinstance(stored, Technician)
    assert stored.skills.names == ("networking", "printers")
    assert (stored.experience_level, stored.available, stored.active) == (2, False, False)


def test_an_employee_is_rebuilt_as_an_employee(uow: UnitOfWork) -> None:
    uow.users.add(
        UserFactory.create(Role.ADMINISTRATOR, user_id=9, email="a@campus.edu", full_name="A")
    )
    uow.commit()
    admin = uow.users.get(9)
    assert admin.role is Role.ADMINISTRATOR
    assert not isinstance(admin, Technician)


# ---------------------------------------------------------------- catalogue
def test_the_catalogue_round_trips_skills_categories_and_services(uow: UnitOfWork) -> None:
    uow.catalogue.save_skill(Skill(1, "Networking"))
    uow.catalogue.save_skill(Skill(2, "database"))
    category = Category(
        1, "Network", required_skill_id=1, keywords=("wifi", "signal"), minimum_priority=Priority.P2
    )
    uow.catalogue.save_category(category)
    service = ITService(
        1, "Fee Payment Portal", criticality=3, required_skill_id=2, depends_on=(2, 3)
    )
    uow.catalogue.save_service(ITService(2, "Database Cluster", criticality=3))
    uow.catalogue.save_service(ITService(3, "Network Core", criticality=2))
    uow.catalogue.save_service(service)
    uow.commit()

    assert uow.catalogue.skill_names() == {1: "networking", 2: "database"}
    stored_category = uow.catalogue.get_category(1)
    assert stored_category.keywords == ("signal", "wifi")
    assert stored_category.minimum_priority is Priority.P2
    assert stored_category.required_skill_id == 1

    stored_service = uow.catalogue.get_service(1)
    assert list(stored_service.depends_on) == [2, 3]
    assert stored_service.required_skill_id == 2
    assert stored_service.sla_tier.value == SLATier.GOLD.value
    assert stored_service.tier_overridden is False
    assert [s.id for s in uow.catalogue.services()] == [1, 2, 3]


def test_editing_the_catalogue_replaces_what_was_stored(uow: UnitOfWork) -> None:
    uow.catalogue.save_service(ITService(2, "Database", criticality=3))
    uow.catalogue.save_service(ITService(1, "Portal", criticality=3, depends_on=(2,)))
    uow.catalogue.save_category(Category(1, "Network", keywords=("wifi",)))
    uow.commit()

    service = uow.catalogue.get_service(1)
    service.remove_dependency(2)
    service.set_sla_tier(SLATier.BRONZE)
    service.retire()
    uow.catalogue.save_service(service)
    category = uow.catalogue.get_category(1)
    category.rename("Networking")
    category.set_minimum_priority(None)
    category.retire()
    uow.catalogue.save_category(category)
    uow.commit()

    stored = uow.catalogue.get_service(1)
    assert stored.depends_on == ()
    assert stored.sla_tier.value == SLATier.BRONZE.value
    assert stored.tier_overridden is True
    assert stored.active is False
    assert [s.id for s in uow.catalogue.services(active_only=True)] == [2]
    assert uow.catalogue.categories(active_only=True) == ()
    assert uow.catalogue.get_category(1).name == "Networking"


def test_a_team_keeps_its_lead_and_its_technicians(uow: UnitOfWork) -> None:
    uow.catalogue.save_team(Team(1, "Network Operations"))
    uow.users.add(
        UserFactory.create(
            Role.TEAM_LEAD, user_id=5, email="l@campus.edu", full_name="L", team_id=1
        )
    )
    uow.users.add(
        UserFactory.create(
            Role.TECHNICIAN, user_id=6, email="t@campus.edu", full_name="T", team_id=1
        )
    )
    uow.commit()

    team = uow.catalogue.get_team(1)
    assert list(team.member_ids) == [5, 6]
    team.set_lead(5)
    uow.catalogue.save_team(team)
    uow.commit()
    assert uow.catalogue.get_team(1).lead_id == 5
    assert [t.id for t in uow.catalogue.teams()] == [1]


def test_the_sla_policy_table_round_trips_and_falls_back_to_gold(uow: UnitOfWork) -> None:
    uow.catalogue.save_policies(default_policies())
    uow.commit()
    book = uow.catalogue.policy_book()
    assert book.target_for(SLATier.SILVER, Priority.P1) == SLATarget(
        timedelta(minutes=10), timedelta(hours=1)
    )

    uow.catalogue.save_policies({(SLATier.GOLD, Priority.P1): GOLD_TARGETS[Priority.P1]})
    uow.commit()
    target, used_default = uow.catalogue.policy_book().target_or_default(
        SLATier.BRONZE, Priority.P3
    )
    assert used_default is True
    assert target == GOLD_TARGETS[Priority.P3]
