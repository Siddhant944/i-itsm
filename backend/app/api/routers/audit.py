"""The audit log and its integrity check (blueprint §8, BR-10)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuditDep, requires
from app.api.schemas.admin import (
    AuditPageResponse,
    AuditRecordResponse,
    AuditVerificationResponse,
)
from app.domain.permissions import Permission
from app.domain.users import User

router = APIRouter(prefix="/audit", tags=["audit"])

MAX_AUDIT_PAGE = 200


@router.get("", response_model=AuditPageResponse)
def log(
    user: Annotated[User, Depends(requires(Permission.AUDIT_VIEW))],
    audit: AuditDep,
    incident_id: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPageResponse:
    """The newest records first. ``sequence`` is the record's position in the whole chain,
    filtered or not, so it matches what "verify integrity" reports."""
    total = audit.count(incident_id=incident_id)
    size = max(min(limit, total - offset), 0)
    start = max(total - offset - size, 0)
    page = audit.numbered_history(incident_id=incident_id, limit=size, offset=start) if size else ()
    items = [
        AuditRecordResponse(
            sequence=position,
            occurred_at=record.occurred_at,
            action=record.action.value,
            actor_id=record.actor_id,
            incident_id=record.incident_id,
            details=dict(record.details),
            hash=record.hash,
        )
        for position, record in page
    ]
    items.reverse()
    return AuditPageResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/verify", response_model=AuditVerificationResponse)
def verify(
    user: Annotated[User, Depends(requires(Permission.AUDIT_VERIFY))], audit: AuditDep
) -> AuditVerificationResponse:
    """Recompute the whole hash chain and report the first break, if there is one."""
    result = audit.verify()
    return AuditVerificationResponse(
        intact=result.intact,
        checked=result.checked,
        broken_at=result.broken_at,
        summary=result.summary,
    )
