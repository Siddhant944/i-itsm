"""``make demo-reset`` (P5.5, blueprint §14): the state every demo take starts from.

``python -m app.demo`` wipes the database at DATABASE_URL, migrates it to head, seeds it, and
then does the two things a plain seed cannot:

1. **Catches the monitor up.** The seeded history was generated, not watched, so on its own the
   first tick after a seed would record ~170 breaches, ~60 escalations and ~30 auto-closes at
   once, in the middle of the recording. One quiet tick here records them now, with no
   notifications, exactly as the monitor would have done had it been running all along.
2. **Settles the old outages** (D-041): the history's open P1 and P2 incidents are resolved by
   their assignees (or cancelled while unassigned), so the health map starts green and
   Workflow 3's database outage is the one red service on screen.
3. **Stages the workflows' starting points** through the IncidentService facade, so each one
   is classified, prioritised, put on its SLA, assigned and audited like any other report:
   - Workflow 1: an open, low-priority Fee Payment Portal report from another employee, so the
     live report shows the "similar open incident" hint while it is typed (§6.2).
   - Workflow 2: a low-priority Wi-Fi incident from the demo employee in the demo technician's
     queue, ready to acknowledge.
   - Workflow 3 is reported live: a staged P1 would escalate under the ×10 clock before the
     take began (30, 60 and 90 real seconds; D-003).

``--seed-if-empty`` is the gentler half for a deployment's first start: it seeds a database
that was never seeded and catches the monitor up, and does nothing on every later start.

This module is a composition root like ``app.main``: it is the one place besides the seed CLI
that wires persistence, seed data and services together, and nothing imports it. It refuses to
run when ``APP_ENV=prod``.
"""

import argparse
from argparse import Namespace
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.engine.url import make_url

from app.core.clock import Clock, FakeClock, SystemClock
from app.core.config import AppEnv, Settings, get_settings
from app.core.security import Argon2PasswordHasher
from app.domain.dependency_graph import LIVE_STATUSES
from app.domain.errors import ITSMError
from app.domain.incident import CancelReason, Incident
from app.domain.priority import Priority
from app.domain.repositories import UnitOfWork
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.search import CSV_EXPORT_LIMIT, IncidentQuery
from app.domain.states import IncidentStatus
from app.domain.users import User
from app.domain.value_objects import EmailAddress
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base, IncidentRow, SystemConfigRow
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork, make_session_factory
from app.seed import people
from app.seed.runner import already_seeded, seed
from app.services.dispatcher import PostCommitDispatcher
from app.services.incident_service import IncidentService
from app.services.notifications import default_factory
from app.services.notifications.service import NotificationService
from app.services.sla_monitor import SLAMonitor, TickReport

BACKEND = Path(__file__).resolve().parents[1]
DEMO_EMPLOYEE = 1  # employee@campus.edu
DEMO_TECHNICIAN = 2  # technician@campus.edu
DEMO_LEAD = 3  # lead@campus.edu, the demo technician's Team Lead
OTHER_EMPLOYEE = people.EMPLOYEES[0].user_id
DEMO_ADMIN = 4  # admin@campus.edu
#: The staged incidents' titles; the rehearsal finds them by these (D-043).
LOOK_ALIKE_TITLE = "Fee payment portal page is very slow"
WIFI_TITLE = "Wi-Fi keeps dropping in the library reading room"
#: The script's live reports, exactly as the video script has them typed (D-043).
WORKFLOW1_REPORT = ("Fee payment page fails at checkout", "Fee Payment Portal", "Web Application")
DATABASE_REPORT = ("Database cluster not responding", "Database Cluster", "Database")
DATABASE_REPORTER = "employee@campus.edu"  # Devika reports it: one tab fewer
#: What settle() writes on the incidents it closes off, so the audit log says why.
SETTLED_SUMMARY = "Fixed before the demo: demo-reset settles old outages (D-041)."


#: Hosts a reset may wipe without being told twice: this machine, and Compose's database service.
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})
#: Written once the first seed's history has been caught up, so a failed catch-up is retried.
CATCH_UP_MARKER = "seed:caught-up"


class DemoResetRefusedError(ValueError):
    """Raised instead of wiping a database the reset must not touch.

    A command-line guard in a composition root, like the settings validators in
    ``app.core.config``: it never reaches the API, so it is not part of the ITSMError hierarchy
    (§8), which exists to be mapped to HTTP responses.
    """


def is_local_database(database_url: str) -> bool:
    """True for SQLite and for PostgreSQL on this machine or Compose's ``postgres`` service."""
    url = make_url(database_url)
    return url.get_backend_name() == "sqlite" or (url.host or "") in LOCAL_DATABASE_HOSTS


@dataclass(frozen=True, slots=True)
class StagedIncident:
    """One workflow's starting point, so the presenter knows where to find it."""

    workflow: str
    incident_id: str
    title: str
    priority: str
    assignee_id: int | None


@dataclass(frozen=True, slots=True)
class SettleReport:
    """How many old P1/P2 incidents were taken off the health map before the demo (D-041)."""

    resolved: int
    cancelled: int

    @property
    def summary(self) -> str:
        return (
            f"old outages settled: {self.resolved} P1/P2 resolved, {self.cancelled} cancelled,"
            " so the health map starts green"
        )


@dataclass(frozen=True, slots=True)
class DemoReport:
    seed_summary: str
    catch_up: TickReport
    settled: SettleReport
    staged: tuple[StagedIncident, ...]
    plan: "TakePlan | None" = None

    def summary(self) -> str:
        lines = [
            self.seed_summary,
            f"history caught up ({self.catch_up.summary}, no notifications sent)",
            self.settled.summary,
            *(
                f"staged for {s.workflow}: {s.incident_id} {s.priority} '{s.title}'"
                f" (assigned to user {s.assignee_id})"
                for s in self.staged
            ),
            f"demo accounts: employee, technician, lead, admin, manager @campus.edu,"
            f" password {people.DEMO_PASSWORD}",
        ]
        if self.plan is not None:
            lines.append(self.plan.summary())
        return "\n".join(lines)


# ---------------------------------------------------------------- the reset
def reset(settings: Settings, clock: Clock, *, allow_remote_database: bool = False) -> DemoReport:
    """Wipe, migrate, seed, catch up and stage the database ``settings`` names.

    Two guards, because ``make demo-reset`` sets ``APP_ENV=demo`` itself and so can never trip
    the first on its own (P5 review): never with ``APP_ENV=prod``, and never a database on
    another machine unless the caller asks for exactly that (the image's DEMO_RESET_ON_START).
    """
    if settings.app_env is AppEnv.PROD:
        msg = "demo-reset wipes the database; it never runs with APP_ENV=prod"
        raise DemoResetRefusedError(msg)
    if not allow_remote_database and not is_local_database(settings.database_url):
        host = make_url(settings.database_url).host
        msg = (
            f"refusing to wipe the database on {host}: demo-reset only wipes a local database."
            " If that really is a demo database, run python -m app.demo --allow-remote-database"
        )
        raise DemoResetRefusedError(msg)
    engine = make_engine(settings.database_url)
    try:
        wipe(engine)
        migrate(settings.database_url)
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
        try:
            seeded = seed(uow, clock, hash_password=Argon2PasswordHasher().hash)
            caught_up = catch_up(uow, clock)
            uow.session.add(SystemConfigRow(key=CATCH_UP_MARKER, value={}, updated_at=clock.now()))
            uow.commit()
            settled = settle(uow, clock)
            staged = stage(uow, clock)
            plan = rehearse(uow, clock.now())
        finally:
            uow.close()
    finally:
        engine.dispose()
    return DemoReport(seeded.summary(), caught_up, settled, staged, plan)


def seed_if_empty(settings: Settings, clock: Clock) -> str:
    """A deployment's first start (SEED_ON_START): seed a never-seeded database and catch up.

    Unlike :func:`reset` this wipes nothing and stages nothing, so it is safe in production and
    a no-op on every later start; the catch-up keeps the first live tick from notifying dozens
    of people about breaches that happened, in the generated history, months ago.

    The catch-up is recorded by a marker of its own, written only after the tick commits, so a
    start that seeded but failed to catch up (a dropped connection, say) catches up next time.
    """
    engine = make_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
        try:
            lines: list[str] = []
            if not already_seeded(uow):
                lines.append(seed(uow, clock, hash_password=Argon2PasswordHasher().hash).summary())
            if uow.session.get(SystemConfigRow, CATCH_UP_MARKER) is None:
                lines.append(f"history caught up ({catch_up(uow, clock).summary})")
                uow.session.add(
                    SystemConfigRow(key=CATCH_UP_MARKER, value={}, updated_at=clock.now())
                )
                uow.commit()
            return "\n".join(lines) or "seed: already seeded; nothing changed"
        finally:
            uow.close()
    finally:
        engine.dispose()


def wipe(engine: Engine) -> None:
    """Drop every table, including Alembic's own, on SQLite and PostgreSQL alike."""
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        if inspect(connection).has_table("alembic_version"):
            connection.execute(text("DROP TABLE alembic_version"))


def migrate(database_url: str) -> None:
    """``alembic upgrade head`` against ``database_url``, from any working directory."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.cmd_opts = Namespace(x=[f"url={database_url}"])
    command.upgrade(config, "head")


def catch_up(uow: UnitOfWork, clock: Clock) -> TickReport:
    """One tick with nobody to notify: the history's breaches, recorded as they would have been."""
    return SLAMonitor(uow, clock).tick()


def settle(uow: UnitOfWork, clock: Clock) -> SettleReport:
    """Close off the history's open P1 and P2 incidents, quietly, through the facade (D-041).

    The generated history leaves outages open on several services, so the health map would
    open half red and Workflow 3's database outage would not stand out. Each is resolved by
    its assignee through the legal steps (§4), or, while nobody holds it yet, cancelled by an
    administrator; both are audited. Nobody is notified, as in catch_up().
    """
    service = IncidentService(uow, clock, advisor=RuleBasedAdvisor())
    query = IncidentQuery(
        statuses=tuple(sorted(LIVE_STATUSES)),
        priorities=(Priority.P1, Priority.P2),
        limit=CSV_EXPORT_LIMIT,
    )
    admin = _user(uow, DEMO_ADMIN)
    resolved = cancelled = 0
    for incident in uow.incidents.search(query, clock.now()).items:
        if incident.assignee_id is None:
            service.cancel(admin, incident.id, CancelReason.WITHDRAWN)
            cancelled += 1
            continue
        assignee = _user(uow, incident.assignee_id)
        status = incident.status
        if status is IncidentStatus.ASSIGNED:
            status = service.acknowledge(assignee, incident.id).status
        if status is IncidentStatus.ACKNOWLEDGED:
            status = service.start(assignee, incident.id).status
        if status is IncidentStatus.ON_HOLD:
            status = service.resume(assignee, incident.id).status
        service.resolve(assignee, incident.id, SETTLED_SUMMARY)
        resolved += 1
    return SettleReport(resolved, cancelled)


def stage(uow: UnitOfWork, clock: Clock) -> tuple[StagedIncident, ...]:
    """Report each workflow's starting incident through the facade (§11 steps 1-9)."""
    notifications = NotificationService(uow, clock, default_factory())
    service = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifications.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    services = {s.name: s.id for s in uow.catalogue.services()}
    categories = {c.name: c.id for c in uow.catalogue.categories()}

    look_alike = service.report(
        _user(uow, OTHER_EMPLOYEE),
        title=LOOK_ALIKE_TITLE,
        description="The fee payment page takes minutes to load and sometimes shows an error.",
        service_id=services["Fee Payment Portal"],
        category_id=categories["Web Application"],
        impact=1,
        urgency=1,
    ).incident

    wifi = service.report(
        _user(uow, DEMO_EMPLOYEE),
        title=WIFI_TITLE,
        description="The wifi connection drops every few minutes on the first floor.",
        service_id=services["Campus Wi-Fi"],
        category_id=categories["Network"],
        impact=1,
        urgency=1,
    ).incident
    if wifi.assignee_id != DEMO_TECHNICIAN:
        wifi = service.reassign(_user(uow, DEMO_LEAD), wifi.id, DEMO_TECHNICIAN)

    return (
        _staged("Workflow 1 (duplicate hint)", look_alike),
        _staged("Workflow 2 (technician queue)", wifi),
    )


def _staged(workflow: str, incident: Incident) -> StagedIncident:
    return StagedIncident(
        workflow=workflow,
        incident_id=incident.id,
        title=incident.title,
        priority=incident.priority.value if incident.priority else "-",
        assignee_id=incident.assignee_id,
    )


def _user(uow: UnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


# ---------------------------------------------------------------- the take, rehearsed
@dataclass(frozen=True, slots=True)
class Person:
    """Someone the presenters need a signed-in window for."""

    name: str
    email: str

    def __str__(self) -> str:
        return f"{self.name} ({self.email})"


@dataclass(frozen=True, slots=True)
class TakePlan:
    """Who the script's live reports reach on this exact data (D-043).

    Assignment is deterministic, but the Smart scores for the Workflow 1 report are close, so
    one extra report before the take (a dry run without a reset, say) changes who gets it. The
    rehearsal replays the script on the current data and rolls everything back, so the
    presenters know every name before they press record.
    """

    fresh: bool
    workflow1: Person | None
    duplicate_holder: Person | None
    database: Person | None
    escalations: tuple[Person, ...]
    reassign_to: tuple[Person, ...]

    def summary(self) -> str:
        def name(person: Person | None) -> str:
            return "nobody (check the data)" if person is None else str(person)

        levels = ("~31 s", "~61 s", "~92 s")
        lines = [
            "",
            "WHO GETS WHAT IN THE TAKE (the script replayed on this data, then rolled back):",
            f"  Workflow 1  '{WORKFLOW1_REPORT[0]}', Category {WORKFLOW1_REPORT[2]}"
            f" -> {name(self.workflow1)}",
            f"  Step 2      '{LOOK_ALIKE_TITLE}' is confirmed as a duplicate by"
            f" {name(self.duplicate_holder)}",
            f"  Workflow 3  '{DATABASE_REPORT[0]}', Category {DATABASE_REPORT[2]}"
            f" -> {name(self.database)}",
            *(
                f"    escalation level {level} at {when}: {person}"
                for level, (when, person) in enumerate(
                    zip(levels, self.escalations, strict=False), start=1
                )
            ),
            "  Speaker 3   Assignment advice on the database incident (Smart): "
            + (", ".join(p.name for p in self.reassign_to) or "none"),
            "  Set each Category exactly as above. Sign a window in for every person named.",
        ]
        if not self.fresh:
            lines.append(
                "  WARNING: incidents were reported after the reset, so these names may not hold"
                " for the take. Run demo-reset again before recording."
            )
        return "\n".join(lines)


class _RehearsalUnitOfWork(UnitOfWork):
    """Pattern: Proxy. Problem solved: the rehearsal must run the real facade and monitor, which
    commit as they go, and still leave nothing behind. Here commit() only flushes, so the
    rehearsal sees its own writes, and the caller rolls the one transaction back at the end."""

    def __init__(self, inner: SqlAlchemyUnitOfWork) -> None:
        self.__inner = inner
        self.incidents = inner.incidents
        self.users = inner.users
        self.credentials = inner.credentials
        self.catalogue = inner.catalogue
        self.audit = inner.audit
        self.notifications = inner.notifications
        self.analytics = inner.analytics
        self.violations = inner.violations
        self.settings = inner.settings
        self.embeddings = inner.embeddings

    def commit(self) -> None:
        self.__inner.session.flush()

    def rollback(self) -> None:
        self.__inner.rollback()


def rehearse(uow: SqlAlchemyUnitOfWork, now: datetime) -> TakePlan:
    """Replay the script's live steps on the current data, note who gets what, roll back."""
    fresh = is_fresh(uow)
    dry = _RehearsalUnitOfWork(uow)
    clock = FakeClock(now)
    service = IncidentService(dry, clock, advisor=RuleBasedAdvisor())
    services = {s.name: s.id for s in uow.catalogue.services()}
    categories = {c.name: c.id for c in uow.catalogue.categories()}
    try:
        workflow1 = service.report(
            _user(uow, OTHER_EMPLOYEE),
            title=WORKFLOW1_REPORT[0],
            description="When I click pay, the page spins and then shows an error.",
            service_id=services[WORKFLOW1_REPORT[1]],
            category_id=categories[WORKFLOW1_REPORT[2]],
            impact=3,
            urgency=3,
        ).incident
        holder = None
        if workflow1.assignee_id is not None:
            meera = _user(uow, workflow1.assignee_id)
            service.acknowledge(meera, workflow1.id)
            service.start(meera, workflow1.id)
            service.request_information(meera, workflow1.id, "Transaction ID?")
            look_alike = _find_live(uow, LOOK_ALIKE_TITLE, now)
            if look_alike is not None and look_alike.assignee_id is not None:
                holder_user = _user(uow, look_alike.assignee_id)
                service.confirm_duplicate(holder_user, look_alike.id, workflow1.id)
                holder = _person(holder_user)
        database = service.report(
            uow.users.find_by_email(EmailAddress(DATABASE_REPORTER)) or _user(uow, DEMO_EMPLOYEE),
            title=DATABASE_REPORT[0],
            description="Every query to the main database times out.",
            service_id=services[DATABASE_REPORT[1]],
            category_id=categories[DATABASE_REPORT[2]],
            impact=3,
            urgency=3,
        ).incident
        first_owner = database.assignee_id
        escalations: list[Person] = []
        for minutes in (5, 10, 15):  # the P1 response target, missed once, twice, three times
            clock.set(database.created_at + timedelta(minutes=minutes, seconds=4))
            SLAMonitor(dry, clock).tick()
            owner = uow.incidents.get(database.id).assignee_id
            if owner is not None:
                escalations.append(_person(_user(uow, owner)))
        advice = service.assignment_advice(uow.incidents.get(database.id))
        reassign_to = tuple(_person(_user(uow, c.technician_id)) for c in advice.ranked[:3])
        return TakePlan(
            fresh=fresh,
            workflow1=_person_or_none(uow, workflow1.assignee_id),
            duplicate_holder=holder,
            database=_person_or_none(uow, first_owner),
            escalations=tuple(escalations),
            reassign_to=reassign_to,
        )
    finally:
        uow.rollback()


def is_fresh(uow: SqlAlchemyUnitOfWork) -> bool:
    """True while the highest-numbered incident is still the staged Wi-Fi report.

    Incident numbers are allocated in order (INC-YYYY-NNNN), so anything reported after the
    reset outranks it; timestamps would tie under a clock that stands still.
    """
    newest = uow.session.scalars(
        select(IncidentRow.title).order_by(IncidentRow.id.desc()).limit(1)
    ).first()
    return newest == WIFI_TITLE


def check(settings: Settings, now: datetime) -> TakePlan:
    """``demo-check``: the rehearsal on the database as it is now, for just before recording."""
    engine = make_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(now))
        try:
            return rehearse(uow, now)
        finally:
            uow.close()
    finally:
        engine.dispose()


def _find_live(uow: UnitOfWork, title: str, now: datetime) -> Incident | None:
    query = IncidentQuery(text=title, statuses=tuple(sorted(LIVE_STATUSES)), limit=5)
    for incident in uow.incidents.search(query, now).items:
        if incident.title == title:
            return incident
    return None


def _person(user: User) -> Person:
    return Person(user.full_name, str(user.email))


def _person_or_none(uow: UnitOfWork, user_id: int | None) -> Person | None:
    return None if user_id is None else _person(_user(uow, user_id))


# ---------------------------------------------------------------- the CLI
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.demo",
        description="Reset the database for a demo take (P5.5, blueprint §14).",
    )
    parser.add_argument(
        "--seed-if-empty",
        action="store_true",
        help="only seed a never-seeded database and catch the monitor up; wipe nothing",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="wipe nothing: replay the script on the current data and print who gets what",
    )
    parser.add_argument(
        "--allow-remote-database",
        action="store_true",
        help="let the reset wipe a database on another machine (a demo deployment only)",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        if args.check:
            print(check(settings, SystemClock().now()).summary().lstrip())
        elif args.seed_if_empty:
            print(seed_if_empty(settings, SystemClock()))
        else:
            report = reset(
                settings, SystemClock(), allow_remote_database=args.allow_remote_database
            )
            print(report.summary())
    except (DemoResetRefusedError, ITSMError) as error:
        print(f"demo-reset: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
