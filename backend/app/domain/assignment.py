"""Technician assignment (blueprint §5.3, BR-06).

Pattern: Template Method + Strategy. Problem solved: every strategy must apply the same
eligibility rules (available, active, spare capacity under the 10-point cap) before ranking;
``AssignmentStrategy.select`` does the filtering once and calls the abstract ``rank``, so a new
strategy is one class plus one registry entry and cannot forget the rules.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.domain.errors import (
    InvalidUserInputError,
    TechnicianUnavailableError,
    WorkloadExceededError,
)
from app.domain.priority import Priority
from app.domain.users import MAX_EXPERIENCE_LEVEL, Technician
from app.domain.value_objects import SkillSet

# §5.3: weighted workload, P1-P4 cost 4, 3, 2, 1 points; cap L_max = 10.
WORKLOAD_COST: Mapping[Priority, int] = MappingProxyType(
    {Priority.P1: 4, Priority.P2: 3, Priority.P3: 2, Priority.P4: 1}
)
MAX_LOAD = 10
# §5.3: SmartStrategy weights (skills, capacity, experience, history); admin-editable later.
DEFAULT_SMART_WEIGHTS = (0.4, 0.3, 0.15, 0.15)
_LEVEL_LABEL = MappingProxyType({1: "junior", 2: "mid-level", 3: "senior"})


@dataclass(frozen=True, slots=True)
class AssignmentRequest:
    priority: Priority
    required_skills: SkillSet  # S_r: category skill + service skill (D-002)
    service_id: int


@dataclass(frozen=True, slots=True)
class Candidate:
    technician: Technician
    load: int  # current weighted load L_t
    past_fixes: int  # n_{t,s}: resolved incidents on the request's service


@dataclass(frozen=True, slots=True)
class CandidateScore:
    technician_id: int
    score: float
    reasons: tuple[str, ...]


def check_capacity(load: int, priority: Priority) -> None:
    """Refuse a manual assignment that would exceed the cap (BR-06)."""
    if load + WORKLOAD_COST[priority] > MAX_LOAD:
        raise WorkloadExceededError


def _coverage(candidate: Candidate, request: AssignmentRequest) -> tuple[int, int]:
    return candidate.technician.skills.coverage(request.required_skills)


def _skill_ratio(candidate: Candidate, request: AssignmentRequest) -> float:
    matched, total = _coverage(candidate, request)
    return 1.0 if total == 0 else matched / total


def _free(candidate: Candidate) -> float:
    return 1 - candidate.load / MAX_LOAD


class AssignmentStrategy(ABC):
    """Interface and template: filter eligible technicians, then rank them."""

    name = "abstract"

    def select(
        self, request: AssignmentRequest, candidates: Iterable[Candidate]
    ) -> tuple[CandidateScore, ...]:
        """All eligible candidates, best first; raises when nobody qualifies (BR-06)."""
        cost = WORKLOAD_COST[request.priority]
        eligible = [
            c
            for c in candidates
            if c.technician.available and c.technician.active and c.load + cost <= MAX_LOAD
        ]
        if not eligible:
            raise TechnicianUnavailableError
        return tuple(self.rank(request, eligible))

    @abstractmethod
    def rank(
        self, request: AssignmentRequest, eligible: Sequence[Candidate]
    ) -> list[CandidateScore]:
        """Order eligible candidates, best first."""


class SkillBasedStrategy(AssignmentStrategy):
    """Most required skills first; ties go to the lower load."""

    name = "skill_based"

    def rank(
        self, request: AssignmentRequest, eligible: Sequence[Candidate]
    ) -> list[CandidateScore]:
        ordered = sorted(
            eligible, key=lambda c: (-_skill_ratio(c, request), c.load, c.technician.id)
        )
        return [
            CandidateScore(
                c.technician.id,
                _skill_ratio(c, request),
                ("{}/{} skills".format(*_coverage(c, request)), f"load {c.load}/{MAX_LOAD}"),
            )
            for c in ordered
        ]


class LoadBasedStrategy(AssignmentStrategy):
    """Lowest weighted load first."""

    name = "load_based"

    def rank(
        self, request: AssignmentRequest, eligible: Sequence[Candidate]
    ) -> list[CandidateScore]:
        ordered = sorted(eligible, key=lambda c: (c.load, c.technician.id))
        return [
            CandidateScore(c.technician.id, _free(c), (f"{round(_free(c) * 100)} % capacity free",))
            for c in ordered
        ]


class SmartStrategy(AssignmentStrategy):
    """score = 0.4·skills + 0.3·free capacity + 0.15·experience + 0.15·past fixes (default)."""

    name = "smart"

    def __init__(self, weights: tuple[float, float, float, float] = DEFAULT_SMART_WEIGHTS) -> None:
        if any(w < 0 for w in weights) or abs(sum(weights) - 1) > 1e-9:
            raise InvalidUserInputError({"weights": "Weights must be non-negative and sum to 1."})
        self.__weights = weights

    @property
    def weights(self) -> tuple[float, float, float, float]:
        return self.__weights

    def rank(
        self, request: AssignmentRequest, eligible: Sequence[Candidate]
    ) -> list[CandidateScore]:
        most_fixes = max(c.past_fixes for c in eligible)
        a1, a2, a3, a4 = self.__weights
        scored = []
        for c in eligible:
            history = c.past_fixes / most_fixes if most_fixes else 0.0
            level = c.technician.experience_level
            score = (
                a1 * _skill_ratio(c, request)
                + a2 * _free(c)
                + a3 * level / MAX_EXPERIENCE_LEVEL
                + a4 * history
            )
            reasons = (
                "{}/{} skills".format(*_coverage(c, request)),
                f"{round(_free(c) * 100)} % capacity free",
                _LEVEL_LABEL[level],
                f"{c.past_fixes} past fixes on this service",
            )
            scored.append(CandidateScore(c.technician.id, score, reasons))
        return sorted(scored, key=lambda s: (-s.score, s.technician_id))


_REGISTRY: Mapping[str, Callable[[], AssignmentStrategy]] = MappingProxyType(
    {
        SkillBasedStrategy.name: SkillBasedStrategy,
        LoadBasedStrategy.name: LoadBasedStrategy,
        SmartStrategy.name: SmartStrategy,
    }
)


def strategy_for(name: str) -> AssignmentStrategy:
    """Resolve the admin's saved choice (a new strategy is one class plus one entry here)."""
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise InvalidUserInputError({"strategy": f"Unknown strategy '{name}'."}) from None
