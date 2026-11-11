"""Moving time on purpose (D-009).

Playwright and the demo need to show what happens five minutes after a P1 is reported without
waiting five minutes. This router exists only when ``APP_ENV`` is ``test`` or ``demo``, and it
can only move the clock forward — a clock that can go backwards would break the SLA invariants
the rest of the system relies on.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, MonitorDep, ServicesDep
from app.core.clock import FakeClock, in_ist
from app.domain.errors import InvalidUserInputError

router = APIRouter(prefix="/dev", tags=["dev"])
MAX_ADVANCE_SECONDS = 60 * 60 * 24 * 14  # a fortnight is more than any demo needs


class ClockResponse(BaseModel):
    """Where the application thinks it is in time."""

    now: datetime
    now_ist: str
    mode: str
    controllable: bool
    tick_seconds: float


class AdvanceRequest(BaseModel):
    seconds: int = Field(ge=1, le=MAX_ADVANCE_SECONDS)
    tick: bool = Field(
        default=True, description="Run the SLA monitor afterwards, as the scheduler would"
    )


class AdvanceResponse(ClockResponse):
    """The new time, and what the monitor did on the way there."""

    warned: int
    breached: int
    escalated: list[str]
    auto_closed: list[str]


@router.get("/clock", response_model=ClockResponse)
def read_clock(user: CurrentUser, services: ServicesDep) -> ClockResponse:
    """The current time as the application sees it."""
    return _state(services)


@router.post("/clock/advance", response_model=AdvanceResponse)
def advance_clock(
    user: CurrentUser,
    services: ServicesDep,
    monitor: MonitorDep,
    payload: Annotated[AdvanceRequest, Body()],
) -> AdvanceResponse:
    """Move the clock forward, then tick the monitor so the consequences are visible."""
    clock = services.clock
    if not isinstance(clock, FakeClock):
        raise InvalidUserInputError(
            {"clock_mode": "Set CLOCK_MODE=fake to control the clock (D-009)."}
        )
    clock.advance(timedelta(seconds=payload.seconds))
    report = monitor.tick() if payload.tick else None
    state = _state(services)
    return AdvanceResponse(
        **state.model_dump(),
        warned=len(report.warned) if report else 0,
        breached=len(report.breached) if report else 0,
        escalated=list(report.escalated) if report else [],
        auto_closed=list(report.auto_closed) if report else [],
    )


def _state(services: ServicesDep) -> ClockResponse:
    now = services.clock.now()
    return ClockResponse(
        now=now,
        now_ist=in_ist(now).strftime("%d %b %Y, %H:%M:%S IST"),
        mode=type(services.clock).__name__,
        controllable=isinstance(services.clock, FakeClock),
        tick_seconds=services.clock.real_seconds(timedelta(seconds=30)),
    )
