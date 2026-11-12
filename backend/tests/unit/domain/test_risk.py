"""Predictive SLA risk (blueprint §6.3)."""

from datetime import timedelta

import pytest

from app.domain.risk import (
    MIN_SAMPLES,
    HistoricalRiskEstimator,
    RiskMethod,
    shown_duration,
)

H = timedelta(hours=1)
M = timedelta(minutes=1)
TARGET = 8 * H


def history(*hours: float) -> list[timedelta]:
    return [timedelta(hours=h) for h in hours]


#: Twenty past P2 Network incidents: most finish in a couple of hours; six overran 8 h.
PAST = history(1, 1, 1.5, 1.5, 2, 2, 2, 2.5, 3, 3, 3.5, 4, 5, 6, 9, 10, 10, 12, 14, 20)


def test_the_estimate_is_the_blueprints_conditional_share() -> None:
    estimator = HistoricalRiskEstimator(PAST, label="P2 Network")
    early = estimator.estimate(0 * H, TARGET)
    assert early.probability == pytest.approx(6 / 20)
    assert early.samples == 20
    assert not early.at_risk
    later = estimator.estimate(2 * H + 30 * M, TARGET)
    # Still open after 2 h 30 m: 12 of the 20 were, and 6 of those 12 breached.
    assert later.probability == pytest.approx(6 / 12)
    assert later.at_risk  # exactly 0.5 is at risk (§6.3: "reaches")
    assert later.method is RiskMethod.HISTORY
    assert later.reason == (
        "50 % of past P2 Network incidents still open at 2 h 30 m went on to breach (6 of 12)."
    )


def test_the_estimate_rises_as_the_ticket_ages() -> None:
    estimator = HistoricalRiskEstimator(PAST * 3)  # enough survivors all the way along
    estimates = [estimator.estimate(e * H, TARGET).probability for e in (0, 1, 2, 3, 4, 5)]
    assert all(p is not None for p in estimates)
    assert estimates == sorted(estimates)  # type: ignore[type-var]
    assert estimates[0] < estimates[-1]  # type: ignore[operator]


def test_below_ten_comparable_incidents_the_75_percent_rule_answers() -> None:
    estimator = HistoricalRiskEstimator(history(*([10] * (MIN_SAMPLES - 1))), label="P1 Email")
    early = estimator.estimate(5 * H, TARGET)
    assert early.method is RiskMethod.THRESHOLD
    assert early.probability is None
    assert not early.at_risk
    assert early.reason.startswith("62 % of the resolution target used; too few past P1 Email")
    assert estimator.estimate(6 * H, TARGET).at_risk  # 75 % exactly


def test_the_threshold_counts_only_incidents_still_open_at_e() -> None:
    # Fifteen samples overall, but only five of them lasted beyond 3 h.
    estimator = HistoricalRiskEstimator(history(*([1] * 10), *([9] * 5)))
    assert estimator.estimate(30 * M, TARGET).method is RiskMethod.HISTORY
    assert estimator.estimate(3 * H, TARGET).method is RiskMethod.THRESHOLD


def test_no_history_at_all_still_answers() -> None:
    assert HistoricalRiskEstimator([]).estimate(7 * H, TARGET).at_risk
    assert HistoricalRiskEstimator([]).is_at_risk(H, TARGET) is False


def test_past_the_target_is_a_certainty_not_a_forecast() -> None:
    passed = HistoricalRiskEstimator(PAST).estimate(TARGET + M, TARGET)
    assert (passed.at_risk, passed.probability) == (True, 1.0)


@pytest.mark.parametrize(
    ("span", "words"),
    [(45 * M, "45 m"), (H, "1 h"), (H + 20 * M, "1 h 20 m"), (51 * H, "2 d 3 h"), (48 * H, "2 d")],
)
def test_durations_read_in_plain_words(span: timedelta, words: str) -> None:
    assert shown_duration(span) == words
