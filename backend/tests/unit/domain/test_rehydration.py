"""Named constructors that rebuild aggregates from stored rows (used by the SQL mappers).

Restoring must reproduce every measurement the live aggregate would give, and must not
re-emit the domain events that were already dispatched when the change first happened.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.errors import InvalidIncidentError
from app.domain.incident import CancelReason, Incident, IncidentFactory, NoteKind, WorkNote
from app.domain.priority import Priority
from app.domain.sla import SLAClock, SLAStatus, SLATarget
from app.domain.states import IncidentStatus

START = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
TARGET = SLATarget(timedelta(minutes=15), timedelta(hours=2))


def _live_clock() -> SLAClock:
    clock = SLAClock(START, TARGET)
    clock.respond(START + timedelta(minutes=10))
    clock.pause(START + timedelta(minutes=30))
    clock.resume(START + timedelta(minutes=50))
    return clock


def test_a_restored_sla_clock_measures_like_the_live_one() -> None:
    live = _live_clock()
    restored = SLAClock.restore(
        started_at=live.started_at,
        target=live.target,
        responded_at=live.responded_at,
        paused_total=live.paused_accumulated,
        paused_since=live.paused_since,
        stopped_at=live.stopped_at,
        response_met=live.response_met,
        resolution_target_at_stop=live.resolution_target_at_stop,
    )
    now = START + timedelta(hours=1)
    assert restored.paused_total(now) == live.paused_total(now) == timedelta(minutes=20)
    assert restored.resolution_elapsed(now) == live.resolution_elapsed(now)
    assert restored.resolution_deadline(now) == live.resolution_deadline(now)
    assert restored.response_status(now) is live.response_status(now) is SLAStatus.ON_TRACK
    assert restored.resolution_status(now) is live.resolution_status(now)


def test_a_restored_clock_keeps_a_pause_and_a_stop_in_progress() -> None:
    live = SLAClock(START, TARGET)
    live.pause(START + timedelta(minutes=10))
    paused = SLAClock.restore(
        started_at=START,
        target=TARGET,
        responded_at=None,
        paused_total=live.paused_accumulated,
        paused_since=live.paused_since,
        stopped_at=None,
        response_met=None,
        resolution_target_at_stop=None,
    )
    assert paused.is_paused
    with pytest.raises(InvalidIncidentError):
        paused.pause(START + timedelta(minutes=20))
    paused.resume(START + timedelta(minutes=20))
    assert paused.paused_total(START + timedelta(minutes=30)) == timedelta(minutes=10)

    live.resume(START + timedelta(minutes=20))
    live.stop(START + timedelta(minutes=40))
    stopped = SLAClock.restore(
        started_at=START,
        target=TARGET,
        responded_at=None,
        paused_total=live.paused_accumulated,
        paused_since=None,
        stopped_at=live.stopped_at,
        response_met=None,
        resolution_target_at_stop=live.resolution_target_at_stop,
    )
    assert stopped.is_stopped
    far = START + timedelta(days=2)
    assert stopped.resolution_elapsed(far) == timedelta(minutes=30)
    assert stopped.resolution_status(far) is live.resolution_status(far)


def test_a_restored_breached_response_stays_breached() -> None:
    live = SLAClock(START, TARGET)
    live.respond(START + timedelta(minutes=16))
    restored = SLAClock.restore(
        started_at=START,
        target=TARGET,
        responded_at=live.responded_at,
        paused_total=timedelta(),
        paused_since=None,
        stopped_at=None,
        response_met=live.response_met,
        resolution_target_at_stop=None,
    )
    assert restored.response_status(START + timedelta(minutes=20)) is SLAStatus.BREACHED


def _resolved_incident() -> Incident:
    clock = FakeClock(START)
    incident = IncidentFactory.create(
        sequence=7,
        clock=clock,
        reporter_id=1,
        title="Projector dead",
        description="No picture in LT-3",
        service_id=4,
        impact=2,
        urgency=3,
    )
    incident.apply_sla(TARGET)
    incident.classify(2, None, clock)
    incident.assign(5, 9, clock)
    clock.advance(timedelta(minutes=10))
    incident.acknowledge(5, clock)
    incident.start(5, clock)
    incident.add_note(5, clock, "Swapped the cable")
    clock.advance(timedelta(minutes=20))
    incident.resolve(5, clock, "Replaced the projector lamp")
    incident.pull_events()
    return incident


def test_a_restored_incident_reproduces_its_state_without_re_emitting_events() -> None:
    live = _resolved_incident()
    assert live.sla_clock is not None
    restored = Incident.restore(
        incident_id=live.id,
        reporter_id=live.reporter_id,
        title=live.title,
        description=live.description,
        service_id=live.service_id,
        impact=live.impact,
        urgency=live.urgency,
        created_at=live.created_at,
        status=live.status,
        category_id=live.category_id,
        assignee_id=live.assignee_id,
        parent_id=live.parent_id,
        cancel_reason=live.cancel_reason,
        acknowledged_at=live.acknowledged_at,
        resolved_at=live.resolved_at,
        closed_at=live.closed_at,
        reopen_count=live.reopen_count,
        escalation_level=live.escalation_level,
        priority=live.priority,
        priority_score=live.priority_score,
        priority_overridden=live.priority_overridden,
        sla_clock=live.sla_clock,
        notes=live.notes,
        resolution=live.resolution,
        feedback=live.feedback,
    )
    assert restored.pull_events() == ()
    for field in (
        "id",
        "reporter_id",
        "title",
        "description",
        "service_id",
        "impact",
        "urgency",
        "created_at",
        "status",
        "category_id",
        "assignee_id",
        "parent_id",
        "acknowledged_at",
        "resolved_at",
        "reopen_count",
        "escalation_level",
        "priority",
        "priority_overridden",
        "notes",
        "resolution",
    ):
        assert getattr(restored, field) == getattr(live, field), field


def test_a_restored_incident_still_enforces_the_lifecycle_and_sla_effects() -> None:
    live = _resolved_incident()
    assert live.sla_clock is not None
    restored = Incident.restore(
        incident_id=live.id,
        reporter_id=live.reporter_id,
        title=live.title,
        description=live.description,
        service_id=live.service_id,
        impact=live.impact,
        urgency=live.urgency,
        created_at=live.created_at,
        status=live.status,
        sla_clock=live.sla_clock,
        notes=live.notes,
        resolution=live.resolution,
    )
    clock = FakeClock(START + timedelta(hours=1))
    restored.verify(1, clock, rating=5)
    assert restored.status is IncidentStatus.VERIFIED
    assert restored.feedback is not None
    events = restored.pull_events()
    assert [type(event).__name__ for event in events] == ["IncidentStateChanged"]


def test_restoring_a_cancelled_duplicate_keeps_its_parent_and_reason() -> None:
    note = WorkNote(1, START, NoteKind.NOTE, "Same as INC-2026-0001")
    restored = Incident.restore(
        incident_id="INC-2026-0002",
        reporter_id=1,
        title="Portal down",
        description="Again",
        service_id=1,
        impact=3,
        urgency=3,
        created_at=START,
        status=IncidentStatus.CANCELLED,
        parent_id="INC-2026-0001",
        cancel_reason=CancelReason.DUPLICATE,
        closed_at=START + timedelta(minutes=5),
        priority=Priority.P1,
        priority_score=27,
        notes=(note,),
    )
    assert restored.parent_id == "INC-2026-0001"
    assert restored.cancel_reason is CancelReason.DUPLICATE
    assert restored.notes == (note,)
    assert restored.priority is Priority.P1
    with pytest.raises(InvalidIncidentError):
        restored.override_priority(Priority.P2, "wrong", 9, FakeClock(START))
