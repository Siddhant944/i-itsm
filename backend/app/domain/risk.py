"""Predictive SLA risk from how long similar incidents took (blueprint §6.3).

A fixed 75 % rule flags every ticket at the same point, whether incidents like it usually
finish in a tenth of the target or usually overrun. This estimator asks the history instead:
of the past incidents in the same category and priority that were still open after as long as
this one has been, what share went on to breach?

    P̂(breach) = P̂(T > R | T > e) = |{k : T_k > R}| / |{k : T_k > e}|

T_k are past resolution times excluding paused time, R the resolution target and e the time
this incident has been worked so far. With fewer than ten comparable incidents the evidence is
too thin and the 75 % rule answers instead.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from app.domain.sla import AT_RISK_FRACTION, RiskEstimator, ThresholdRiskEstimator

#: §6.3: AT_RISK once the estimated probability of a breach reaches this.
RISK_THRESHOLD = 0.5
#: §6.3: below this many past incidents still open at e, the 75 % rule applies.
MIN_SAMPLES = 10


class RiskMethod(StrEnum):
    HISTORY = "history"
    THRESHOLD = "threshold"


@dataclass(frozen=True, slots=True)
class RiskEstimate:
    """The answer, with how it was reached and a sentence a technician can check."""

    at_risk: bool
    method: RiskMethod
    reason: str
    #: The estimated probability of a breach; None when the 75 % rule answered.
    probability: float | None = None
    #: How many past incidents were still open at this point (the denominator).
    samples: int = 0


def shown_duration(span: timedelta) -> str:
    """ "1 h 20 m", "45 m", "2 d 3 h": the plain words §6.3 asks for."""
    minutes = max(int(span.total_seconds() // 60), 0)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {minutes} m" if minutes else f"{hours} h"
    return f"{minutes} m"


class HistoricalRiskEstimator(RiskEstimator):
    """§6.3's estimator over the resolution times of comparable past incidents.

    Pattern: Strategy (an interchangeable ``RiskEstimator``). Problem solved: flag tickets on
    evidence rather than at a fixed share of the target, while still answering — with the
    §5.2 rule — when there is not enough history to go on.
    """

    def __init__(
        self,
        durations: Sequence[timedelta],
        *,
        label: str = "similar",
        fallback: ThresholdRiskEstimator | None = None,
    ) -> None:
        self.__durations = tuple(sorted(durations))
        self.__label = label
        self.__fallback = fallback or ThresholdRiskEstimator()

    def is_at_risk(self, elapsed: timedelta, target: timedelta) -> bool:
        return self.estimate(elapsed, target).at_risk

    def estimate(self, elapsed: timedelta, target: timedelta) -> RiskEstimate:
        """The estimate for an incident worked for ``elapsed`` against ``target``.

        Past the target the incident has breached, which is not a forecast: the caller's SLA
        status says so, and this answers at_risk with probability 1.
        """
        if elapsed > target:
            return RiskEstimate(True, RiskMethod.HISTORY, "The resolution target has passed.", 1.0)
        survivors = [duration for duration in self.__durations if duration > elapsed]
        if len(survivors) < MIN_SAMPLES:
            at_risk = self.__fallback.is_at_risk(elapsed, target)
            share = round(elapsed / target * 100) if target > timedelta(0) else 100
            return RiskEstimate(
                at_risk,
                RiskMethod.THRESHOLD,
                f"{share} % of the resolution target used; too few past {self.__label} "
                f"incidents ({len(survivors)}) to predict from, so the "
                f"{round(AT_RISK_FRACTION * 100)} % rule applies.",
                samples=len(survivors),
            )
        breached = sum(1 for duration in survivors if duration > target)
        probability = breached / len(survivors)
        return RiskEstimate(
            probability >= RISK_THRESHOLD,
            RiskMethod.HISTORY,
            f"{round(probability * 100)} % of past {self.__label} incidents still open at "
            f"{shown_duration(elapsed)} went on to breach ({breached} of {len(survivors)}).",
            probability,
            len(survivors),
        )
