"""What the admin configures as data (blueprint §3): SLA policies and the assignment strategy.

Catalogue edits live beside the catalogue reads in ``catalogue.py``.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ConfigurationDep, requires
from app.api.schemas.admin import (
    AssignmentSettingsRequest,
    AssignmentSettingsResponse,
    AssignmentWeights,
    SLAPolicyRequest,
    SLAPolicyResponse,
)
from app.domain.assignment import AssignmentSettings
from app.domain.permissions import Permission
from app.domain.priority import Priority
from app.domain.sla import SLATarget, SLATier
from app.domain.users import User

router = APIRouter(tags=["configuration"])

SLAManager = Annotated[User, Depends(requires(Permission.SLA_MANAGE))]
StrategyManager = Annotated[User, Depends(requires(Permission.STRATEGY_MANAGE))]


@router.get("/sla/policies", response_model=list[SLAPolicyResponse])
def policies(user: SLAManager, configuration: ConfigurationDep) -> list[SLAPolicyResponse]:
    """The §5.2 grid: one response and one resolution target per tier and priority."""
    table = configuration.policies()
    return [
        _policy(tier, priority, table[(tier, priority)])
        for tier in SLATier
        for priority in Priority
        if (tier, priority) in table
    ]


@router.put("/sla/policies/{tier}/{priority}", response_model=SLAPolicyResponse)
def set_policy(
    tier: SLATier,
    priority: Priority,
    body: SLAPolicyRequest,
    user: SLAManager,
    configuration: ConfigurationDep,
) -> SLAPolicyResponse:
    target = configuration.set_policy(
        user,
        tier,
        priority,
        response=timedelta(minutes=body.response_minutes),
        resolution=timedelta(minutes=body.resolution_minutes),
    )
    return _policy(tier, priority, target)


@router.get("/config/assignment", response_model=AssignmentSettingsResponse)
def assignment(
    user: StrategyManager, configuration: ConfigurationDep
) -> AssignmentSettingsResponse:
    """The active assignment strategy and the smart strategy's weights (§5.3)."""
    return _assignment(configuration.assignment(), configuration.strategies())


@router.put("/config/assignment", response_model=AssignmentSettingsResponse)
def set_assignment(
    body: AssignmentSettingsRequest, user: StrategyManager, configuration: ConfigurationDep
) -> AssignmentSettingsResponse:
    """Switch strategy at runtime; the next assignment uses it."""
    weights = body.weights
    settings = AssignmentSettings(
        strategy=body.strategy,
        weights=(weights.skills, weights.capacity, weights.experience, weights.history),
    )
    saved = configuration.set_assignment(user, settings)
    return _assignment(saved, configuration.strategies())


def _policy(tier: SLATier, priority: Priority, target: SLATarget) -> SLAPolicyResponse:
    return SLAPolicyResponse(
        tier=tier,
        priority=priority,
        response_minutes=int(target.response.total_seconds() // 60),
        resolution_minutes=int(target.resolution.total_seconds() // 60),
    )


def _assignment(
    settings: AssignmentSettings, available: tuple[str, ...]
) -> AssignmentSettingsResponse:
    skills, capacity, experience, history = settings.weights
    return AssignmentSettingsResponse(
        strategy=settings.strategy,
        weights=AssignmentWeights(
            skills=skills, capacity=capacity, experience=experience, history=history
        ),
        available=list(available),
    )
