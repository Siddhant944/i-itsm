from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.errors import (
    InvalidIncidentError,
    InvalidStateTransitionError,
    InvalidUserInputError,
    UnauthorizedOperationError,
)
from app.domain.events import EventBus, IncidentCreated, IncidentStateChanged, WorkNoteAdded
from app.domain.incident import CancelReason, Incident, IncidentFactory, NoteKind
from app.domain.states import IncidentStatus as S

REPORTER, TECH, ADMIN = 1, 2, 3


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 5, 10, 0, tzinfo=UTC))


def new_incident(clock: FakeClock, sequence: int = 42) -> Incident:
    return IncidentFactory.create(
        sequence=sequence,
        clock=clock,
        reporter_id=REPORTER,
        title="Fee portal down",
        description="Payments fail with error 502",
        service_id=7,
        impact=3,
        urgency=3,
    )


def in_progress(clock: FakeClock) -> Incident:
    incident = new_incident(clock)
    incident.classify(category_id=4, actor_id=0, clock=clock)
    incident.assign(TECH, actor_id=0, clock=clock)
    incident.acknowledge(TECH, clock)
    incident.start(TECH, clock)
    return incident


def test_factory_creates_a_new_incident_with_a_yearly_id(clock: FakeClock) -> None:
    incident = new_incident(clock)
    assert incident.id == "INC-2026-0042"
    assert incident.status is S.NEW
    assert incident.created_at == clock.now()
    assert incident.reporter_id == REPORTER
    assert isinstance(incident.pull_events()[0], IncidentCreated)


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("title", {"title": " "}),
        ("description", {"description": ""}),
        ("impact", {"impact": 4}),
        ("urgency", {"urgency": 0}),
    ],
)
def test_factory_validates_input(clock: FakeClock, field: str, kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "sequence": 1,
        "clock": clock,
        "reporter_id": 1,
        "title": "t",
        "description": "d",
        "service_id": 1,
        "impact": 1,
        "urgency": 1,
    }
    with pytest.raises(InvalidUserInputError) as caught:
        IncidentFactory.create(**(base | kwargs))  # type: ignore[arg-type]
    assert field in caught.value.field_errors


def test_full_lifecycle_records_times_and_one_event_per_transition(clock: FakeClock) -> None:
    incident = in_progress(clock)
    clock.advance(timedelta(minutes=10))
    incident.resolve(TECH, clock, summary="Restarted the payment gateway")
    incident.verify(REPORTER, clock, rating=5, comment="Works now")
    incident.close(0, clock)

    assert incident.status is S.CLOSED
    assert incident.resolution is not None
    assert incident.resolution.summary == "Restarted the payment gateway"
    assert incident.feedback is not None
    assert incident.feedback.rating == 5
    assert incident.resolved_at == clock.now()
    assert incident.closed_at == clock.now()
    changes = [e for e in incident.pull_events() if isinstance(e, IncidentStateChanged)]
    assert [(e.from_status, e.to_status) for e in changes] == [
        (S.NEW, S.CLASSIFIED),
        (S.CLASSIFIED, S.ASSIGNED),
        (S.ASSIGNED, S.ACKNOWLEDGED),
        (S.ACKNOWLEDGED, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.RESOLVED),
        (S.RESOLVED, S.VERIFIED),
        (S.VERIFIED, S.CLOSED),
    ]
    assert incident.pull_events() == ()


def test_first_acknowledgement_time_is_kept(clock: FakeClock) -> None:
    incident = in_progress(clock)
    first = incident.acknowledged_at
    clock.advance(timedelta(minutes=3))
    incident.assign(TECH + 10, actor_id=ADMIN, clock=clock)
    incident.acknowledge(TECH + 10, clock)
    assert incident.acknowledged_at == first
    assert incident.assignee_id == TECH + 10


@pytest.mark.parametrize("summary", ["", "   "])
def test_BR04_resolving_requires_a_summary(clock: FakeClock, summary: str) -> None:
    incident = in_progress(clock)
    with pytest.raises(InvalidIncidentError):
        incident.resolve(TECH, clock, summary=summary)
    assert incident.status is S.IN_PROGRESS


def test_BR04_reopen_only_from_resolved(clock: FakeClock) -> None:
    incident = in_progress(clock)
    with pytest.raises(InvalidStateTransitionError):
        incident.reject(REPORTER, clock, reason="still broken")
    incident.resolve(TECH, clock, summary="fixed")
    incident.reject(REPORTER, clock, reason="still broken")
    assert incident.status is S.IN_PROGRESS
    assert incident.resolution is None
    assert incident.reopen_count == 1


def test_BR04_closed_incident_cannot_be_reopened(clock: FakeClock) -> None:
    incident = in_progress(clock)
    incident.resolve(TECH, clock, summary="fixed")
    incident.auto_close(clock)
    with pytest.raises(InvalidStateTransitionError):
        incident.reject(REPORTER, clock, reason="broken again")


def test_BR03_only_the_reporter_verifies_or_rejects(clock: FakeClock) -> None:
    incident = in_progress(clock)
    incident.resolve(TECH, clock, summary="fixed")
    with pytest.raises(UnauthorizedOperationError):
        incident.verify(TECH, clock, rating=5)
    with pytest.raises(UnauthorizedOperationError):
        incident.reject(ADMIN, clock, reason="no")
    assert incident.status is S.RESOLVED


@pytest.mark.parametrize("rating", [0, 6])
def test_feedback_rating_is_1_to_5(clock: FakeClock, rating: int) -> None:
    incident = in_progress(clock)
    incident.resolve(TECH, clock, summary="fixed")
    with pytest.raises(InvalidUserInputError):
        incident.verify(REPORTER, clock, rating=rating)


def test_new_to_closed_is_refused(clock: FakeClock) -> None:
    incident = new_incident(clock)
    with pytest.raises(InvalidStateTransitionError):
        incident.close(ADMIN, clock)
    assert incident.status is S.NEW


def test_hold_and_resume_record_notes(clock: FakeClock) -> None:
    incident = in_progress(clock)
    incident.hold(TECH, clock, question="Which browser are you using?")
    statuses = [incident.status]
    incident.provide_info(REPORTER, clock, answer="Chrome")
    statuses.append(incident.status)
    assert statuses == [S.ON_HOLD, S.IN_PROGRESS]  # D-006
    kinds = [note.kind for note in incident.notes]
    assert kinds == [NoteKind.INFO_REQUEST, NoteKind.INFO_RESPONSE]
    assert isinstance(incident.notes, tuple)


def test_notes_are_composed_and_need_text(clock: FakeClock) -> None:
    incident = in_progress(clock)
    note = incident.add_note(TECH, clock, "Checked gateway logs")
    assert note.kind is NoteKind.NOTE
    assert incident.notes == (note,)
    assert any(isinstance(e, WorkNoteAdded) for e in incident.pull_events())
    with pytest.raises(InvalidUserInputError):
        incident.add_note(TECH, clock, "  ")


def test_cancel_as_duplicate_links_the_parent(clock: FakeClock) -> None:
    incident = new_incident(clock)
    incident.cancel(ADMIN, clock, CancelReason.DUPLICATE, duplicate_of="INC-2026-0040")
    assert incident.status is S.CANCELLED
    assert incident.parent_id == "INC-2026-0040"
    with pytest.raises(InvalidIncidentError):
        new_incident(clock, 43).cancel(ADMIN, clock, CancelReason.DUPLICATE)


def test_event_bus_delivers_events_to_subscribers(clock: FakeClock) -> None:
    bus = EventBus()
    received: list[IncidentStateChanged] = []
    bus.subscribe(IncidentStateChanged, received.append)
    incident = new_incident(clock)
    incident.classify(category_id=4, actor_id=0, clock=clock)
    for event in incident.pull_events():
        bus.publish(event)
    assert [e.to_status for e in received] == [S.CLASSIFIED]


def test_review_refused_actions_leave_the_incident_unchanged(clock: FakeClock) -> None:
    incident = in_progress(clock)
    incident.resolve(TECH, clock, summary="fixed")
    with pytest.raises(InvalidUserInputError):
        incident.reject(REPORTER, clock, reason="  ")
    assert (incident.status, incident.reopen_count, incident.notes) == (S.RESOLVED, 0, ())
    assert incident.resolution is not None


def test_escalation_raises_the_level_and_reassigns(clock: FakeClock) -> None:
    incident = new_incident(clock)
    incident.classify(category_id=4, actor_id=0, clock=clock)
    incident.assign(TECH, actor_id=0, clock=clock)
    assert incident.escalation_level == 0
    incident.pull_events()

    incident.escalate(technician_id=9, level=1, actor_id=None, clock=clock)
    assert (incident.escalation_level, incident.assignee_id) == (1, 9)
    assert incident.status is S.ASSIGNED
    [event] = incident.pull_events()
    assert isinstance(event, IncidentStateChanged)
    assert "level 1" in event.description


def test_escalation_never_moves_back_down_a_level(clock: FakeClock) -> None:
    incident = new_incident(clock)
    incident.classify(category_id=4, actor_id=0, clock=clock)
    incident.assign(TECH, actor_id=0, clock=clock)
    incident.escalate(technician_id=9, level=2, actor_id=None, clock=clock)
    for level in (1, 2):
        with pytest.raises(InvalidIncidentError):
            incident.escalate(technician_id=10, level=level, actor_id=None, clock=clock)
    assert (incident.escalation_level, incident.assignee_id) == (2, 9)


def test_escalation_is_refused_once_the_incident_is_closed(clock: FakeClock) -> None:
    incident = in_progress(clock)
    incident.resolve(TECH, clock, summary="fixed")
    incident.verify(REPORTER, clock, rating=5)
    incident.close(ADMIN, clock)
    with pytest.raises(InvalidStateTransitionError):
        incident.escalate(technician_id=9, level=1, actor_id=None, clock=clock)
    assert incident.escalation_level == 0
