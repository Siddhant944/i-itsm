import pytest

from app.domain.assignment import (
    MAX_LOAD,
    AssignmentRequest,
    Candidate,
    LoadBasedStrategy,
    SkillBasedStrategy,
    SmartStrategy,
    check_capacity,
    strategy_for,
)
from app.domain.errors import (
    InvalidUserInputError,
    TechnicianUnavailableError,
    WorkloadExceededError,
)
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.users import Technician, UserFactory
from app.domain.value_objects import SkillSet

REQUEST = AssignmentRequest(Priority.P1, SkillSet({"app-support", "payments"}), service_id=7)


def tech(user_id: int, skills: set[str], level: int = 1, available: bool = True) -> Technician:
    user = UserFactory.create(
        Role.TECHNICIAN,
        user_id=user_id,
        email=f"t{user_id}@campus.edu",
        full_name=f"T{user_id}",
        skills=SkillSet(skills),
        experience_level=level,
        available=available,
    )
    assert isinstance(user, Technician)
    return user


SENIOR = Candidate(tech(1, {"app-support", "payments"}, level=3), load=4, past_fixes=5)
JUNIOR = Candidate(tech(2, {"app-support"}, level=1), load=0, past_fixes=0)


def test_BR06_capacity_cap_is_inclusive_at_10_points() -> None:
    at_cap = Candidate(tech(3, {"payments"}), load=6, past_fixes=0)  # 6 + 4 (P1) = 10
    over = Candidate(tech(4, {"payments"}), load=7, past_fixes=0)  # 7 + 4 = 11
    ranked = LoadBasedStrategy().select(REQUEST, [at_cap, over])
    assert [c.technician_id for c in ranked] == [3]
    assert MAX_LOAD == 10


def test_BR06_unavailable_or_inactive_technicians_are_never_auto_assigned() -> None:
    away = Candidate(tech(5, {"payments"}, available=False), load=0, past_fixes=0)
    gone = Candidate(tech(6, {"payments"}), load=0, past_fixes=0)
    gone.technician.deactivate()
    with pytest.raises(TechnicianUnavailableError):
        SmartStrategy().select(REQUEST, [away, gone])


def test_BR06_manual_assignment_over_capacity_is_refused() -> None:
    check_capacity(load=6, priority=Priority.P1)
    with pytest.raises(WorkloadExceededError):
        check_capacity(load=7, priority=Priority.P1)


def test_smart_scores_match_the_blueprint_formula() -> None:
    ranked = SmartStrategy().select(REQUEST, [JUNIOR, SENIOR])
    assert [c.technician_id for c in ranked] == [1, 2]
    assert ranked[0].score == pytest.approx(0.4 * 1 + 0.3 * 0.6 + 0.15 * 1 + 0.15 * 1)
    assert ranked[1].score == pytest.approx(0.4 * 0.5 + 0.3 * 1 + 0.15 / 3 + 0)
    assert ranked[0].reasons == (
        "2/2 skills",
        "60 % capacity free",
        "senior",
        "5 past fixes on this service",
    )


def test_skill_strategy_prefers_coverage_and_load_strategy_prefers_free_capacity() -> None:
    assert SkillBasedStrategy().select(REQUEST, [JUNIOR, SENIOR])[0].technician_id == 1
    assert LoadBasedStrategy().select(REQUEST, [SENIOR, JUNIOR])[0].technician_id == 2


def test_skill_strategy_breaks_ties_on_lower_load() -> None:
    busy = Candidate(tech(7, {"app-support", "payments"}), load=5, past_fixes=0)
    ranked = SkillBasedStrategy().select(REQUEST, [busy, SENIOR])
    assert [c.technician_id for c in ranked] == [1, 7]


def test_strategies_switch_at_runtime_through_the_registry() -> None:
    assert isinstance(strategy_for("smart"), SmartStrategy)
    assert isinstance(strategy_for("load_based"), LoadBasedStrategy)
    assert isinstance(strategy_for("skill_based"), SkillBasedStrategy)
    with pytest.raises(InvalidUserInputError):
        strategy_for("round_robin")


def test_smart_weights_must_sum_to_one() -> None:
    with pytest.raises(InvalidUserInputError):
        SmartStrategy(weights=(0.5, 0.5, 0.5, 0.5))
