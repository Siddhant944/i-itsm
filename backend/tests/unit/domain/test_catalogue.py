"""The configurable catalogue (blueprint §3 "Configurable as data", D-002)."""

import pytest

from app.domain.catalogue import Category, ITService, Skill, Team, required_skills_for
from app.domain.errors import InvalidUserInputError
from app.domain.priority import Priority
from app.domain.sla import SLATier
from app.domain.value_objects import SkillSet


def tier(service: ITService) -> str:
    """Read the tier through a call, so the type checker does not narrow it to one literal."""
    return service.sla_tier.value


def test_a_skill_name_is_normalised_and_compared_by_value() -> None:
    assert Skill(1, "  Networking ").name == "networking"
    assert Skill(1, "networking") == Skill(1, "networking")
    with pytest.raises(InvalidUserInputError):
        Skill(1, "   ")


def test_a_category_keeps_keywords_as_a_read_only_tuple() -> None:
    category = Category(1, "Network", required_skill_id=2, keywords=("wifi", " WiFi ", "signal"))
    assert category.keywords == ("signal", "wifi")
    assert category.minimum_priority is None
    assert isinstance(category.keywords, tuple)


def test_a_category_floor_is_editable_by_an_admin() -> None:
    category = Category(1, "Network", required_skill_id=None)
    category.set_minimum_priority(Priority.P2)
    assert category.minimum_priority is Priority.P2
    category.set_minimum_priority(None)
    assert category.minimum_priority is None


def test_a_category_can_be_renamed_and_retired_but_never_blank() -> None:
    category = Category(1, "Network", required_skill_id=None)
    category.rename("Networking")
    assert category.name == "Networking"
    category.retire()
    assert category.active is False
    with pytest.raises(InvalidUserInputError):
        category.rename("  ")


def test_a_service_tier_defaults_to_its_criticality_and_can_be_overridden() -> None:
    service = ITService(1, "Fee Payment Portal", criticality=3)
    assert tier(service) == SLATier.GOLD.value
    assert service.tier_overridden is False
    service.set_sla_tier(SLATier.BRONZE)
    assert tier(service) == SLATier.BRONZE.value
    assert service.tier_overridden is True


def test_a_service_rejects_a_criticality_outside_one_to_three() -> None:
    with pytest.raises(InvalidUserInputError):
        ITService(1, "Portal", criticality=4)
    service = ITService(1, "Portal", criticality=1)
    with pytest.raises(InvalidUserInputError):
        service.set_criticality(0)


def test_changing_criticality_keeps_an_overridden_tier() -> None:
    service = ITService(1, "Portal", criticality=1)
    assert tier(service) == SLATier.BRONZE.value
    service.set_criticality(3)
    assert tier(service) == SLATier.GOLD.value
    service.set_sla_tier(SLATier.SILVER)
    service.set_criticality(1)
    assert tier(service) == SLATier.SILVER.value


def test_a_service_depends_on_other_services_without_duplicates_or_cycles() -> None:
    service = ITService(1, "Fee Payment Portal", criticality=3)
    service.add_dependency(2)
    service.add_dependency(2)
    assert isinstance(service.depends_on, tuple)
    assert list(service.depends_on) == [2]
    service.add_dependency(3)
    assert list(service.depends_on) == [2, 3]
    service.remove_dependency(2)
    assert list(service.depends_on) == [3]
    with pytest.raises(InvalidUserInputError):
        service.add_dependency(1)


def test_required_skills_combine_the_category_and_the_service_d002() -> None:
    skills = {1: "networking", 2: "database"}
    category = Category(1, "Network", required_skill_id=1)
    service = ITService(1, "Portal", criticality=3, required_skill_id=2)
    assert required_skills_for(category, service, skills) == SkillSet({"networking", "database"})
    assert required_skills_for(None, service, skills) == SkillSet({"database"})
    assert required_skills_for(category, None, skills) == SkillSet({"networking"})
    assert required_skills_for(None, None, skills) == SkillSet()


def test_required_skills_ignore_an_unknown_skill_id() -> None:
    category = Category(1, "Network", required_skill_id=99)
    assert required_skills_for(category, None, {1: "networking"}) == SkillSet()


def test_a_team_aggregates_technicians_and_names_its_lead() -> None:
    team = Team(1, "Network Operations", lead_id=7)
    team.add_member(7)
    team.add_member(8)
    team.add_member(8)
    assert list(team.member_ids) == [7, 8]
    team.remove_member(7)
    assert list(team.member_ids) == [8]
    assert team.lead_id == 7
    team.set_lead(8)
    assert team.lead_id == 8


def test_a_team_lead_must_be_a_member_when_one_is_known() -> None:
    team = Team(1, "Network Operations", lead_id=None)
    team.add_member(8)
    with pytest.raises(InvalidUserInputError):
        team.set_lead(9)


def test_the_escalation_fallback_prefers_the_service_desk() -> None:
    """D-004: the Service Desk's lead, else any team's lead."""
    from app.domain.catalogue import FALLBACK_TEAM_NAME, fallback_lead

    network = Team.restore(1, "Network Operations", lead_id=10, member_ids=(10,))
    desk = Team.restore(2, FALLBACK_TEAM_NAME, lead_id=20, member_ids=(20,))
    leaderless = Team.restore(3, "Security Operations", lead_id=None, member_ids=())

    assert fallback_lead([network, desk, leaderless]) == 20
    assert fallback_lead([desk, network]) == 20
    assert fallback_lead([network, leaderless]) == 10  # no Service Desk, so any lead
    assert fallback_lead([leaderless]) is None
    assert fallback_lead([]) is None


def test_the_fallback_skips_whoever_already_holds_the_incident() -> None:
    """Handing an incident back to its current owner would leave it where it was."""
    from app.domain.catalogue import FALLBACK_TEAM_NAME, fallback_lead

    desk = Team.restore(1, FALLBACK_TEAM_NAME, lead_id=20, member_ids=(20,))
    network = Team.restore(2, "Network Operations", lead_id=10, member_ids=(10,))

    assert fallback_lead([desk, network], excluding=20) == 10
    assert fallback_lead([desk], excluding=20) is None
    assert fallback_lead([desk, network], excluding=99) == 20
