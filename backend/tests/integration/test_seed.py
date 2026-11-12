"""``make seed`` must give a reviewer a database worth looking at (blueprint §9, P2.2).

The seed is deterministic for a given clock, idempotent, and leaves every dashboard with
something to show: open queues, closed work, feedback, SLA breaches and linked duplicates.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select

from app.core.clock import FakeClock
from app.domain.incident import CancelReason, IncidentFactory
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.states import IncidentStatus
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import (
    Base,
    CategoryRow,
    FeedbackRow,
    IncidentRow,
    ResolutionRow,
    ServiceDependencyRow,
    ServiceRow,
    SLAPolicyRow,
    TeamRow,
    TechnicianProfileRow,
    TechnicianSkillRow,
    UserRow,
    WorkNoteRow,
)
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.seed import campus, people, seed

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
SMALL = 60  # enough to exercise every outcome without slowing the suite down


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
    uow = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    yield uow
    uow.close()


def count(uow: SqlAlchemyUnitOfWork, model: type[Base]) -> int:
    return int(uow.session.scalar(select(func.count()).select_from(model)) or 0)


def test_the_catalogue_and_the_demo_accounts_are_seeded(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    seed(unit_of_work, FakeClock(NOW), history=SMALL)

    assert count(unit_of_work, ServiceRow) == len(campus.SERVICES)
    assert count(unit_of_work, CategoryRow) == len(campus.CATEGORIES)
    assert count(unit_of_work, TeamRow) == len(campus.TEAMS)
    assert count(unit_of_work, UserRow) == len(people.ALL_USERS)
    assert count(unit_of_work, SLAPolicyRow) == 12  # one per tier and priority (§5.2)
    assert count(unit_of_work, ServiceDependencyRow) > 0
    assert count(unit_of_work, TechnicianSkillRow) > 0
    assert count(unit_of_work, TechnicianProfileRow) == sum(
        1 for u in people.ALL_USERS if u.role in (Role.TECHNICIAN, Role.TEAM_LEAD)
    )

    roles = {user.role for user in unit_of_work.session.scalars(select(UserRow)).all()}
    assert roles == set(Role)  # a reviewer can sign in as every portal

    teams = unit_of_work.catalogue.teams()
    assert all(team.lead_id is not None for team in teams)
    assert all(team.lead_id in team.member_ids for team in teams)


def test_the_fee_portal_depends_on_the_database_cluster(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    """The §6.2 correlation demo needs this edge to exist."""
    seed(unit_of_work, FakeClock(NOW), history=0)
    by_name = {service.name: service for service in unit_of_work.catalogue.services()}
    portal = by_name["Fee Payment Portal"]
    assert by_name["Database Cluster"].id in portal.depends_on
    assert by_name["Campus Network Core"].id in portal.depends_on


def test_the_history_fills_every_dashboard(unit_of_work: SqlAlchemyUnitOfWork) -> None:
    report = seed(unit_of_work, FakeClock(NOW), history=SMALL)
    assert report.incidents == SMALL
    assert report.history_written is True

    rows = unit_of_work.session.scalars(select(IncidentRow)).all()
    statuses = {row.status for row in rows}
    assert IncidentStatus.CLOSED in statuses
    assert statuses & {IncidentStatus.ASSIGNED, IncidentStatus.ACKNOWLEDGED}
    assert statuses & {IncidentStatus.IN_PROGRESS, IncidentStatus.ON_HOLD}
    assert {row.priority for row in rows} == set(Priority)

    assert count(unit_of_work, WorkNoteRow) > 0
    assert count(unit_of_work, ResolutionRow) > 0
    assert count(unit_of_work, FeedbackRow) > 0  # CSAT has something to average

    # Metrics need both sides of every ratio.
    assert any(row.sla_response_met is False for row in rows)  # compliance below 100 %
    assert any(row.sla_response_met is True for row in rows)
    assert any(row.acknowledged_at is not None for row in rows)  # MTTA
    assert any(row.resolved_at is not None for row in rows)  # MTTR
    assert any(row.reopen_count > 0 for row in rows)  # reopen rate

    oldest = min(row.created_at for row in rows)
    assert NOW - oldest <= timedelta(days=121)
    assert all(row.created_at <= NOW for row in rows)


def test_cancelled_duplicates_point_at_their_parent(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    seed(unit_of_work, FakeClock(NOW), history=200)
    rows = unit_of_work.session.scalars(select(IncidentRow)).all()
    by_id = {row.id: row for row in rows}
    duplicates = [row for row in rows if row.cancel_reason is CancelReason.DUPLICATE]
    assert duplicates, "the duplicate demo (D-005) needs at least one linked pair"
    for row in duplicates:
        assert row.parent_id in by_id
        assert by_id[row.parent_id].service_id == row.service_id


def test_seeding_twice_changes_nothing(unit_of_work: SqlAlchemyUnitOfWork) -> None:
    first = seed(unit_of_work, FakeClock(NOW), history=SMALL)
    before = _fingerprint(unit_of_work)

    second = seed(unit_of_work, FakeClock(NOW + timedelta(days=3)), history=SMALL)
    assert second.history_written is False
    assert second.incidents == first.incidents
    assert _fingerprint(unit_of_work) == before


def test_the_same_clock_seeds_the_same_history(
    engine: Engine, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other_url = f"sqlite:///{tmp_path_factory.mktemp('seed') / 'other.db'}"
    other_engine = make_engine(other_url)
    create_schema(other_engine)

    fingerprints = []
    for target in (engine, other_engine):
        uow = SqlAlchemyUnitOfWork(make_session_factory(target), FakeClock(NOW))
        seed(uow, FakeClock(NOW), history=SMALL)
        fingerprints.append(_fingerprint(uow))
        uow.close()
    other_engine.dispose()

    assert fingerprints[0] == fingerprints[1]


def test_the_next_reported_incident_continues_the_series(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    """The seed must leave the per-year counter past its own ids, or the next report collides."""
    seed(unit_of_work, FakeClock(NOW), history=SMALL)
    clock = FakeClock(NOW)
    incident = IncidentFactory.create(
        sequence=unit_of_work.incidents.next_sequence(NOW.year),
        clock=clock,
        reporter_id=people.EMPLOYEES[0].user_id,
        title="New report after seeding",
        description="Should not clash with the seeded ids",
        service_id=1,
        impact=2,
        urgency=2,
    )
    unit_of_work.incidents.add(incident)
    unit_of_work.commit()
    assert unit_of_work.incidents.get(incident.id).title == "New report after seeding"


def test_the_demo_accounts_have_no_credentials_until_a_hasher_is_given(
    unit_of_work: SqlAlchemyUnitOfWork,
) -> None:
    """P2.3 supplies Argon2; until then an account exists with no hash, never a fake one."""
    seed(unit_of_work, FakeClock(NOW), history=0)
    assert all(
        row.password_hash is None for row in unit_of_work.session.scalars(select(UserRow)).all()
    )

    seed(unit_of_work, FakeClock(NOW), hash_password=lambda raw: f"fake${raw}", history=0)
    hashes = {row.password_hash for row in unit_of_work.session.scalars(select(UserRow)).all()}
    assert hashes == {f"fake${people.DEMO_PASSWORD}"}


def _fingerprint(uow: SqlAlchemyUnitOfWork) -> list[tuple[object, ...]]:
    """Everything about the seeded incidents that two identical runs must agree on."""
    rows = uow.session.scalars(select(IncidentRow).order_by(IncidentRow.id)).all()
    return [
        (
            row.id,
            row.reporter_id,
            row.assignee_id,
            row.service_id,
            row.category_id,
            row.status,
            row.priority,
            row.created_at,
            row.resolved_at,
            row.closed_at,
            row.reopen_count,
            row.escalation_level,
            row.parent_id,
        )
        for row in rows
    ]


def test_the_command_line_entry_point_seeds_the_configured_database(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make seed`` runs ``python -m app.seed`` after the migrations."""
    from app.core.config import get_settings
    from app.seed.__main__ import main

    url = f"sqlite:///{tmp_path_factory.mktemp('cli') / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.ENV_FILE", tmp_path_factory.mktemp("noenv") / ".env")
    try:
        create_schema(make_engine(url))
        assert main() == 0
    finally:
        get_settings.cache_clear()

    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(IncidentRow))
        assert session.scalar(select(func.count()).select_from(UserRow)) == len(people.ALL_USERS)
    engine.dispose()


def test_seeding_only_if_empty_leaves_a_seeded_database_alone(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deployment seeds on every start (SEED_ON_START); the second start must change nothing."""
    from app.core.config import get_settings
    from app.core.security import FakePasswordHasher
    from app.domain.catalogue import Category
    from app.seed import __main__ as entry
    from app.seed.runner import already_seeded

    engine = make_engine(database_url)
    Base.metadata.drop_all(engine)
    create_schema(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
        assert already_seeded(uow) is False
        seed(uow, FakeClock(NOW), hash_password=FakePasswordHasher().hash, history=5)
        assert already_seeded(uow) is True
        uow.catalogue.save_category(Category(99, "Added by an admin"))
        uow.commit()
        uow.close()

        assert entry.main(["--if-empty"]) == 0
        assert "already seeded" in capsys.readouterr().out
        check = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
        assert check.catalogue.get_category(99).name == "Added by an admin"
        check.close()
    finally:
        get_settings.cache_clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_a_seeded_fix_fits_its_incidents_category(unit_of_work: SqlAlchemyUnitOfWork) -> None:
    """The suggested-fix panel (§6.1) quotes these, so a Wi-Fi ticket must not read like a
    database fix in the demo (P6 review)."""
    from app.seed.history import CATEGORY_FIXES

    seed(unit_of_work, FakeClock(NOW), history=SMALL)
    rows = unit_of_work.session.execute(
        select(CategoryRow.name, ResolutionRow.summary)
        .join(IncidentRow, IncidentRow.id == ResolutionRow.incident_id)
        .join(CategoryRow, CategoryRow.id == IncidentRow.category_id)
    ).all()
    assert rows
    for category, summary in rows:
        assert summary in CATEGORY_FIXES[category], (category, summary)
