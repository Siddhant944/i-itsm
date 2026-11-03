"""The Incident aggregate (blueprint §3, §4).

An Incident composes its work notes, resolution and feedback: they live and die with it
and its SLA clock. Its status changes only through intention-revealing methods,
each of which asks the current State object whether the move is legal, applies the change,
and records a domain event for audit and notifications.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.core.clock import Clock
from app.domain.errors import (
    InvalidIncidentError,
    InvalidUserInputError,
    UnauthorizedOperationError,
)
from app.domain.events import (
    DomainEvent,
    IncidentCreated,
    IncidentStateChanged,
    PriorityChanged,
    WorkNoteAdded,
)
from app.domain.priority import Priority, PriorityAssessment
from app.domain.sla import SLAClock, SLATarget
from app.domain.states import IncidentState, IncidentStatus, state_for

MAX_TITLE_LENGTH = 200
MIN_RATING, MAX_RATING = 1, 5
MIN_FACTOR, MAX_FACTOR = 1, 3  # impact and urgency answers (blueprint §5.1)


class NoteKind(StrEnum):
    NOTE = "note"
    INFO_REQUEST = "info_request"
    INFO_RESPONSE = "info_response"


class CancelReason(StrEnum):
    WITHDRAWN = "withdrawn"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class WorkNote:
    author_id: int
    created_at: datetime
    kind: NoteKind
    text: str


@dataclass(frozen=True, slots=True)
class Resolution:
    resolver_id: int
    resolved_at: datetime
    summary: str


@dataclass(frozen=True, slots=True)
class Feedback:
    rating: int
    comment: str
    given_at: datetime


def _text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidUserInputError({field: "Must not be empty."})
    return cleaned


class Incident:
    """A reported problem and everything that happens to it until closure."""

    def __init__(
        self,
        incident_id: str,
        reporter_id: int,
        title: str,
        description: str,
        service_id: int,
        impact: int,
        urgency: int,
        created_at: datetime,
        status: IncidentStatus = IncidentStatus.NEW,
    ) -> None:
        self.__id = incident_id
        self.__reporter_id = reporter_id
        self.__title = title
        self.__description = description
        self.__service_id = service_id
        self.__impact = impact
        self.__urgency = urgency
        self.__created_at = created_at
        self.__state: IncidentState = state_for(status)
        self.__category_id: int | None = None
        self.__assignee_id: int | None = None
        self.__parent_id: str | None = None
        self.__cancel_reason: CancelReason | None = None
        self.__acknowledged_at: datetime | None = None
        self.__resolved_at: datetime | None = None
        self.__closed_at: datetime | None = None
        self.__reopen_count = 0
        self.__priority: Priority | None = None
        self.__sla_clock: SLAClock | None = None
        self.__priority_score: int | None = None
        self.__priority_overridden = False
        self.__notes: list[WorkNote] = []
        self.__resolution: Resolution | None = None
        self.__feedback: Feedback | None = None
        self.__events: list[DomainEvent] = []

    # ------------------------------------------------------------ read-only views
    @property
    def id(self) -> str:
        return self.__id

    @property
    def reporter_id(self) -> int:
        return self.__reporter_id

    @property
    def title(self) -> str:
        return self.__title

    @property
    def description(self) -> str:
        return self.__description

    @property
    def service_id(self) -> int:
        return self.__service_id

    @property
    def impact(self) -> int:
        return self.__impact

    @property
    def urgency(self) -> int:
        return self.__urgency

    @property
    def status(self) -> IncidentStatus:
        return self.__state.status

    @property
    def category_id(self) -> int | None:
        return self.__category_id

    @property
    def assignee_id(self) -> int | None:
        return self.__assignee_id

    @property
    def parent_id(self) -> str | None:
        return self.__parent_id

    @property
    def cancel_reason(self) -> CancelReason | None:
        return self.__cancel_reason

    @property
    def created_at(self) -> datetime:
        return self.__created_at

    @property
    def acknowledged_at(self) -> datetime | None:
        """Time of the first acknowledgement (meets the response SLA, BR-07)."""
        return self.__acknowledged_at

    @property
    def resolved_at(self) -> datetime | None:
        return self.__resolved_at

    @property
    def closed_at(self) -> datetime | None:
        return self.__closed_at

    @property
    def reopen_count(self) -> int:
        return self.__reopen_count

    @property
    def priority(self) -> Priority | None:
        return self.__priority

    @property
    def priority_score(self) -> int | None:
        return self.__priority_score

    @property
    def priority_overridden(self) -> bool:
        return self.__priority_overridden

    @property
    def sla_clock(self) -> SLAClock | None:
        return self.__sla_clock

    def apply_sla(self, target: SLATarget) -> None:
        """Start the SLA clock from creation, or retarget it after a priority change."""
        if self.__sla_clock is None:
            self.__sla_clock = SLAClock(self.__created_at, target)
        else:
            self.__sla_clock.retarget(target)

    @property
    def notes(self) -> tuple[WorkNote, ...]:
        return tuple(self.__notes)

    @property
    def resolution(self) -> Resolution | None:
        return self.__resolution

    @property
    def feedback(self) -> Feedback | None:
        return self.__feedback

    def _record(self, event: DomainEvent) -> None:
        """Internal: queue an event (used by the aggregate and its factory)."""
        self.__events.append(event)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Hand over and forget the events recorded since the last call."""
        events, self.__events = tuple(self.__events), []
        return events

    # ------------------------------------------------------------ lifecycle
    def _move(self, target: IncidentStatus, actor_id: int | None, clock: Clock, text: str) -> None:
        before = self.__state.status
        self.__state = state_for(target)
        self.__events.append(
            IncidentStateChanged(clock.now(), self.__id, actor_id, before, target, text)
        )

    def classify(self, category_id: int, actor_id: int | None, clock: Clock) -> None:
        target = self.__state.classify()
        self.__category_id = category_id
        self._move(target, actor_id, clock, f"Classified as category {category_id}")

    def assign(self, technician_id: int, actor_id: int | None, clock: Clock) -> None:
        """Assign, reassign or escalate to ``technician_id``."""
        target = self.__state.assign()
        self.__assignee_id = technician_id
        self._move(target, actor_id, clock, f"Assigned to user {technician_id}")

    def acknowledge(self, actor_id: int, clock: Clock) -> None:
        target = self.__state.acknowledge()
        if self.__acknowledged_at is None:
            self.__acknowledged_at = clock.now()
        if self.__sla_clock is not None:
            self.__sla_clock.respond(clock.now())
        self._move(target, actor_id, clock, "Technician acknowledged the incident")

    def start(self, actor_id: int, clock: Clock) -> None:
        self._move(self.__state.start(), actor_id, clock, "Investigation started")

    def hold(self, actor_id: int, clock: Clock, question: str) -> None:
        """Ask the reporter for information; the resolution clock pauses (BR-07)."""
        target = self.__state.hold()
        self._add(actor_id, clock, NoteKind.INFO_REQUEST, _text(question, "question"))
        if self.__sla_clock is not None:
            self.__sla_clock.pause(clock.now())
        self._move(target, actor_id, clock, "Waiting for information from the reporter")

    def resume(self, actor_id: int, clock: Clock) -> None:
        target = self.__state.resume()
        self._resume_sla(clock)
        self._move(target, actor_id, clock, "Work resumed")

    def provide_info(self, actor_id: int, clock: Clock, answer: str) -> None:
        """The reporter answers; an incident on hold resumes (D-006)."""
        self._add(actor_id, clock, NoteKind.INFO_RESPONSE, _text(answer, "answer"))
        if self.__state.status is IncidentStatus.ON_HOLD:
            target = self.__state.resume()
            self._resume_sla(clock)
            self._move(target, actor_id, clock, "Reporter provided information")

    def resolve(self, actor_id: int, clock: Clock, summary: str) -> None:
        """Resolving requires a resolution summary (BR-04)."""
        target = self.__state.resolve()
        if not summary.strip():
            msg = "A resolution summary is required."
            raise InvalidIncidentError(msg)
        self.__resolution = Resolution(actor_id, clock.now(), summary.strip())
        self.__resolved_at = clock.now()
        self._stop_sla(clock)
        self._move(target, actor_id, clock, "Resolution provided")

    def verify(self, actor_id: int, clock: Clock, rating: int, comment: str = "") -> None:
        """Only the reporter verifies (BR-03); records feedback."""
        self._require_reporter(actor_id)
        target = self.__state.verify()
        if not MIN_RATING <= rating <= MAX_RATING:
            raise InvalidUserInputError({"rating": f"Must be {MIN_RATING}-{MAX_RATING}."})
        self.__feedback = Feedback(rating, comment.strip(), clock.now())
        self._move(target, actor_id, clock, f"Reporter verified the fix ({rating}/5)")

    def reject(self, actor_id: int, clock: Clock, reason: str) -> None:
        """Only the reporter rejects (BR-03); reopening is possible only from RESOLVED (BR-04)."""
        self._require_reporter(actor_id)
        target = self.__state.reject()
        self._add(actor_id, clock, NoteKind.NOTE, f"Fix rejected: {_text(reason, 'reason')}")
        self.__resolution = None
        self.__resolved_at = None
        self.__reopen_count += 1
        if self.__sla_clock is not None:
            self.__sla_clock.restart(clock.now())
        self._move(target, actor_id, clock, "Reporter rejected the fix; incident reopened")

    def close(self, actor_id: int | None, clock: Clock) -> None:
        target = self.__state.close()
        self.__closed_at = clock.now()
        self._move(target, actor_id, clock, "Incident closed")

    def auto_close(self, clock: Clock) -> None:
        """Close an unverified resolution after 72 h (BR-03); the system is the actor."""
        target = self.__state.auto_close()
        self.__closed_at = clock.now()
        self._move(target, None, clock, "Closed automatically after 72 h without verification")

    def cancel(
        self, actor_id: int, clock: Clock, reason: CancelReason, duplicate_of: str | None = None
    ) -> None:
        target = self.__state.cancel()
        if reason is CancelReason.DUPLICATE and not duplicate_of:
            msg = "A duplicate must name the incident it duplicates."
            raise InvalidIncidentError(msg)
        self.__cancel_reason = reason
        self._stop_sla(clock)
        self.__parent_id = duplicate_of
        self.__closed_at = clock.now()
        label = f"duplicate of {duplicate_of}" if duplicate_of else reason.value
        self._move(target, actor_id, clock, f"Cancelled ({label})")

    # ------------------------------------------------------------ priority (BR-05)
    def prioritise(self, assessment: PriorityAssessment, clock: Clock) -> None:
        """Record the computed priority (the system is the actor)."""
        old = self.__priority
        self.__priority = assessment.priority
        self.__priority_score = assessment.score
        self.__priority_overridden = False
        self._record(
            PriorityChanged(
                clock.now(), self.__id, None, old, assessment.priority, assessment.explanation
            )
        )

    def override_priority(
        self, priority: Priority, reason: str, actor_id: int, clock: Clock
    ) -> None:
        """A technician or admin override; it needs a reason and is audited (BR-05)."""
        if self.__state.is_terminal:
            msg = "A closed or cancelled incident cannot be re-prioritised."
            raise InvalidIncidentError(msg)
        why = _text(reason, "reason")
        old = self.__priority
        self.__priority = priority
        self.__priority_overridden = True
        self._record(PriorityChanged(clock.now(), self.__id, actor_id, old, priority, why))

    # ------------------------------------------------------------ notes
    def add_note(self, actor_id: int, clock: Clock, text: str) -> WorkNote:
        return self._add(actor_id, clock, NoteKind.NOTE, _text(text, "text"))

    def _add(self, actor_id: int, clock: Clock, kind: NoteKind, text: str) -> WorkNote:
        note = WorkNote(actor_id, clock.now(), kind, text)
        self.__notes.append(note)
        self.__events.append(WorkNoteAdded(clock.now(), self.__id, actor_id, kind.value))
        return note

    def _resume_sla(self, clock: Clock) -> None:
        if self.__sla_clock is not None:
            self.__sla_clock.resume(clock.now())

    def _stop_sla(self, clock: Clock) -> None:
        if self.__sla_clock is not None:
            self.__sla_clock.stop(clock.now())

    def _require_reporter(self, actor_id: int) -> None:
        if actor_id != self.__reporter_id:
            msg = "Only the reporter can verify or reject the fix."
            raise UnauthorizedOperationError(msg)


class IncidentFactory:
    """Pattern: Factory. Problem solved: a new incident needs a formatted ID (INC-YYYY-NNNN),
    validated input, the NEW state and an IncidentCreated event; callers get all of it from one
    place instead of repeating the rules.
    """

    @staticmethod
    def create(
        *,
        sequence: int,
        clock: Clock,
        reporter_id: int,
        title: str,
        description: str,
        service_id: int,
        impact: int,
        urgency: int,
    ) -> Incident:
        errors: dict[str, str] = {}
        if not title.strip():
            errors["title"] = "Must not be empty."
        elif len(title.strip()) > MAX_TITLE_LENGTH:
            errors["title"] = f"At most {MAX_TITLE_LENGTH} characters."
        if not description.strip():
            errors["description"] = "Must not be empty."
        for name, value in (("impact", impact), ("urgency", urgency)):
            if not MIN_FACTOR <= value <= MAX_FACTOR:
                errors[name] = f"Must be {MIN_FACTOR}-{MAX_FACTOR}."
        if errors:
            raise InvalidUserInputError(errors)
        now = clock.now()
        incident = Incident(
            f"INC-{now.year}-{sequence:04d}",
            reporter_id,
            title.strip(),
            description.strip(),
            service_id,
            impact,
            urgency,
            now,
        )
        incident._record(IncidentCreated(now, incident.id, reporter_id, incident.title))
        return incident
