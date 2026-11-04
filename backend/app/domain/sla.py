"""SLA policies and the per-incident SLA clock (blueprint §5.2, BR-07).

Targets come from the service's tier and the incident's priority. The response SLA is met at the
first acknowledgement; the resolution clock pauses while ON_HOLD, stops at RESOLVED, and on
reopen excludes the time spent resolved. A breach means now > deadline. AT_RISK comes from a
RiskEstimator: the 75 % threshold here, the historical estimator in P4.5.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from app.domain.errors import InvalidIncidentError, MissingSLAConfigurationError
from app.domain.priority import Priority


class SLATier(StrEnum):
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


class SLAStatus(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"


@dataclass(frozen=True, slots=True)
class SLATarget:
    response: timedelta
    resolution: timedelta

    def scaled(self, factor: int) -> "SLATarget":
        return SLATarget(self.response * factor, self.resolution * factor)


_H = timedelta(hours=1)
_M = timedelta(minutes=1)
# §5.2: Gold is the requirements' table; Silver ×2 and Bronze ×4.
GOLD_TARGETS: Mapping[Priority, SLATarget] = MappingProxyType(
    {
        Priority.P1: SLATarget(5 * _M, 30 * _M),
        Priority.P2: SLATarget(15 * _M, 2 * _H),
        Priority.P3: SLATarget(1 * _H, 8 * _H),
        Priority.P4: SLATarget(4 * _H, 24 * _H),
    }
)
TIER_MULTIPLIER: Mapping[SLATier, int] = MappingProxyType(
    {SLATier.GOLD: 1, SLATier.SILVER: 2, SLATier.BRONZE: 4}
)
_TIER_BY_CRITICALITY: Mapping[int, SLATier] = MappingProxyType(
    {3: SLATier.GOLD, 2: SLATier.SILVER, 1: SLATier.BRONZE}
)
AT_RISK_FRACTION = 0.75  # §5.2 fallback: AT_RISK from 75 % of the target elapsed (inclusive)


def default_policies() -> dict[tuple[SLATier, Priority], SLATarget]:
    """The seeded policy table: one target per tier and priority (12 rows)."""
    return {
        (tier, priority): GOLD_TARGETS[priority].scaled(TIER_MULTIPLIER[tier])
        for tier in SLATier
        for priority in Priority
    }


def tier_for_criticality(criticality: int) -> SLATier:
    """A service's default tier (3 Gold, 2 Silver, 1 Bronze); admins may override it."""
    return _TIER_BY_CRITICALITY[criticality]


class SLAPolicyBook:
    """The configured targets, looked up by tier and priority."""

    def __init__(self, policies: Mapping[tuple[SLATier, Priority], SLATarget]) -> None:
        self.__policies = MappingProxyType(dict(policies))

    def target_for(self, tier: SLATier, priority: Priority) -> SLATarget:
        try:
            return self.__policies[(tier, priority)]
        except KeyError:
            msg = f"No SLA policy for {tier.value} {priority.value}."
            raise MissingSLAConfigurationError(msg) from None

    def target_or_default(self, tier: SLATier, priority: Priority) -> tuple[SLATarget, bool]:
        """The policy, or the strictest (Gold) target with ``True`` so the admin is alerted."""
        try:
            return self.target_for(tier, priority), False
        except MissingSLAConfigurationError:
            return GOLD_TARGETS[priority], True


class RiskEstimator(ABC):
    """Interface: is an incident at risk of breaching, given elapsed time and its target?"""

    @abstractmethod
    def is_at_risk(self, elapsed: timedelta, target: timedelta) -> bool: ...


class ThresholdRiskEstimator(RiskEstimator):
    """AT_RISK once the elapsed share of the target reaches the threshold (inclusive)."""

    def __init__(self, fraction: float = AT_RISK_FRACTION) -> None:
        self.__fraction = fraction

    @property
    def fraction(self) -> float:
        return self.__fraction

    def is_at_risk(self, elapsed: timedelta, target: timedelta) -> bool:
        return elapsed >= target * self.__fraction


_THRESHOLD = ThresholdRiskEstimator()


def _status(elapsed: timedelta, target: timedelta, estimator: RiskEstimator) -> SLAStatus:
    if elapsed > target:
        return SLAStatus.BREACHED
    if estimator.is_at_risk(elapsed, target):
        return SLAStatus.AT_RISK
    return SLAStatus.ON_TRACK


class SLAClock:
    """Response and resolution timing for one incident (composed by Incident)."""

    def __init__(self, started_at: datetime, target: SLATarget) -> None:
        self.__started_at = started_at
        self.__target = target
        self.__responded_at: datetime | None = None
        self.__paused_total = timedelta()  # completed pauses and resolved spells, accumulated
        self.__paused_since: datetime | None = None
        self.__stopped_at: datetime | None = None
        self.__response_met: bool | None = None  # decided at the first acknowledgement
        self.__resolution_target_at_stop: timedelta | None = None

    @classmethod
    def restore(
        cls,
        *,
        started_at: datetime,
        target: SLATarget,
        responded_at: datetime | None,
        paused_total: timedelta,
        paused_since: datetime | None,
        stopped_at: datetime | None,
        response_met: bool | None,
        resolution_target_at_stop: timedelta | None,
    ) -> "SLAClock":
        """Rebuild a clock from stored columns (used by the persistence mappers).

        Only the accumulated paused time is kept, because that is all the measurements use.
        """
        clock = cls(started_at, target)
        clock.__responded_at = responded_at
        clock.__paused_total = paused_total
        clock.__paused_since = paused_since
        clock.__stopped_at = stopped_at
        clock.__response_met = response_met
        clock.__resolution_target_at_stop = resolution_target_at_stop
        return clock

    @property
    def started_at(self) -> datetime:
        return self.__started_at

    @property
    def target(self) -> SLATarget:
        return self.__target

    @property
    def responded_at(self) -> datetime | None:
        return self.__responded_at

    @property
    def paused_accumulated(self) -> timedelta:
        """Paused time already banked, excluding a pause still in progress (for storage)."""
        return self.__paused_total

    @property
    def paused_since(self) -> datetime | None:
        return self.__paused_since

    @property
    def stopped_at(self) -> datetime | None:
        return self.__stopped_at

    @property
    def response_met(self) -> bool | None:
        """Frozen at the first acknowledgement; None until then (D-017)."""
        return self.__response_met

    @property
    def resolution_target_at_stop(self) -> timedelta | None:
        """The resolution target frozen at RESOLVED, so a later retarget cannot rewrite it."""
        return self.__resolution_target_at_stop

    @property
    def is_paused(self) -> bool:
        return self.__paused_since is not None

    @property
    def is_stopped(self) -> bool:
        return self.__stopped_at is not None

    @property
    def response_deadline(self) -> datetime:
        return self.__started_at + self.__target.response

    @property
    def resolution_deadline_at_rest(self) -> datetime:
        """The resolution deadline, ignoring a pause that is still running.

        Persistence stores this so a search can compare it with "now" directly instead of
        doing datetime arithmetic in SQL. A paused incident is excluded from breach searches,
        which is why the current pause does not need to be counted here.
        """
        return self.__started_at + self.__target.resolution + self.__paused_total

    def risk_at(self, estimator: RiskEstimator | None = None) -> datetime:
        """When this incident becomes AT_RISK, on the same "at rest" basis (§5.2)."""
        fraction = AT_RISK_FRACTION
        if isinstance(estimator, ThresholdRiskEstimator):
            fraction = estimator.fraction
        target = self.__resolution_target_at_stop or self.__target.resolution
        return self.__started_at + target * fraction + self.__paused_total

    # ------------------------------------------------------------ changes
    def retarget(self, target: SLATarget) -> None:
        """New targets (e.g. after a priority change); start time and pauses are kept."""
        self.__target = target

    def respond(self, at: datetime) -> None:
        """Record the first acknowledgement; later ones do not count (BR-07)."""
        if self.__responded_at is None:
            self.__responded_at = at
            self.__response_met = at <= self.response_deadline

    def pause(self, at: datetime) -> None:
        if self.is_paused or self.is_stopped:
            msg = "The SLA clock is not running."
            raise InvalidIncidentError(msg)
        self.__paused_since = at

    def resume(self, at: datetime) -> None:
        if self.__paused_since is None:
            msg = "The SLA clock is not paused."
            raise InvalidIncidentError(msg)
        self.__paused_total += max(at - self.__paused_since, timedelta())
        self.__paused_since = None

    def stop(self, at: datetime) -> None:
        """Stop at RESOLVED (or cancellation); a pause in progress ends here."""
        if self.is_stopped:
            return
        if self.is_paused:
            self.resume(at)
        self.__stopped_at = at
        self.__resolution_target_at_stop = self.__target.resolution

    def restart(self, at: datetime) -> None:
        """Reopen: the time spent stopped does not count."""
        if self.__stopped_at is None:
            msg = "The SLA clock is not stopped."
            raise InvalidIncidentError(msg)
        self.__paused_total += max(at - self.__stopped_at, timedelta())
        self.__stopped_at = None
        self.__resolution_target_at_stop = None

    # ------------------------------------------------------------ measurements
    def _effective(self, now: datetime) -> datetime:
        return self.__stopped_at if self.__stopped_at is not None else now

    def paused_total(self, now: datetime) -> timedelta:
        moment = self._effective(now)
        total = self.__paused_total
        if self.__paused_since is not None:
            total += max(moment - self.__paused_since, timedelta())
        return total

    def resolution_elapsed(self, now: datetime) -> timedelta:
        """Working time so far, excluding pauses and time spent resolved."""
        moment = self._effective(now)
        return moment - self.__started_at - self.paused_total(moment)

    def resolution_deadline(self, now: datetime) -> datetime:
        return self.__started_at + self.__target.resolution + self.paused_total(now)

    def response_status(self, now: datetime, estimator: RiskEstimator = _THRESHOLD) -> SLAStatus:
        """Decided once at the first acknowledgement; a later retarget cannot change it."""
        if self.__response_met is not None:
            return SLAStatus.ON_TRACK if self.__response_met else SLAStatus.BREACHED
        elapsed = self._effective(now) - self.__started_at
        return _status(elapsed, self.__target.response, estimator)

    def resolution_status(self, now: datetime, estimator: RiskEstimator = _THRESHOLD) -> SLAStatus:
        target = self.__resolution_target_at_stop or self.__target.resolution
        return _status(self.resolution_elapsed(now), target, estimator)
