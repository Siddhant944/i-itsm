"""Priority engine (blueprint §5.1).

Pattern: Strategy (with a Template Method in ``assess``). Problem solved: the requirements let
teams choose their own prioritisation algorithm; swapping between the weighted product and an
admin-edited matrix must not touch the callers. ``assess`` validates inputs and applies the
category floor once, for every strategy; subclasses only implement ``_rank``.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from types import MappingProxyType

from app.domain.errors import InvalidUserInputError

FACTOR_VALUES = (1, 2, 3)  # impact, urgency and criticality answers (§5.1)
# §5.1 thresholds on S = I × U × C
P1_MIN_SCORE = 18
P2_MIN_SCORE = 9
P3_MIN_SCORE = 4


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

    @property
    def rank(self) -> int:
        """1 is the most severe."""
        return int(self.value[1])

    @property
    def label(self) -> str:
        return {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}[self.value]

    @staticmethod
    def most_severe(first: "Priority", second: "Priority") -> "Priority":
        return first if first.rank <= second.rank else second


@dataclass(frozen=True, slots=True)
class PriorityAssessment:
    """The outcome of a priority calculation, with a plain-language explanation."""

    priority: Priority
    score: int | None
    explanation: str
    floored: bool = False


class PriorityStrategy(ABC):
    """Interface for priority algorithms."""

    name: str = "abstract"

    def assess(
        self, impact: int, urgency: int, criticality: int, floor: Priority | None = None
    ) -> PriorityAssessment:
        """Validate the factors, rank them, then apply the category floor (BR-05)."""
        errors = {
            name: "Must be 1, 2 or 3."
            for name, value in (
                ("impact", impact),
                ("urgency", urgency),
                ("criticality", criticality),
            )
            if value not in FACTOR_VALUES
        }
        if errors:
            raise InvalidUserInputError(errors)
        priority, score, explanation = self._rank(impact, urgency, criticality)
        if floor is not None and floor.rank < priority.rank:
            return PriorityAssessment(
                floor, score, f"{explanation}; raised to the category minimum {floor}", True
            )
        return PriorityAssessment(priority, score, explanation)

    @abstractmethod
    def _rank(
        self, impact: int, urgency: int, criticality: int
    ) -> tuple[Priority, int | None, str]:
        """Return (priority, score or None, explanation)."""


class WeightedProductPriorityStrategy(PriorityStrategy):
    """S = I × U × C; P1 ≥ 18, P2 ≥ 9, P3 ≥ 4, otherwise P4 (the default strategy)."""

    name = "weighted_product"

    def _rank(
        self, impact: int, urgency: int, criticality: int
    ) -> tuple[Priority, int | None, str]:
        score = impact * urgency * criticality
        if score >= P1_MIN_SCORE:
            priority = Priority.P1
        elif score >= P2_MIN_SCORE:
            priority = Priority.P2
        elif score >= P3_MIN_SCORE:
            priority = Priority.P3
        else:
            priority = Priority.P4
        return priority, score, f"{impact} × {urgency} × {criticality} = {score} → {priority}"


class MatrixPriorityStrategy(PriorityStrategy):
    """An impact × urgency table the admin can edit (criticality is not used)."""

    name = "matrix"
    DEFAULT_TABLE: Mapping[tuple[int, int], Priority] = MappingProxyType(
        {
            (3, 3): Priority.P1,
            (3, 2): Priority.P2,
            (2, 3): Priority.P2,
            (3, 1): Priority.P3,
            (2, 2): Priority.P3,
            (1, 3): Priority.P3,
            (2, 1): Priority.P4,
            (1, 2): Priority.P4,
            (1, 1): Priority.P4,
        }
    )

    def __init__(self, table: Mapping[tuple[int, int], Priority] | None = None) -> None:
        cells = dict(table if table is not None else self.DEFAULT_TABLE)
        if set(cells) != set(product(FACTOR_VALUES, repeat=2)):
            raise InvalidUserInputError({"matrix": "Every impact × urgency cell needs a priority."})
        self.__table: Mapping[tuple[int, int], Priority] = MappingProxyType(cells)

    @property
    def table(self) -> Mapping[tuple[int, int], Priority]:
        return self.__table

    def _rank(
        self, impact: int, urgency: int, criticality: int
    ) -> tuple[Priority, int | None, str]:
        priority = self.__table[(impact, urgency)]
        return priority, None, f"Impact {impact}, urgency {urgency} → {priority} (matrix)"
