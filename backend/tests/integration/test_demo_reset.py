"""``make demo-reset`` (P5.5, blueprint §14): the state every demo take starts from.

One full reset is a few seconds of work (the whole 420-incident history), so the database is
reset once per module and the tests read what it left behind.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select

from app.core.clock import FakeClock
from app.core.config import AppEnv, Settings
from app.demo import (
    DEMO_EMPLOYEE,
    DEMO_TECHNICIAN,
    OTHER_EMPLOYEE,
    DemoReport,
    DemoResetRefusedError,
    migrate,
    reset,
    seed_if_empty,
    wipe,
)
from app.domain.states import IncidentStatus
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import IncidentRow, NotificationRow
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork, make_session_factory
from app.services.incident_service import IncidentService
from app.services.sla_monitor import SLAMonitor

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Settings, Engine]]:
    """Like conftest's ``database_url``, but once for the module."""
    url = os.environ.get("TEST_DATABASE_URL") or (
        f"sqlite:///{tmp_path_factory.mktemp('demo') / 'demo.db'}"
    )
    settings = Settings(app_env=AppEnv.DEMO, database_url=url, _env_file=None)
    engine = make_engine(url)
    yield settings, engine
    wipe(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture(scope="module")
def report(database: tuple[Settings, Engine], clock: FakeClock) -> DemoReport:
    settings, _ = database
    reset(settings, clock)  # a second reset must start from scratch, not add to the first
    return reset(settings, clock)


@pytest.fixture
def uow(database: tuple[Settings, Engine], clock: FakeClock) -> Iterator[SqlAlchemyUnitOfWork]:
    unit = SqlAlchemyUnitOfWork(make_session_factory(database[1]), clock)
    yield unit
    unit.close()


def test_a_reset_starts_from_scratch_every_time(
    report: DemoReport, uow: SqlAlchemyUnitOfWork
) -> None:
    incidents = int(uow.session.scalar(select(func.count()).select_from(IncidentRow)) or 0)
    assert incidents == 420 + len(report.staged)
    assert "420 incidents (written)" in report.seed_summary


def test_the_history_is_caught_up_so_the_first_live_tick_is_quiet(
    report: DemoReport, uow: SqlAlchemyUnitOfWork, clock: FakeClock
) -> None:
    """The catch-up tick records the backlog; the next real tick has nothing left to do."""
    assert report.catch_up.breached
    assert report.catch_up.escalations
    assert report.catch_up.auto_closed

    after = SLAMonitor(uow, clock).tick()

    assert after.did_nothing


def test_the_catch_up_notifies_nobody(report: DemoReport, uow: SqlAlchemyUnitOfWork) -> None:
    """Only the staged reports, made through the facade, leave notifications behind."""
    staged = {s.incident_id for s in report.staged}
    notified = set(uow.session.scalars(select(NotificationRow.incident_id)).all())
    assert notified <= staged


def test_workflow_2_starts_in_the_demo_technicians_queue(
    report: DemoReport, uow: SqlAlchemyUnitOfWork
) -> None:
    workflow_2 = next(s for s in report.staged if s.workflow.startswith("Workflow 2"))
    incident = uow.incidents.get(workflow_2.incident_id)

    assert incident.reporter_id == DEMO_EMPLOYEE
    assert incident.assignee_id == DEMO_TECHNICIAN
    assert incident.status is IncidentStatus.ASSIGNED
    assert workflow_2.priority == "P4"  # a long SLA, so ×10 cannot breach it before the take


def test_workflow_1s_report_is_offered_the_staged_look_alike(
    report: DemoReport, uow: SqlAlchemyUnitOfWork, clock: FakeClock
) -> None:
    """§6.2: the live report shows the "similar open incident" hint while it is typed."""
    workflow_1 = next(s for s in report.staged if s.workflow.startswith("Workflow 1"))
    assert uow.incidents.get(workflow_1.incident_id).reporter_id == OTHER_EMPLOYEE
    fee_portal = next(s.id for s in uow.catalogue.services() if s.name == "Fee Payment Portal")
    clock.advance(timedelta(minutes=30))  # some clock time passes before the take

    check = IncidentService(uow, clock).similar_incidents(
        uow.users.get(DEMO_EMPLOYEE),
        title="Fee payment portal is down",
        description="Payment fails with an error when I pay my fees.",
        service_id=fee_portal,
    )

    assert workflow_1.incident_id in [c.incident.id for c in check.candidates]


def test_a_production_database_is_never_wiped() -> None:
    settings = Settings(
        app_env=AppEnv.PROD,
        database_url="sqlite://",
        jwt_secret="x" * 48,
        cors_origins=["https://i-itsm-web.onrender.com"],
        _env_file=None,
    )
    with pytest.raises(DemoResetRefusedError):
        reset(settings, FakeClock(NOW))


def test_a_first_start_seeds_once_and_catches_up(tmp_path_factory: pytest.TempPathFactory) -> None:
    """SEED_ON_START: the first start seeds quietly, every later start changes nothing."""
    url = f"sqlite:///{tmp_path_factory.mktemp('first') / 'first.db'}"
    settings = Settings(app_env=AppEnv.DEV, database_url=url, _env_file=None)
    clock = FakeClock(NOW)
    migrate(url)

    first = seed_if_empty(settings, clock)
    again = seed_if_empty(settings, clock)

    assert "420 incidents (written)" in first
    assert "breached" in first
    assert again == "seed: already seeded; nothing changed"
    engine = make_engine(url)
    unit = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
    try:
        assert SLAMonitor(unit, clock).tick().did_nothing
    finally:
        unit.close()
        engine.dispose()
