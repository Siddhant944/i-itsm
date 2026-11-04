"""The incident endpoints (blueprint §4, §5, §7).

Each route validates its body with Pydantic, calls one IncidentService method and maps the
result. The role check is a dependency, so it is declared on the route and appears in the
OpenAPI document; the ownership checks (BR-01, BR-02, BR-03) happen inside the service, which
is the only place that has the incident to check against.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, IncidentsDep, ServicesDep, requires
from app.api.schemas.incidents import (
    AssignmentAdviceResponse,
    CancelRequest,
    CandidateScoreResponse,
    CategoryOverrideRequest,
    ClassifyRequest,
    IncidentResponse,
    IncidentSummaryResponse,
    NoteRequest,
    PriorityOverrideRequest,
    RatingRequest,
    ReasonRequest,
    ReassignRequest,
    ReportedIncidentResponse,
    ReportIncidentRequest,
    ResolveRequest,
    SuggestionResponse,
    detail_of,
    summary_of,
)
from app.domain.assignment import CandidateScore
from app.domain.permissions import Permission
from app.domain.ports import Classification
from app.domain.users import User

router = APIRouter(prefix="/incidents", tags=["incidents"])

Reporter = Annotated[User, Depends(requires(Permission.INCIDENT_CREATE))]
Worker = Annotated[User, Depends(requires(Permission.INCIDENT_WORK))]
MAX_PAGE = 200


# ---------------------------------------------------------------- reporting
@router.post("", response_model=ReportedIncidentResponse, status_code=status.HTTP_201_CREATED)
def report(
    payload: ReportIncidentRequest,
    user: Reporter,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> ReportedIncidentResponse:
    """Report an incident. It is classified, prioritised, given an SLA and assigned."""
    result = incidents.report(
        user,
        title=payload.title,
        description=payload.description,
        service_id=payload.service_id,
        impact=payload.impact,
        urgency=payload.urgency,
        category_id=payload.category_id,
    )
    return ReportedIncidentResponse(
        incident=detail_of(result.incident, services.clock),
        suggestion=_suggestion(result.suggestion),
        assignment=None if result.assignment is None else _score(result.assignment),
        queued_for_team_lead=result.queued_for_team_lead,
        needs_triage=result.needs_triage,
    )


@router.post("/classify", response_model=SuggestionResponse | None)
def classify(
    payload: ClassifyRequest, user: Reporter, incidents: IncidentsDep
) -> SuggestionResponse | None:
    """Suggest a category for what the reporter has typed. Advice only (§6.1)."""
    return _suggestion(incidents.classify_text(payload.text))


# ---------------------------------------------------------------- reading
@router.get("/mine", response_model=list[IncidentSummaryResponse])
def mine(
    user: CurrentUser, incidents: IncidentsDep, services: ServicesDep
) -> list[IncidentSummaryResponse]:
    """What the caller reported (BR-01)."""
    return [summary_of(i, services.clock) for i in incidents.my_incidents(user)]


@router.get("/queue", response_model=list[IncidentSummaryResponse])
def queue(
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[IncidentSummaryResponse]:
    """What the calling technician is carrying."""
    return [summary_of(i, services.clock) for i in incidents.my_queue(user)[:limit]]


@router.get("/{incident_id}", response_model=IncidentResponse)
def detail(
    incident_id: str, user: CurrentUser, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    """One incident, if the caller may see it (BR-01). 403 otherwise, never a leak."""
    return detail_of(incidents.get(user, incident_id), services.clock)


@router.get("/{incident_id}/assignment-advice", response_model=AssignmentAdviceResponse)
def assignment_advice(
    incident_id: str,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_REASSIGN))],
    incidents: IncidentsDep,
) -> AssignmentAdviceResponse:
    """The ranked technicians and the reasons behind the ranking (§5.3, §6)."""
    advice = incidents.assignment_advice(incidents.get(user, incident_id))
    return AssignmentAdviceResponse(
        strategy=advice.strategy,
        ranked=[_score(score) for score in advice.ranked],
    )


# ---------------------------------------------------------------- technician actions
@router.post("/{incident_id}/acknowledge", response_model=IncidentResponse)
def acknowledge(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    """BR-02, BR-07: acknowledging meets the response SLA."""
    return detail_of(incidents.acknowledge(user, incident_id), services.clock)


@router.post("/{incident_id}/start", response_model=IncidentResponse)
def start(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return detail_of(incidents.start(user, incident_id), services.clock)


@router.post("/{incident_id}/notes", response_model=IncidentResponse)
def add_note(
    incident_id: str,
    payload: NoteRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    return detail_of(incidents.add_note(user, incident_id, payload.text), services.clock)


@router.post("/{incident_id}/request-information", response_model=IncidentResponse)
def request_information(
    incident_id: str,
    payload: NoteRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """Ask the reporter a question; the resolution clock pauses (BR-07)."""
    return detail_of(incidents.request_information(user, incident_id, payload.text), services.clock)


@router.post("/{incident_id}/resume", response_model=IncidentResponse)
def resume(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return detail_of(incidents.resume(user, incident_id), services.clock)


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve(
    incident_id: str,
    payload: ResolveRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-04: a resolution summary is required."""
    return detail_of(incidents.resolve(user, incident_id, payload.summary), services.clock)


@router.post("/{incident_id}/close", response_model=IncidentResponse)
def close(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return detail_of(incidents.close(user, incident_id), services.clock)


@router.post("/{incident_id}/reassign", response_model=IncidentResponse)
def reassign(
    incident_id: str,
    payload: ReassignRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_REASSIGN))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-06: refused when the technician is unavailable or would exceed the cap."""
    return detail_of(incidents.reassign(user, incident_id, payload.technician_id), services.clock)


@router.post("/{incident_id}/priority", response_model=IncidentResponse)
def override_priority(
    incident_id: str,
    payload: PriorityOverrideRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_OVERRIDE_PRIORITY))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-05: the reason is required and the override is audited."""
    return detail_of(
        incidents.override_priority(user, incident_id, payload.priority, payload.reason),
        services.clock,
    )


@router.post("/{incident_id}/category", response_model=IncidentResponse)
def override_category(
    incident_id: str,
    payload: CategoryOverrideRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_OVERRIDE_CATEGORY))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """Correct the category, whether the AI or the reporter chose it (§6.1)."""
    return detail_of(
        incidents.override_category(user, incident_id, payload.category_id), services.clock
    )


# ---------------------------------------------------------------- reporter actions
@router.post("/{incident_id}/information", response_model=IncidentResponse)
def provide_information(
    incident_id: str,
    payload: NoteRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """The reporter answers; an incident on hold resumes (D-006)."""
    return detail_of(incidents.provide_information(user, incident_id, payload.text), services.clock)


@router.post("/{incident_id}/verify", response_model=IncidentResponse)
def verify(
    incident_id: str,
    payload: RatingRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-03: only the reporter verifies, and the rating feeds the CSAT figure."""
    return detail_of(
        incidents.verify(user, incident_id, payload.rating, payload.comment), services.clock
    )


@router.post("/{incident_id}/reject", response_model=IncidentResponse)
def reject(
    incident_id: str,
    payload: ReasonRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-03, BR-04: only the reporter rejects, and only from RESOLVED."""
    return detail_of(incidents.reject(user, incident_id, payload.reason), services.clock)


@router.post("/{incident_id}/cancel", response_model=IncidentResponse)
def cancel(
    incident_id: str,
    payload: CancelRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """The reporter withdraws their own; an admin may cancel any, including as a duplicate."""
    return detail_of(
        incidents.cancel(user, incident_id, payload.reason, payload.duplicate_of),
        services.clock,
    )


# ---------------------------------------------------------------- mapping helpers
def _suggestion(classification: Classification | None) -> SuggestionResponse | None:
    if classification is None:
        return None
    return SuggestionResponse(
        category_id=classification.category_id,
        confidence=classification.confidence,
        source=classification.source,
    )


def _score(score: CandidateScore) -> CandidateScoreResponse:
    return CandidateScoreResponse(
        technician_id=score.technician_id, score=score.score, reasons=list(score.reasons)
    )
