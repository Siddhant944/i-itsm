from collections import Counter
from datetime import UTC, datetime
from itertools import product

import pytest

from app.core.clock import FakeClock
from app.domain.errors import InvalidUserInputError
from app.domain.events import PriorityChanged
from app.domain.incident import IncidentFactory
from app.domain.priority import (
    MatrixPriorityStrategy,
    Priority,
    PriorityStrategy,
    WeightedProductPriorityStrategy,
)

WEIGHTED = WeightedProductPriorityStrategy()
COMBOS: list[tuple[int, int, int]] = [(i, u, c) for i, u, c in product((1, 2, 3), repeat=3)]


def expected(score: int) -> Priority:
    if score >= 18:
        return Priority.P1
    if score >= 9:
        return Priority.P2
    if score >= 4:
        return Priority.P3
    return Priority.P4


@pytest.mark.parametrize(("impact", "urgency", "criticality"), COMBOS)
def test_BR05_all_27_combinations(impact: int, urgency: int, criticality: int) -> None:
    result = WEIGHTED.assess(impact, urgency, criticality)
    assert result.score == impact * urgency * criticality
    assert result.priority is expected(result.score)


def test_BR05_combination_counts_match_the_blueprint_table() -> None:
    counts = Counter(WEIGHTED.assess(i, u, c).priority for i, u, c in COMBOS)
    assert counts == {Priority.P1: 4, Priority.P2: 6, Priority.P3: 10, Priority.P4: 7}


@pytest.mark.parametrize(
    ("combo", "priority"),
    [
        ((3, 3, 3), Priority.P1),
        ((3, 3, 2), Priority.P1),
        ((1, 3, 3), Priority.P2),
        ((2, 2, 2), Priority.P3),
        ((2, 2, 1), Priority.P3),
        ((3, 1, 1), Priority.P4),
    ],
)
def test_threshold_boundaries(combo: tuple[int, int, int], priority: Priority) -> None:
    assert WEIGHTED.assess(*combo).priority is priority


def test_a_criticality_1_service_never_computes_above_p2() -> None:
    worst = min(
        (WEIGHTED.assess(i, u, 1).priority for i, u in product((1, 2, 3), repeat=2)),
        key=lambda p: p.rank,
    )
    assert worst is Priority.P2


def test_payment_outage_scenario_is_p1_and_explained() -> None:
    result = WEIGHTED.assess(3, 3, 3)
    assert result.priority is Priority.P1
    assert "3 × 3 × 3 = 27" in result.explanation


def test_BR05_category_floor_raises_but_never_lowers_priority() -> None:
    raised = WEIGHTED.assess(1, 1, 1, floor=Priority.P2)
    assert (raised.priority, raised.floored) == (Priority.P2, True)
    kept = WEIGHTED.assess(3, 3, 3, floor=Priority.P2)
    assert (kept.priority, kept.floored) == (Priority.P1, False)


@pytest.mark.parametrize("combo", [(0, 1, 1), (1, 4, 1), (1, 1, 0)])
def test_factors_must_be_1_to_3(combo: tuple[int, int, int]) -> None:
    with pytest.raises(InvalidUserInputError):
        WEIGHTED.assess(*combo)


def test_strategies_are_interchangeable() -> None:
    strategies: list[PriorityStrategy] = [WEIGHTED, MatrixPriorityStrategy()]
    for strategy in strategies:
        assert strategy.assess(3, 3, 3).priority is Priority.P1
        assert strategy.assess(1, 1, 3).priority is Priority.P4


def test_matrix_strategy_ignores_criticality_and_can_be_edited() -> None:
    default = MatrixPriorityStrategy()
    assert default.assess(2, 3, 1).priority is default.assess(2, 3, 3).priority
    table = dict(MatrixPriorityStrategy.DEFAULT_TABLE) | {(1, 1): Priority.P3}
    assert MatrixPriorityStrategy(table).assess(1, 1, 1).priority is Priority.P3


def test_matrix_must_cover_all_nine_cells() -> None:
    with pytest.raises(InvalidUserInputError):
        MatrixPriorityStrategy({(1, 1): Priority.P4})


def test_priority_order_and_most_severe() -> None:
    assert Priority.P1.rank == 1
    assert Priority.most_severe(Priority.P3, Priority.P2) is Priority.P2


@pytest.fixture
def incident():  # type: ignore[no-untyped-def]
    clock = FakeClock(datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    item = IncidentFactory.create(
        sequence=1,
        clock=clock,
        reporter_id=1,
        title="Fee portal down",
        description="502",
        service_id=7,
        impact=3,
        urgency=3,
    )
    item.pull_events()
    return item, clock


def test_BR05_computed_priority_is_recorded(incident) -> None:  # type: ignore[no-untyped-def]
    item, clock = incident
    item.prioritise(WEIGHTED.assess(item.impact, item.urgency, 3), clock)
    assert (item.priority, item.priority_score) == (Priority.P1, 27)
    event = item.pull_events()[0]
    assert isinstance(event, PriorityChanged)
    assert event.new_priority is Priority.P1


@pytest.mark.parametrize("reason", ["", "   "])
def test_BR05_override_needs_a_reason(incident, reason: str) -> None:  # type: ignore[no-untyped-def]
    item, clock = incident
    item.prioritise(WEIGHTED.assess(3, 3, 3), clock)
    with pytest.raises(InvalidUserInputError):
        item.override_priority(Priority.P3, reason, actor_id=2, clock=clock)
    assert item.priority is Priority.P1


def test_BR05_override_is_recorded_with_its_reason(incident) -> None:  # type: ignore[no-untyped-def]
    item, clock = incident
    item.prioritise(WEIGHTED.assess(3, 3, 3), clock)
    item.pull_events()
    item.override_priority(Priority.P3, "Only the test portal is affected", actor_id=2, clock=clock)
    event = item.pull_events()[0]
    assert isinstance(event, PriorityChanged)
    assert (event.old_priority, event.new_priority) == (Priority.P1, Priority.P3)
    assert event.reason == "Only the test portal is affected"
    assert item.priority_overridden
