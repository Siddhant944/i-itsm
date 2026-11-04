from datetime import timedelta

import pytest

from app.domain.escalation import EscalationContext, build_chain, decide_escalation
from app.domain.permissions import Role
from app.domain.priority import Priority

MIN = timedelta(minutes=1)
TICK = timedelta(microseconds=1)
P1_RESPONSE = 5 * MIN


def ctx(
    elapsed: timedelta,
    *,
    priority: Priority = Priority.P1,
    acknowledged: bool = False,
    level: int = 0,
    resolution_breached: bool = False,
) -> EscalationContext:
    return EscalationContext(
        priority, acknowledged, P1_RESPONSE, elapsed, level, resolution_breached
    )


@pytest.mark.parametrize(
    ("elapsed", "role"),
    [
        (5 * MIN, None),
        (5 * MIN + TICK, Role.TEAM_LEAD),
        (10 * MIN, Role.TEAM_LEAD),
        (10 * MIN + TICK, Role.ADMINISTRATOR),
        (15 * MIN + TICK, Role.IT_MANAGER),
        (120 * MIN, Role.IT_MANAGER),
    ],
)
def test_BR08_unacknowledged_p1_escalates_one_level_per_missed_target(
    elapsed: timedelta, role: Role | None
) -> None:
    decision = decide_escalation(ctx(elapsed))
    assert (decision.target_role if decision else None) is role


def test_BR08_no_repeat_escalation_to_the_current_level() -> None:
    assert decide_escalation(ctx(7 * MIN, level=1)) is None
    decision = decide_escalation(ctx(11 * MIN, level=1))
    assert decision is not None
    assert decision.level == 2


def test_BR08_p2_escalates_but_p3_and_acknowledged_incidents_do_not() -> None:
    assert decide_escalation(ctx(6 * MIN, priority=Priority.P2)) is not None
    assert decide_escalation(ctx(600 * MIN, priority=Priority.P3)) is None
    assert decide_escalation(ctx(30 * MIN, acknowledged=True)) is None


def test_resolution_breach_goes_straight_to_the_team_lead() -> None:
    decision = decide_escalation(
        ctx(0 * MIN, priority=Priority.P3, acknowledged=True, resolution_breached=True)
    )
    assert decision is not None
    assert (decision.level, decision.target_role) == (1, Role.TEAM_LEAD)
    assert "resolution" in decision.reason
    assert (
        decide_escalation(ctx(0 * MIN, acknowledged=True, level=2, resolution_breached=True))
        is None
    )


def test_chain_runs_technician_to_it_manager() -> None:
    assert [handler.role for handler in build_chain()] == [
        Role.TECHNICIAN,
        Role.TEAM_LEAD,
        Role.ADMINISTRATOR,
        Role.IT_MANAGER,
    ]
