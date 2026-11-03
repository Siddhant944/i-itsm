from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.errors import InvalidIncidentError, MissingSLAConfigurationError
from app.domain.incident import Incident, IncidentFactory
from app.domain.priority import Priority
from app.domain.sla import (
    SLAClock,
    SLAPolicyBook,
    SLAStatus,
    SLATarget,
    SLATier,
    ThresholdRiskEstimator,
    default_policies,
    tier_for_criticality,
)

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
GOLD_P1 = SLATarget(response=5 * MIN, resolution=30 * MIN)
TICK = timedelta(microseconds=1)


def test_default_policies_follow_the_blueprint_table() -> None:
    policies = default_policies()
    assert len(policies) == 12
    assert policies[(SLATier.GOLD, Priority.P1)] == GOLD_P1
    assert policies[(SLATier.GOLD, Priority.P4)] == SLATarget(
        timedelta(hours=4), timedelta(hours=24)
    )
    for priority in Priority:
        gold = policies[(SLATier.GOLD, priority)]
        assert policies[(SLATier.SILVER, priority)] == gold.scaled(2)
        assert policies[(SLATier.BRONZE, priority)] == gold.scaled(4)
    assert policies[(SLATier.BRONZE, Priority.P3)] == SLATarget(4 * 60 * MIN, 32 * 60 * MIN)


@pytest.mark.parametrize(
    ("criticality", "tier"), [(3, SLATier.GOLD), (2, SLATier.SILVER), (1, SLATier.BRONZE)]
)
def test_default_tier_follows_criticality(criticality: int, tier: SLATier) -> None:
    assert tier_for_criticality(criticality) is tier


def test_missing_policy_raises_or_falls_back_to_the_strictest_default() -> None:
    book = SLAPolicyBook({(SLATier.GOLD, Priority.P1): GOLD_P1})
    with pytest.raises(MissingSLAConfigurationError):
        book.target_for(SLATier.BRONZE, Priority.P2)
    target, used_default = book.target_or_default(SLATier.BRONZE, Priority.P2)
    assert used_default
    assert target == default_policies()[(SLATier.GOLD, Priority.P2)]
    assert book.target_or_default(SLATier.GOLD, Priority.P1) == (GOLD_P1, False)


def make_clock() -> SLAClock:
    return SLAClock(T0, GOLD_P1)


def test_BR07_breach_means_strictly_after_the_deadline() -> None:
    sla = make_clock()
    assert sla.response_deadline == T0 + 5 * MIN
    assert sla.response_status(T0 + 5 * MIN) is not SLAStatus.BREACHED
    assert sla.response_status(T0 + 5 * MIN + TICK) is SLAStatus.BREACHED
    assert sla.resolution_status(T0 + 30 * MIN) is not SLAStatus.BREACHED
    assert sla.resolution_status(T0 + 30 * MIN + TICK) is SLAStatus.BREACHED


def test_BR07_at_risk_from_exactly_75_percent() -> None:
    sla = make_clock()
    assert sla.resolution_status(T0 + timedelta(minutes=22, seconds=30)) is SLAStatus.AT_RISK
    assert (
        sla.resolution_status(T0 + timedelta(minutes=22, seconds=30) - TICK) is SLAStatus.ON_TRACK
    )
    assert sla.response_status(T0 + timedelta(minutes=3, seconds=45)) is SLAStatus.AT_RISK


def test_BR07_response_is_met_at_first_acknowledgement() -> None:
    on_time, late = make_clock(), make_clock()
    on_time.respond(T0 + 4 * MIN)
    on_time.respond(T0 + 9 * MIN)  # a later acknowledgement does not count
    late.respond(T0 + 6 * MIN)
    assert on_time.responded_at == T0 + 4 * MIN
    assert on_time.response_status(T0 + 60 * MIN) is SLAStatus.ON_TRACK
    assert late.response_status(T0 + 60 * MIN) is SLAStatus.BREACHED


def test_BR07_pause_excludes_on_hold_time_and_moves_the_deadline() -> None:
    sla = make_clock()
    sla.pause(T0 + 10 * MIN)
    assert sla.resolution_elapsed(T0 + 25 * MIN) == 10 * MIN  # frozen while paused
    assert sla.resolution_status(T0 + 50 * MIN) is SLAStatus.ON_TRACK
    sla.resume(T0 + 40 * MIN)
    assert sla.resolution_elapsed(T0 + 45 * MIN) == 15 * MIN
    assert sla.resolution_deadline(T0 + 45 * MIN) == T0 + 60 * MIN
    assert sla.resolution_status(T0 + 60 * MIN + TICK) is SLAStatus.BREACHED


def test_stop_freezes_the_clock_and_reopen_excludes_resolved_time() -> None:
    sla = make_clock()
    sla.stop(T0 + 20 * MIN)
    assert sla.resolution_status(T0 + 5 * 60 * MIN) is SLAStatus.ON_TRACK
    sla.restart(T0 + 2 * 60 * MIN)
    assert sla.resolution_elapsed(T0 + 2 * 60 * MIN + 5 * MIN) == 25 * MIN


def test_threshold_estimator_is_a_risk_estimator() -> None:
    estimator = ThresholdRiskEstimator()
    assert estimator.is_at_risk(elapsed=75 * MIN, target=100 * MIN)
    assert not estimator.is_at_risk(elapsed=74 * MIN, target=100 * MIN)


def scenario() -> tuple[Incident, FakeClock]:
    clock = FakeClock(T0)
    incident = IncidentFactory.create(
        sequence=1,
        clock=clock,
        reporter_id=1,
        title="Fee portal down",
        description="502",
        service_id=7,
        impact=3,
        urgency=3,
    )
    incident.classify(category_id=4, actor_id=None, clock=clock)
    incident.apply_sla(GOLD_P1)
    incident.assign(2, actor_id=None, clock=clock)
    return incident, clock


def test_BR07_incident_drives_its_sla_clock() -> None:
    incident, clock = scenario()
    sla = incident.sla_clock
    assert sla is not None
    assert sla.started_at == incident.created_at
    clock.advance(3 * MIN)
    incident.acknowledge(2, clock)
    incident.start(2, clock)
    assert sla.responded_at == T0 + 3 * MIN
    clock.advance(7 * MIN)
    incident.hold(2, clock, question="Which browser?")
    clock.advance(60 * MIN)
    incident.provide_info(1, clock, answer="Chrome")
    clock.advance(5 * MIN)
    assert sla.resolution_elapsed(clock.now()) == 15 * MIN
    incident.resolve(2, clock, summary="Restarted the gateway")
    clock.advance(60 * MIN)
    assert sla.resolution_status(clock.now()) is SLAStatus.ON_TRACK


def test_retargeting_keeps_the_start_and_pauses() -> None:
    incident, _clock = scenario()
    incident.apply_sla(GOLD_P1.scaled(2))
    assert incident.sla_clock is not None
    assert incident.sla_clock.response_deadline == T0 + 10 * MIN


def test_review_cancelled_incident_stops_counting_response_time() -> None:
    sla = make_clock()
    sla.stop(T0 + 2 * MIN)
    assert sla.response_status(T0 + 62 * MIN) is SLAStatus.ON_TRACK


def test_review_retarget_cannot_turn_a_met_target_into_a_breach() -> None:
    p4 = SLATarget(timedelta(hours=4), timedelta(hours=24))
    sla = SLAClock(T0, p4)
    sla.respond(T0 + 30 * MIN)
    sla.stop(T0 + 60 * MIN)
    sla.retarget(GOLD_P1)
    assert sla.response_status(T0 + 61 * MIN) is SLAStatus.ON_TRACK
    assert sla.resolution_status(T0 + 61 * MIN) is SLAStatus.ON_TRACK


def test_review_sla_clock_must_start_before_assignment() -> None:
    incident, clock = scenario()
    fresh = IncidentFactory.create(
        sequence=2,
        clock=clock,
        reporter_id=1,
        title="t",
        description="d",
        service_id=1,
        impact=1,
        urgency=1,
    )
    fresh.classify(category_id=1, actor_id=None, clock=clock)
    fresh.assign(2, actor_id=None, clock=clock)
    with pytest.raises(InvalidIncidentError):
        fresh.apply_sla(GOLD_P1)
    incident.apply_sla(GOLD_P1)  # retargeting an existing clock is always allowed
