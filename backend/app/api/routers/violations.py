"""The SLA violations screen, and running the monitor by hand (blueprint §9, §5.2).

The monitor normally runs on a timer (D-003). The manual endpoint exists so an admin — and the
demo — can make it run now and see what it found, without waiting for the next tick.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import MonitorDep, UowDep, requires
from app.api.schemas.violations import TickResponse, ViolationResponse
from app.domain.permissions import Permission
from app.domain.sla import SLAViolation
from app.domain.users import User

router = APIRouter(prefix="/sla", tags=["sla"])
MAX_PAGE = 200

Watcher = Annotated[User, Depends(requires(Permission.SLA_VIOLATIONS_VIEW))]


@router.get("/violations", response_model=list[ViolationResponse])
def violations(
    user: Watcher,
    uow: UowDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[ViolationResponse]:
    """Everything the monitor has recorded, newest first."""
    return [_response(violation) for violation in uow.violations.recent(limit)]


@router.get("/violations/{incident_id}", response_model=list[ViolationResponse])
def for_incident(incident_id: str, user: Watcher, uow: UowDep) -> list[ViolationResponse]:
    """One incident's own history of warnings and breaches, oldest first."""
    return [_response(violation) for violation in uow.violations.for_incident(incident_id)]


@router.post("/tick", response_model=TickResponse)
def tick(user: Watcher, monitor: MonitorDep) -> TickResponse:
    """Run the monitor now and report what it did (the scheduler does this on a timer)."""
    report = monitor.tick()
    return TickResponse(
        warned=len(report.warned),
        breached=len(report.breached),
        escalated=list(report.escalated),
        auto_closed=list(report.auto_closed),
    )


def _response(violation: SLAViolation) -> ViolationResponse:
    return ViolationResponse(
        incident_id=violation.incident_id,
        kind=violation.kind,
        cycle=violation.cycle,
        deadline=violation.deadline,
        detected_at=violation.detected_at,
        escalated_to_level=violation.escalated_to_level,
        is_breach=violation.kind.is_breach,
    )
