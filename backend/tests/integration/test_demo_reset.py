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
    CATCH_UP_MARKER,
    DEMO_EMPLOYEE,
    DEMO_TECHNICIAN,
    OTHER_EMPLOYEE,
    DemoReport,
    DemoResetRefusedError,
    _RehearsalUnitOfWork,
    is_fresh,
    is_local_database,
    migrate,
    rehearse,
    reset,
    seed_if_empty,
    wipe,
)
from app.domain.dependency_graph import LIVE_STATUSES
from app.domain.priority import Priority
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.search import IncidentQuery
from app.domain.states import IncidentStatus
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import IncidentRow, NotificationRow, SystemConfigRow
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


def test_old_outages_are_settled_so_the_health_map_starts_green(
    report: DemoReport, uow: SqlAlchemyUnitOfWork, clock: FakeClock
) -> None:
    """D-041: no P1 or P2 is live before the take, so Workflow 3's outage is the red one."""
    assert report.settled.resolved > 0
    still_live = uow.incidents.search(
        IncidentQuery(statuses=tuple(sorted(LIVE_STATUSES)), priorities=(Priority.P1, Priority.P2)),
        clock.now(),
    )
    assert still_live.total == 0
    assert "old outages settled" in report.summary()


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
    """SEED_ON_START: the first start seeds quietly, every later start changes nothing.

    Runs last in the module on TEST_DATABASE_URL too, so CI's PostgreSQL leg covers the path a
    deployment takes; the module's own teardown wipes it afterwards.
    """
    url = os.environ.get("TEST_DATABASE_URL") or (
        f"sqlite:///{tmp_path_factory.mktemp('first') / 'first.db'}"
    )
    settings = Settings(app_env=AppEnv.DEV, database_url=url, _env_file=None)
    clock = FakeClock(NOW)
    engine = make_engine(url)
    wipe(engine)
    migrate(url)

    first = seed_if_empty(settings, clock)
    again = seed_if_empty(settings, clock)

    assert "420 incidents (written)" in first
    assert "breached" in first
    assert again == "seed: already seeded; nothing changed"
    unit = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
    try:
        assert SLAMonitor(unit, clock).tick().did_nothing
        # A start that seeded but never caught up (the connection dropped) catches up next time.
        unit.session.delete(unit.session.get(SystemConfigRow, CATCH_UP_MARKER))
        unit.commit()
    finally:
        unit.close()
    assert seed_if_empty(settings, clock).startswith("history caught up")
    engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@ep-cool-name.eu-central-1.aws.neon.tech/itsm?sslmode=require",
        "postgresql+psycopg://u:p@10.0.0.5:5432/itsm",
    ],
)
def test_a_remote_database_is_never_wiped_by_make_demo_reset(url: str) -> None:
    """P5 review: make demo-reset forces APP_ENV=demo, so the env check alone could never fire.

    The guard therefore looks at the database itself: only SQLite and a local or Compose host
    are reset unless the caller says otherwise (the image's DEMO_RESET_ON_START does).
    """
    settings = Settings(app_env=AppEnv.DEMO, database_url=url, _env_file=None)
    with pytest.raises(DemoResetRefusedError, match="allow-remote-database"):
        reset(settings, FakeClock(NOW))


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./itsm.db",
        "postgresql+psycopg://itsm:itsm@localhost:5432/itsm",
        "postgresql+psycopg://itsm:itsm@127.0.0.1/itsm",
        "postgresql+psycopg://itsm:itsm@postgres:5432/itsm",
    ],
)
def test_a_local_database_may_be_reset(url: str) -> None:
    assert is_local_database(url)


# ---------------------------------------------------------------- D-043: the take, rehearsed
def test_the_reset_names_who_gets_each_scripted_report(report: DemoReport) -> None:
    plan = report.plan
    assert plan is not None
    assert plan.fresh
    assert plan.workflow1 is not None
    assert plan.workflow1.email == "sys2@campus.edu"
    assert plan.duplicate_holder is not None
    assert plan.duplicate_holder.email == "sys2@campus.edu"
    assert plan.database is not None
    assert plan.database.email == "sys1@campus.edu"
    assert [p.email for p in plan.escalations] == [
        "s.desk1@campus.edu",
        "admin@campus.edu",
        "manager@campus.edu",
    ]
    assert "Meera Joshi" in [p.name for p in plan.reassign_to]
    assert "WHO GETS WHAT IN THE TAKE" in report.summary()


def test_the_rehearsal_is_repeatable_and_leaves_nothing_behind(
    report: DemoReport, uow: SqlAlchemyUnitOfWork
) -> None:
    before = int(uow.session.scalar(select(func.count()).select_from(IncidentRow)) or 0)
    again = rehearse(uow, NOW)
    after = int(uow.session.scalar(select(func.count()).select_from(IncidentRow)) or 0)
    assert again == report.plan
    assert after == before
    assert is_fresh(uow)


def test_a_report_made_after_the_reset_is_flagged(uow: SqlAlchemyUnitOfWork) -> None:
    """A dry run without a second reset is what moved Workflow 1 from Meera to Rohit."""
    dry = _RehearsalUnitOfWork(uow)
    services = {s.name: s.id for s in uow.catalogue.services()}
    IncidentService(dry, FakeClock(NOW), advisor=RuleBasedAdvisor()).report(
        uow.users.get(OTHER_EMPLOYEE),
        title="A stray test report",
        description="Sent before the take without resetting.",
        service_id=services["Fee Payment Portal"],
        impact=3,
        urgency=3,
    )
    plan = rehearse(uow, NOW)  # rolls the stray report back along with its own steps
    assert not plan.fresh
    assert "Run demo-reset again" in plan.summary()
    assert is_fresh(uow)
