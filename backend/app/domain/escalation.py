"""Automatic escalation (blueprint §5.5, BR-08).

Pattern: Chain of Responsibility. Problem solved: escalation levels (Technician → Team Lead →
Administrator → IT Manager) must be changeable without touching the others; each handler owns
one level and passes requests it cannot satisfy to the next. The SLA monitor builds a context;
the chain decides who handles it.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from app.domain.permissions import Role, escalation_level
from app.domain.priority import Priority

ESCALATING_PRIORITIES = frozenset({Priority.P1, Priority.P2})  # BR-08
MAX_MISSED_TARGETS = 3
RESOLUTION_BREACH_LEVEL = 1  # §5.5: a resolution breach goes straight to the Team Lead


@dataclass(frozen=True, slots=True)
class EscalationContext:
    priority: Priority
    acknowledged: bool
    response_target: timedelta
    elapsed: timedelta  # since creation (the response SLA is not paused)
    current_level: int
    resolution_breached: bool = False


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    level: int
    target_role: Role
    reason: str


class EscalationHandler:
    """One level of the chain; handles a required level it covers, else defers to the next."""

    def __init__(self, role: Role, successor: "EscalationHandler | None" = None) -> None:
        self.__role = role
        self.__level = escalation_level(role) or 0
        self.__successor = successor

    @property
    def role(self) -> Role:
        return self.__role

    @property
    def successor(self) -> "EscalationHandler | None":
        return self.__successor

    def handle(self, required_level: int, reason: str) -> EscalationDecision:
        if required_level <= self.__level or self.__successor is None:
            return EscalationDecision(self.__level, self.__role, reason)
        return self.__successor.handle(required_level, reason)

    def __iter__(self) -> Iterator["EscalationHandler"]:
        handler: EscalationHandler | None = self
        while handler is not None:
            yield handler
            handler = handler.successor


def build_chain() -> EscalationHandler:
    """Technician → Team Lead → Administrator → IT Manager."""
    manager = EscalationHandler(Role.IT_MANAGER)
    admin = EscalationHandler(Role.ADMINISTRATOR, manager)
    lead = EscalationHandler(Role.TEAM_LEAD, admin)
    return EscalationHandler(Role.TECHNICIAN, lead)


_CHAIN = build_chain()


def _missed_targets(context: EscalationContext) -> int:
    missed = 0
    while missed < MAX_MISSED_TARGETS and context.elapsed > context.response_target * (missed + 1):
        missed += 1
    return missed


def decide_escalation(
    context: EscalationContext, chain: EscalationHandler = _CHAIN
) -> EscalationDecision | None:
    """Who should own the incident now, or None if no escalation is due."""
    required, reason = 0, ""
    if not context.acknowledged and context.priority in ESCALATING_PRIORITIES:
        missed = _missed_targets(context)
        required, reason = (
            missed,
            f"{context.priority} unacknowledged after {missed} missed response target(s)",
        )
    if context.resolution_breached and required < RESOLUTION_BREACH_LEVEL:
        required, reason = RESOLUTION_BREACH_LEVEL, "resolution SLA breached"
    if required <= context.current_level:
        return None
    return chain.handle(required, reason)
