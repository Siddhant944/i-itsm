"""``make demo-reset`` (P5.5, blueprint §14): the state every demo take starts from.

``python -m app.demo`` wipes the database at DATABASE_URL, migrates it to head, seeds it, and
then does the two things a plain seed cannot:

1. **Catches the monitor up.** The seeded history was generated, not watched, so on its own the
   first tick after a seed would record ~170 breaches, ~60 escalations and ~30 auto-closes at
   once, in the middle of the recording. One quiet tick here records them now, with no
   notifications, exactly as the monitor would have done had it been running all along.
2. **Stages the workflows' starting points** through the IncidentService facade, so each one
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
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.core.clock import Clock, SystemClock
from app.core.config import AppEnv, Settings, get_settings
from app.core.security import Argon2PasswordHasher
from app.domain.errors import ITSMError
from app.domain.incident import Incident
from app.domain.repositories import UnitOfWork
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.users import User
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import Base
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


class DemoResetRefusedError(Exception):
    """Raised instead of wiping a production database."""


@dataclass(frozen=True, slots=True)
class StagedIncident:
    """One workflow's starting point, so the presenter knows where to find it."""

    workflow: str
    incident_id: str
    title: str
    priority: str
    assignee_id: int | None


@dataclass(frozen=True, slots=True)
class DemoReport:
    seed_summary: str
    catch_up: TickReport
    staged: tuple[StagedIncident, ...]

    def summary(self) -> str:
        lines = [
            self.seed_summary,
            f"history caught up ({self.catch_up.summary}, no notifications sent)",
            *(
                f"staged for {s.workflow}: {s.incident_id} {s.priority} '{s.title}'"
                f" (assigned to user {s.assignee_id})"
                for s in self.staged
            ),
            f"demo accounts: employee, technician, lead, admin, manager @campus.edu,"
            f" password {people.DEMO_PASSWORD}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------- the reset
def reset(settings: Settings, clock: Clock) -> DemoReport:
    """Wipe, migrate, seed, catch up and stage the database ``settings`` names."""
    if settings.app_env is AppEnv.PROD:
        msg = "demo-reset wipes the database; it never runs with APP_ENV=prod"
        raise DemoResetRefusedError(msg)
    engine = make_engine(settings.database_url)
    try:
        wipe(engine)
        migrate(settings.database_url)
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
        try:
            seeded = seed(uow, clock, hash_password=Argon2PasswordHasher().hash)
            caught_up = catch_up(uow, clock)
            staged = stage(uow, clock)
        finally:
            uow.close()
    finally:
        engine.dispose()
    return DemoReport(seeded.summary(), caught_up, staged)


def seed_if_empty(settings: Settings, clock: Clock) -> str:
    """A deployment's first start (SEED_ON_START): seed a never-seeded database and catch up.

    Unlike :func:`reset` this wipes nothing and stages nothing, so it is safe in production and
    a no-op on every later start; the catch-up keeps the first live tick from notifying dozens
    of people about breaches that happened, in the generated history, months ago.
    """
    engine = make_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), clock)
        try:
            if already_seeded(uow):
                return "seed: already seeded; nothing changed"
            seeded = seed(uow, clock, hash_password=Argon2PasswordHasher().hash)
            return f"{seeded.summary()}\nhistory caught up ({catch_up(uow, clock).summary})"
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
        title="Fee payment portal page is very slow",
        description="The fee payment page takes minutes to load and sometimes shows an error.",
        service_id=services["Fee Payment Portal"],
        category_id=categories["Web Application"],
        impact=1,
        urgency=1,
    ).incident

    wifi = service.report(
        _user(uow, DEMO_EMPLOYEE),
        title="Wi-Fi keeps dropping in the library reading room",
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
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        if args.seed_if_empty:
            print(seed_if_empty(settings, SystemClock()))
        else:
            print(reset(settings, SystemClock()).summary())
    except (DemoResetRefusedError, ITSMError) as error:
        print(f"demo-reset: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
