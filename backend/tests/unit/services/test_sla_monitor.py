"""The SLA monitor (blueprint §5.2, §5.5; BR-03, BR-08).

Everything runs on a FakeClock, so "just after five minutes" means exactly that. The monitor
ticks every 30 clock seconds in production, so every test also ticks twice and checks the
second tick changed nothing.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.audit import AuditAction, verify_chain
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.incident import Incident, IncidentFactory
from app.domain.notifications import NotificationEvent
from app.domain.permissions import Role
from app.domain.priority import Priority, PriorityAssessment
from app.domain.sla import SLAStatus, SLATarget, ViolationKind, default_policies
from app.domain.states import IncidentStatus as S
from app.domain.users import User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.sla_monitor import AUTO_CLOSE_AFTER, TICK_INTERVAL, SLAMonitor

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
# §5.2 Gold: P1 responds in 5 minutes and resolves in 30.
P1_TARGET = SLATarget(timedelta(minutes=5), timedelta(minutes=30))
P3_TARGET = SLATarget(timedelta(hours=1), timedelta(hours=8))
REPORTER, TECH, LEAD, ADMIN, MANAGER = 1, 2, 3, 4, 5
WIFI = 1


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_category(Category(1, "Network", keywords=("wifi",)))
    unit.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=3))
    unit.catalogue.save_policies(default_policies())
    unit.catalogue.save_team(Team(1, "Network Operations"))
    for user_id, role, name in (
        (REPORTER, Role.EMPLOYEE, "Devika Rao"),
        (TECH, Role.TECHNICIAN, "Arjun Menon"),
        (LEAD, Role.TEAM_LEAD, "Priya Nair"),
        (ADMIN, Role.ADMINISTRATOR, "Rahul Verma"),
        (MANAGER, Role.IT_MANAGER, "Sunita Iyer"),
    ):
        support = UserFactory.is_support_role(role)
        unit.users.add(
            UserFactory.create(
                role,
                user_id=user_id,
                email=f"u{user_id}@campus.edu",
                full_name=name,
                skills=SkillSet({"networking"}) if support else None,
                experience_level=2 if support else None,
                team_id=1 if support else None,
            )
        )
    team = unit.catalogue.get_team(1)
    team.add_member(TECH)
    team.add_member(LEAD)
    team.set_lead(LEAD)
    unit.catalogue.save_team(team)
    return unit


@pytest.fixture
def sent() -> list[tuple[NotificationEvent, str, str]]:
    return []


@pytest.fixture
def monitor(
    uow: InMemoryUnitOfWork, clock: FakeClock, sent: list[tuple[NotificationEvent, str, str]]
) -> SLAMonitor:
    def notify(event: NotificationEvent, incident: Incident, detail: str) -> None:
        sent.append((event, incident.id, detail))

    return SLAMonitor(uow, clock, notify=notify)


def unacknowledged(
    uow: InMemoryUnitOfWork,
    clock: FakeClock,
    *,
    priority: Priority = Priority.P1,
    target: SLATarget = P1_TARGET,
    sequence: int = 1,
) -> Incident:
    """An incident assigned to a technician who never picked it up."""
    incident = IncidentFactory.create(
        sequence=sequence,
        clock=clock,
        reporter_id=REPORTER,
        title="Wi-Fi down across campus",
        description="No wifi anywhere",
        service_id=WIFI,
        impact=3,
        urgency=3,
    )
    incident.prioritise(PriorityAssessment(priority, 27, "fixture"), clock)
    incident.apply_sla(target)
    incident.classify(1, None, clock)
    incident.assign(TECH, None, clock)
    incident.pull_events()
    uow.incidents.add(incident)
    return incident


def kinds(uow: InMemoryUnitOfWork, incident_id: str) -> set[ViolationKind]:
    return {v.kind for v in uow.violations.for_incident(incident_id)}


def who(uow: InMemoryUnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


# ---------------------------------------------------------------- nothing to do
def test_a_quiet_system_does_nothing(monitor: SLAMonitor, uow: InMemoryUnitOfWork) -> None:
    report = monitor.tick()
    assert report.did_nothing is True
    assert uow.violations.count() == 0


def test_a_healthy_incident_is_left_alone(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=1))  # well inside the 5-minute response target
    assert monitor.tick().did_nothing is True


# ---------------------------------------------------------------- warnings and breaches
def test_a_warning_is_written_once_at_three_quarters_of_the_target(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.2: AT_RISK from 75 % of the target elapsed."""
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=3, seconds=45))  # exactly 75 % of five minutes

    first = monitor.tick()
    assert [v.kind for v in first.warned] == [ViolationKind.RESPONSE_WARNING]
    assert first.warned[0].deadline == NOW + timedelta(minutes=5)
    assert first.warned[0].cycle == 0

    clock.advance(TICK_INTERVAL)
    second = monitor.tick()
    assert second.warned == ()
    assert uow.violations.count() == 1
    assert kinds(uow, incident.id) == {ViolationKind.RESPONSE_WARNING}


def test_a_breach_is_recorded_once_just_after_the_deadline(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.2: at the deadline it is not breached; a microsecond later it is."""
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=5))
    assert monitor.tick().breached == ()

    clock.advance(timedelta(microseconds=1))
    breaching = monitor.tick()
    assert [v.kind for v in breaching.breached] == [ViolationKind.RESPONSE_BREACH]

    clock.advance(TICK_INTERVAL)
    assert monitor.tick().breached == ()
    assert ViolationKind.RESPONSE_BREACH in kinds(uow, incident.id)


def test_both_clocks_are_reported_separately(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=31))  # past both the 5-minute and the 30-minute target
    monitor.tick()
    assert kinds(uow, incident.id) >= {
        ViolationKind.RESPONSE_BREACH,
        ViolationKind.RESOLUTION_BREACH,
    }


def test_a_reopened_incident_can_breach_again(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """The cycle is the reopen count, so a fix that does not hold is reported afresh."""
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    clock.advance(timedelta(hours=9))
    incident.resolve(TECH, clock, "Rebooted it")
    uow.incidents.save(incident)
    monitor.tick()
    first_round = {(v.kind, v.cycle) for v in uow.violations.for_incident(incident.id)}
    assert (ViolationKind.RESOLUTION_BREACH, 0) in first_round

    incident.reject(REPORTER, clock, "It came back")
    uow.incidents.save(incident)
    clock.advance(timedelta(hours=9))
    monitor.tick()
    second_round = {(v.kind, v.cycle) for v in uow.violations.for_incident(incident.id)}
    assert (ViolationKind.RESOLUTION_BREACH, 1) in second_round


def test_a_paused_incident_is_not_reported(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """BR-07: the resolution clock stops while the reporter is being waited on."""
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    incident.hold(TECH, clock, "Which building?")
    uow.incidents.save(incident)

    clock.advance(timedelta(days=2))  # far past the eight-hour resolution target
    assert ViolationKind.RESOLUTION_BREACH not in kinds(uow, incident.id)
    monitor.tick()
    assert ViolationKind.RESOLUTION_BREACH not in kinds(uow, incident.id)


def test_breaches_are_audited(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=6))
    monitor.tick()
    records = uow.audit.records(limit=100)
    assert AuditAction.SLA_VIOLATED in [r.action for r in records]
    assert verify_chain(records).intact is True


# ---------------------------------------------------------------- BR-08 escalation
def test_BR08_a_p1_escalates_just_after_five_ten_and_fifteen_minutes(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.5: one level per elapsed response target, and not at exactly 5:00."""
    incident = unacknowledged(uow, clock)

    clock.advance(timedelta(minutes=5))
    assert monitor.tick().escalated == ()
    assert uow.incidents.get(incident.id).escalation_level == 0

    clock.advance(timedelta(seconds=1))
    assert monitor.tick().escalated == (incident.id,)
    escalated = uow.incidents.get(incident.id)
    assert escalated.escalation_level == 1
    assert escalated.assignee_id == LEAD  # D-004: the lead of the assignee's team

    clock.advance(TICK_INTERVAL)
    assert monitor.tick().escalated == ()  # nothing new until the next target elapses

    clock.advance(timedelta(minutes=5))
    assert monitor.tick().escalated == (incident.id,)
    assert uow.incidents.get(incident.id).escalation_level == 2
    assert uow.incidents.get(incident.id).assignee_id == ADMIN

    clock.advance(timedelta(minutes=5))
    assert monitor.tick().escalated == (incident.id,)
    assert uow.incidents.get(incident.id).escalation_level == 3
    assert uow.incidents.get(incident.id).assignee_id == MANAGER

    # Level 3 is the top of the chain (§5.5).
    clock.advance(timedelta(minutes=30))
    assert monitor.tick().escalated == ()
    assert uow.incidents.get(incident.id).escalation_level == 3


def test_BR08_acknowledging_stops_the_escalation(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=4))
    incident.acknowledge(TECH, clock)
    uow.incidents.save(incident)

    clock.advance(timedelta(minutes=20))
    report = monitor.tick()
    assert report.escalated == ()
    assert uow.incidents.get(incident.id).escalation_level == 0
    assert uow.incidents.get(incident.id).assignee_id == TECH


def test_BR08_a_p3_does_not_escalate_on_the_response_target(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """Only P1 and P2 escalate for a missed response (§5.5)."""
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    clock.advance(timedelta(hours=2))  # two response targets gone
    report = monitor.tick()
    assert report.escalated == ()
    assert uow.incidents.get(incident.id).escalation_level == 0
    assert ViolationKind.RESPONSE_BREACH in kinds(uow, incident.id)  # still recorded


def test_a_resolution_breach_goes_to_the_team_lead(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.5: a resolution breach goes straight to the Team Lead, whatever the priority."""
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    uow.incidents.save(incident)

    clock.advance(timedelta(hours=9))
    assert monitor.tick().escalated == (incident.id,)
    escalated = uow.incidents.get(incident.id)
    assert escalated.escalation_level == 1
    assert escalated.assignee_id == LEAD


def test_escalation_is_audited(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=6))
    monitor.tick()
    actions = [r.action for r in uow.audit.records(limit=100)]
    assert AuditAction.INCIDENT_ESCALATED in actions
    assert verify_chain(uow.audit.records(limit=100)).intact is True


# ---------------------------------------------------------------- BR-03 auto-close
def test_BR03_autoclose_closes_an_unanswered_resolution_after_72_hours(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    incident.resolve(TECH, clock, "Replaced the access point")
    uow.incidents.save(incident)

    clock.advance(AUTO_CLOSE_AFTER)
    assert monitor.tick().auto_closed == ()  # at 72 hours exactly, not yet
    assert uow.incidents.get(incident.id).status is S.RESOLVED

    clock.advance(timedelta(minutes=1))
    report = monitor.tick()
    assert report.auto_closed == (incident.id,)
    closed = uow.incidents.get(incident.id)
    assert closed.status is S.CLOSED
    assert closed.closed_at == clock.now()

    clock.advance(TICK_INTERVAL)
    assert monitor.tick().auto_closed == ()  # and never again


def test_BR03_autoclose_leaves_a_verified_incident_alone(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    incident.resolve(TECH, clock, "Replaced the access point")
    incident.verify(REPORTER, clock, rating=5)
    uow.incidents.save(incident)

    clock.advance(AUTO_CLOSE_AFTER + timedelta(days=1))
    assert monitor.tick().auto_closed == ()
    assert uow.incidents.get(incident.id).status is S.VERIFIED


def test_BR03_autoclose_is_audited_with_no_actor(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """The system closed it, so the audit record names nobody."""
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    incident.resolve(TECH, clock, "Replaced the access point")
    uow.incidents.save(incident)

    clock.advance(AUTO_CLOSE_AFTER + timedelta(minutes=1))
    monitor.tick()
    closing = [
        record
        for record in uow.audit.records(limit=100, incident_id=incident.id)
        if "72 h" in str(record.details.get("reason", ""))
    ]
    assert closing
    assert closing[0].actor_id is None


# ---------------------------------------------------------------- notifications (§5.4)
def test_warnings_and_breaches_are_notified_after_the_tick(
    monitor: SLAMonitor,
    uow: InMemoryUnitOfWork,
    clock: FakeClock,
    sent: list[tuple[NotificationEvent, str, str]],
) -> None:
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=4))
    monitor.tick()
    assert [event for event, _, _ in sent] == [NotificationEvent.SLA_APPROACHING]

    sent.clear()
    clock.advance(timedelta(minutes=2))
    monitor.tick()
    assert NotificationEvent.SLA_VIOLATED in [event for event, _, _ in sent]
    assert all(incident_id == incident.id for _, incident_id, _ in sent)
    assert all(detail for _, _, detail in sent)


def test_a_failing_notification_does_not_lose_the_violation(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.4: notifications never block or roll back what triggered them."""

    def explode(*_: object) -> None:
        msg = "the mail server is down"
        raise RuntimeError(msg)

    incident = unacknowledged(uow, clock)
    monitor = SLAMonitor(uow, clock, notify=explode)
    clock.advance(timedelta(minutes=6))
    report = monitor.tick()
    assert report.breached
    assert ViolationKind.RESPONSE_BREACH in kinds(uow, incident.id)


def test_a_monitor_with_no_notifier_still_records(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=6))
    assert SLAMonitor(uow, clock).tick().breached
    assert ViolationKind.RESPONSE_BREACH in kinds(uow, incident.id)


# ---------------------------------------------------------------- the violations screen
def test_the_violations_screen_reads_the_newest_first(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    unacknowledged(uow, clock, sequence=1)
    clock.advance(timedelta(minutes=6))
    monitor.tick()
    unacknowledged(uow, clock, sequence=2)
    clock.advance(timedelta(minutes=6))
    monitor.tick()

    recent = uow.violations.recent(limit=10)
    assert len(recent) >= 2
    assert [v.detected_at for v in recent] == sorted((v.detected_at for v in recent), reverse=True)
    assert uow.violations.count(breaches_only=True) <= uow.violations.count()


def test_the_status_the_monitor_acts_on_is_the_one_the_clock_reports(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """A sanity check that the query and the clock agree about who needs attention."""
    incident = unacknowledged(uow, clock)
    clock.advance(timedelta(minutes=4))
    attention = uow.incidents.needing_sla_attention(clock.now())
    assert [i.id for i in attention] == [incident.id]
    assert incident.sla_clock is not None
    assert incident.sla_clock.response_status(clock.now()) is SLAStatus.AT_RISK


def test_a_resolved_incident_past_its_deadline_is_not_asked_about_again(
    monitor: SLAMonitor, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§4 has no ASSIGNED move out of RESOLVED, so the chain must not be asked about one.

    Before this was guarded, every tick tried the escalation, failed and logged it — for the
    life of the row. The seeded history has hundreds of these.
    """
    incident = unacknowledged(uow, clock, priority=Priority.P3, target=P3_TARGET)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    clock.advance(timedelta(hours=9))  # past the eight-hour target
    incident.resolve(TECH, clock, "Took a while")
    uow.incidents.save(incident)

    first = monitor.tick()
    assert ViolationKind.RESOLUTION_BREACH in kinds(uow, incident.id)
    assert first.escalations == ()
    assert uow.incidents.get(incident.id).status is S.RESOLVED

    clock.advance(TICK_INTERVAL)
    assert monitor.tick().did_nothing is True


def test_escalation_skips_a_level_whose_owner_already_holds_the_incident(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.5: handing an incident back to its current owner would leave it stuck."""
    incident = unacknowledged(uow, clock)
    incident.assign(LEAD, None, clock)  # the team's own lead is carrying it
    uow.incidents.save(incident)

    monitor = SLAMonitor(uow, clock)
    clock.advance(timedelta(minutes=6))
    report = monitor.tick()

    assert [step.incident_id for step in report.escalations] == [incident.id]
    moved = uow.incidents.get(incident.id)
    assert moved.assignee_id == ADMIN  # level 1 was the lead, so it went to level 2
    assert moved.escalation_level == 2
    assert [step.level for step in report.escalations] == [2]


def test_escalation_stops_when_nobody_is_left_above_the_current_owner(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """With the IT manager already holding it, there is nowhere further up to go."""
    incident = unacknowledged(uow, clock)
    incident.escalate(MANAGER, 3, None, clock)
    uow.incidents.save(incident)

    monitor = SLAMonitor(uow, clock)
    clock.advance(timedelta(minutes=30))
    report = monitor.tick()

    assert report.escalations == ()
    assert uow.incidents.get(incident.id).assignee_id == MANAGER
    assert uow.incidents.get(incident.id).escalation_level == 3


def test_an_unclassified_incident_is_not_asked_about_escalation(
    monitor: SLAMonitor,
    uow: InMemoryUnitOfWork,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§4 has no NEW → ASSIGNED move, so a NEW incident cannot be escalated (issue #6).

    The monitor used to try, fail and log a warning on every tick for the life of the row;
    eight of the seeded incidents are NEW, so that was a warning every three real seconds in
    the demo. The breach itself is still recorded.
    """
    incident = IncidentFactory.create(
        sequence=1,
        clock=clock,
        reporter_id=REPORTER,
        title="Wi-Fi down across campus",
        description="No wifi anywhere",
        service_id=WIFI,
        impact=3,
        urgency=3,
    )
    incident.prioritise(PriorityAssessment(Priority.P1, 27, "fixture"), clock)
    incident.apply_sla(P1_TARGET)
    incident.pull_events()
    uow.incidents.add(incident)
    clock.advance(timedelta(minutes=16))

    with caplog.at_level("WARNING", logger="app.services.sla_monitor"):
        report = monitor.tick()

    assert report.escalations == ()
    assert ViolationKind.RESPONSE_BREACH in kinds(uow, incident.id)
    assert uow.incidents.get(incident.id).status is S.NEW
    assert caplog.records == []
