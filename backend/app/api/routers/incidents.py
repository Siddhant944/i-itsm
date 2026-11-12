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
    ConfirmDuplicateRequest,
    CorrelationResponse,
    DuplicateCheckResponse,
    IncidentResponse,
    IncidentSummaryResponse,
    NoteRequest,
    PastFixResponse,
    PriorityOverrideRequest,
    RatingRequest,
    ReasonRequest,
    ReassignRequest,
    RelatedIncidentResponse,
    ReportedIncidentResponse,
    ReportIncidentRequest,
    ResolveRequest,
    RiskResponse,
    SimilarRequest,
    SuggestedResolutionResponse,
    SuggestionResponse,
    detail_of,
    linked,
    similar_of,
    summary_of,
)
from app.core.clock import Clock
from app.domain.assignment import CandidateScore
from app.domain.dependency_graph import Correlation, hint
from app.domain.incident import Incident
from app.domain.permissions import Permission
from app.domain.ports import Classification
from app.domain.users import User
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/incidents", tags=["incidents"])

Reporter = Annotated[User, Depends(requires(Permission.INCIDENT_CREATE))]
Worker = Annotated[User, Depends(requires(Permission.INCIDENT_WORK))]
MAX_PAGE = 200
#: How many related incidents one correlation answer lists on each side.
MAX_RELATED = 10


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
        follow=payload.follow,
    )
    return ReportedIncidentResponse(
        incident=_full(incidents, result.incident, services.clock),
        suggestion=_suggestion(result.suggestion),
        assignment=None if result.assignment is None else _score(result.assignment),
        queued_for_team_lead=result.queued_for_team_lead,
        needs_triage=result.needs_triage,
        possible_duplicates=[similar_of(c) for c in result.possible_duplicates],
        followed=None if result.followed is None else linked(result.followed),
    )


@router.post("/classify", response_model=SuggestionResponse | None)
def classify(
    payload: ClassifyRequest, user: Reporter, incidents: IncidentsDep
) -> SuggestionResponse | None:
    """Suggest a category for what the reporter has typed. Advice only (§6.1)."""
    return _suggestion(incidents.classify_text(payload.text))


@router.post("/similar", response_model=DuplicateCheckResponse)
def similar(
    payload: SimilarRequest, user: Reporter, incidents: IncidentsDep
) -> DuplicateCheckResponse:
    """Open incidents that look like what is being typed (§6.2, BR-09). Advice only.

    Only an incident's id, title and status are shown, so the reporter can follow it instead
    of filing the same problem again.
    """
    check = incidents.similar_incidents(
        user,
        title=payload.title,
        description=payload.description,
        service_id=payload.service_id,
    )
    return DuplicateCheckResponse(
        provider=check.provider, candidates=[similar_of(c) for c in check.candidates]
    )


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
    return _full(incidents, incidents.get(user, incident_id), services.clock)


@router.get("/{incident_id}/possible-duplicates", response_model=DuplicateCheckResponse)
def possible_duplicates(
    incident_id: str,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_CONFIRM_DUPLICATE))],
    incidents: IncidentsDep,
) -> DuplicateCheckResponse:
    """What this incident may be a duplicate of, for the technician to confirm (§6.2)."""
    check = incidents.possible_duplicates(user, incident_id)
    return DuplicateCheckResponse(
        provider=check.provider, candidates=[similar_of(c) for c in check.candidates]
    )


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
    return _full(incidents, incidents.acknowledge(user, incident_id), services.clock)


@router.post("/{incident_id}/start", response_model=IncidentResponse)
def start(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return _full(incidents, incidents.start(user, incident_id), services.clock)


@router.post("/{incident_id}/notes", response_model=IncidentResponse)
def add_note(
    incident_id: str,
    payload: NoteRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    return _full(incidents, incidents.add_note(user, incident_id, payload.text), services.clock)


@router.post("/{incident_id}/request-information", response_model=IncidentResponse)
def request_information(
    incident_id: str,
    payload: NoteRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """Ask the reporter a question; the resolution clock pauses (BR-07)."""
    return _full(
        incidents, incidents.request_information(user, incident_id, payload.text), services.clock
    )


@router.post("/{incident_id}/resume", response_model=IncidentResponse)
def resume(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return _full(incidents, incidents.resume(user, incident_id), services.clock)


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve(
    incident_id: str,
    payload: ResolveRequest,
    user: Worker,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-04: a resolution summary is required."""
    return _full(incidents, incidents.resolve(user, incident_id, payload.summary), services.clock)


@router.post("/{incident_id}/close", response_model=IncidentResponse)
def close(
    incident_id: str, user: Worker, incidents: IncidentsDep, services: ServicesDep
) -> IncidentResponse:
    return _full(incidents, incidents.close(user, incident_id), services.clock)


@router.post("/{incident_id}/reassign", response_model=IncidentResponse)
def reassign(
    incident_id: str,
    payload: ReassignRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_REASSIGN))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-06: refused when the technician is unavailable or would exceed the cap."""
    return _full(
        incidents, incidents.reassign(user, incident_id, payload.technician_id), services.clock
    )


@router.post("/{incident_id}/priority", response_model=IncidentResponse)
def override_priority(
    incident_id: str,
    payload: PriorityOverrideRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_OVERRIDE_PRIORITY))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-05: the reason is required and the override is audited."""
    return _full(
        incidents,
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
    return _full(
        incidents,
        incidents.override_category(user, incident_id, payload.category_id),
        services.clock,
    )


@router.get("/{incident_id}/suggested-resolution", response_model=SuggestedResolutionResponse)
def suggested_resolution(
    incident_id: str,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_VIEW_ASSIGNED))],
    incidents: IncidentsDep,
) -> SuggestedResolutionResponse:
    """§6.1: the three most similar resolved incidents, and a summary citing only them."""
    found = incidents.suggested_resolution(user, incident_id)
    return SuggestedResolutionResponse(
        fixes=[
            PastFixResponse(
                id=fix.incident.id,
                title=fix.incident.title,
                status=fix.incident.status,
                resolution=fix.resolution,
                score=min(1.0, fix.score),
            )
            for fix in found.fixes
        ],
        summary=found.summary,
        source=found.source,
    )


@router.get("/{incident_id}/risk", response_model=RiskResponse | None)
def risk(incident_id: str, user: CurrentUser, incidents: IncidentsDep) -> RiskResponse | None:
    """§6.3: predicted breach risk from comparable past incidents; null when nothing to forecast."""
    found = incidents.risk(user, incident_id)
    if found is None:
        return None
    return RiskResponse(
        at_risk=found.at_risk,
        method=found.method,
        reason=found.reason,
        probability=found.probability,
        samples=found.samples,
    )


@router.get("/{incident_id}/correlation", response_model=CorrelationResponse)
def correlation(
    incident_id: str,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_VIEW_ASSIGNED))],
    incidents: IncidentsDep,
) -> CorrelationResponse:
    """§6.2: the likely root cause upstream, and the open incidents it may be causing."""
    report = incidents.correlation(user, incident_id)
    names = incidents.service_names()

    def related(found: Correlation) -> RelatedIncidentResponse:
        other = found.incident
        return RelatedIncidentResponse(
            id=other.id,
            title=other.title,
            status=other.status,
            priority=other.priority,
            service_id=other.service_id,
            service_name=names.get(other.service_id, str(other.service_id)),
            hops=found.reach.hops,
            path=[names.get(s, str(s)) for s in found.reach.path],
        )

    return CorrelationResponse(
        hint=hint(report, names),
        root_causes=[related(c) for c in report.root_causes[:MAX_RELATED]],
        impacted=[related(c) for c in report.impacted[:MAX_RELATED]],
    )


@router.post("/{incident_id}/confirm-duplicate", response_model=IncidentResponse)
def confirm_duplicate(
    incident_id: str,
    payload: ConfirmDuplicateRequest,
    user: Annotated[User, Depends(requires(Permission.INCIDENT_CONFIRM_DUPLICATE))],
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-09: cancel this incident as a duplicate; its reporter then follows the parent."""
    return _full(
        incidents, incidents.confirm_duplicate(user, incident_id, payload.parent_id), services.clock
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
    return _full(
        incidents, incidents.provide_information(user, incident_id, payload.text), services.clock
    )


@router.post("/{incident_id}/verify", response_model=IncidentResponse)
def verify(
    incident_id: str,
    payload: RatingRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """BR-03: only the reporter verifies, and the rating feeds the CSAT figure."""
    return _full(
        incidents,
        incidents.verify(user, incident_id, payload.rating, payload.comment),
        services.clock,
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
    return _full(incidents, incidents.reject(user, incident_id, payload.reason), services.clock)


@router.post("/{incident_id}/cancel", response_model=IncidentResponse)
def cancel(
    incident_id: str,
    payload: CancelRequest,
    user: CurrentUser,
    incidents: IncidentsDep,
    services: ServicesDep,
) -> IncidentResponse:
    """The reporter withdraws their own; an admin may cancel any, including as a duplicate."""
    return _full(
        incidents,
        incidents.cancel(user, incident_id, payload.reason, payload.duplicate_of),
        services.clock,
    )


# ---------------------------------------------------------------- mapping helpers
def _full(incidents: IncidentService, incident: Incident, clock: Clock) -> IncidentResponse:
    """The incident with its duplicate links, so every answer shows the same picture (§6.2)."""
    parent, count = incidents.duplicate_links(incident)
    return detail_of(incident, clock, duplicate_of=parent, duplicate_count=count)


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
