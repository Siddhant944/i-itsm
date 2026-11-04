"""Request and response models for incidents (blueprint §4, §5, §6).

Responses carry what each portal needs to render without a second call: the live SLA status and
its deadline, the AI suggestion with its confidence, and the plain-language reasons behind an
assignment. Timestamps go out as UTC; the frontend shows them in IST (§9).
"""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.clock import Clock
from app.domain.incident import (
    MAX_FACTOR,
    MAX_RATING,
    MAX_TITLE_LENGTH,
    MIN_FACTOR,
    MIN_RATING,
    CancelReason,
    Incident,
    NoteKind,
)
from app.domain.priority import Priority
from app.domain.sla import SLAStatus
from app.domain.states import IncidentStatus

Factor = Annotated[int, Field(ge=MIN_FACTOR, le=MAX_FACTOR)]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]


class ReportIncidentRequest(BaseModel):
    """The plain-language report form (§1: no jargon, three simple questions)."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str = Field(min_length=1, max_length=5000)
    service_id: int = Field(ge=1)
    impact: Factor = Field(description="1 just me, 2 my team, 3 everyone")
    urgency: Factor = Field(description="1 when convenient, 2 today, 3 right now")
    category_id: int | None = Field(
        default=None, ge=1, description="The confirmed category; omitted lets the AI suggest one"
    )


class ClassifyRequest(BaseModel):
    """What the reporter has typed so far, for the while-typing suggestion (§6.1)."""

    text: str = Field(min_length=1, max_length=5000)


class SuggestionResponse(BaseModel):
    """An AI suggestion, always shown with its confidence and never applied silently."""

    category_id: int | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


class NoteRequest(BaseModel):
    text: Reason


class RatingRequest(BaseModel):
    rating: int = Field(ge=MIN_RATING, le=MAX_RATING)
    comment: str = Field(default="", max_length=1000)


class ReasonRequest(BaseModel):
    reason: Reason


class ResolveRequest(BaseModel):
    """BR-04: resolving requires a summary."""

    summary: Reason


class ReassignRequest(BaseModel):
    technician_id: int = Field(ge=1)


class PriorityOverrideRequest(BaseModel):
    """BR-05: an override needs a reason and is audited."""

    priority: Priority
    reason: Reason


class CategoryOverrideRequest(BaseModel):
    category_id: int = Field(ge=1)


class CancelRequest(BaseModel):
    reason: CancelReason = CancelReason.WITHDRAWN
    duplicate_of: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _duplicates_name_their_parent(self) -> Self:
        if self.reason is CancelReason.DUPLICATE and not self.duplicate_of:
            msg = "A duplicate must name the incident it duplicates."
            raise ValueError(msg)
        return self


class WorkNoteResponse(BaseModel):
    author_id: int
    created_at: datetime
    kind: NoteKind
    text: str


class ResolutionResponse(BaseModel):
    resolver_id: int
    resolved_at: datetime
    summary: str


class FeedbackResponse(BaseModel):
    rating: int
    comment: str
    given_at: datetime


class SLAResponse(BaseModel):
    """The live SLA picture the chips and countdowns need (§5.2)."""

    response_status: SLAStatus
    resolution_status: SLAStatus
    response_deadline: datetime
    resolution_deadline: datetime
    responded_at: datetime | None
    paused: bool


class IncidentSummaryResponse(BaseModel):
    """One row in a queue or list."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    title: str
    status: IncidentStatus
    priority: Priority | None
    service_id: int
    category_id: int | None
    reporter_id: int
    assignee_id: int | None
    created_at: datetime
    escalation_level: int
    sla: SLAResponse | None


class IncidentResponse(IncidentSummaryResponse):
    """One incident in full, for the detail page and the timeline."""

    description: str
    impact: int
    urgency: int
    priority_score: int | None
    priority_overridden: bool
    parent_id: str | None
    cancel_reason: CancelReason | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    reopen_count: int
    notes: list[WorkNoteResponse]
    resolution: ResolutionResponse | None
    feedback: FeedbackResponse | None


class CandidateScoreResponse(BaseModel):
    """One ranked technician, with the reasons a human can check (§5.3, §6)."""

    technician_id: int
    score: float
    reasons: list[str]


class AssignmentAdviceResponse(BaseModel):
    strategy: str
    ranked: list[CandidateScoreResponse]


class ReportedIncidentResponse(BaseModel):
    """What the report form gets back: the incident, plus what the system did and why."""

    incident: IncidentResponse
    suggestion: SuggestionResponse | None
    assignment: CandidateScoreResponse | None
    queued_for_team_lead: bool
    needs_triage: bool


def sla_of(incident: Incident, clock: Clock) -> SLAResponse | None:
    """The incident's SLA state now, or None before it has been prioritised."""
    sla = incident.sla_clock
    if sla is None:
        return None
    now = clock.now()
    return SLAResponse(
        response_status=sla.response_status(now),
        resolution_status=sla.resolution_status(now),
        response_deadline=sla.response_deadline,
        resolution_deadline=sla.resolution_deadline(now),
        responded_at=sla.responded_at,
        paused=sla.is_paused,
    )


def summary_of(incident: Incident, clock: Clock) -> IncidentSummaryResponse:
    return IncidentSummaryResponse(
        id=incident.id,
        title=incident.title,
        status=incident.status,
        priority=incident.priority,
        service_id=incident.service_id,
        category_id=incident.category_id,
        reporter_id=incident.reporter_id,
        assignee_id=incident.assignee_id,
        created_at=incident.created_at,
        escalation_level=incident.escalation_level,
        sla=sla_of(incident, clock),
    )


def detail_of(incident: Incident, clock: Clock) -> IncidentResponse:
    return IncidentResponse(
        **summary_of(incident, clock).model_dump(),
        description=incident.description,
        impact=incident.impact,
        urgency=incident.urgency,
        priority_score=incident.priority_score,
        priority_overridden=incident.priority_overridden,
        parent_id=incident.parent_id,
        cancel_reason=incident.cancel_reason,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
        closed_at=incident.closed_at,
        reopen_count=incident.reopen_count,
        notes=[
            WorkNoteResponse(
                author_id=note.author_id,
                created_at=note.created_at,
                kind=note.kind,
                text=note.text,
            )
            for note in incident.notes
        ],
        resolution=(
            None
            if incident.resolution is None
            else ResolutionResponse(
                resolver_id=incident.resolution.resolver_id,
                resolved_at=incident.resolution.resolved_at,
                summary=incident.resolution.summary,
            )
        ),
        feedback=(
            None
            if incident.feedback is None
            else FeedbackResponse(
                rating=incident.feedback.rating,
                comment=incident.feedback.comment,
                given_at=incident.feedback.given_at,
            )
        ),
    )
