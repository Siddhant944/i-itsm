"""Response models for the admin's SLA violations screen (blueprint §9)."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.sla import ViolationKind


class ViolationResponse(BaseModel):
    incident_id: str
    kind: ViolationKind
    cycle: int
    deadline: datetime
    detected_at: datetime
    escalated_to_level: int | None
    is_breach: bool


class TickResponse(BaseModel):
    """What one monitor run did; the demo and the tests read this."""

    warned: int
    breached: int
    escalated: list[str]
    auto_closed: list[str]
