"""The admin's configuration as data (blueprint §3, §5.2, §5.3) and its audit trail (§8)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.assignment import (
    DEFAULT_SMART_WEIGHTS,
    AssignmentSettings,
    LoadBasedStrategy,
    SmartStrategy,
    strategy_for,
    strategy_names,
)
from app.domain.audit import AuditAction
from app.domain.catalogue import Category, ITService, Skill, dependency_cycle
from app.domain.errors import InvalidUserInputError, NotFoundError
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.sla import GOLD_TARGETS, SLATarget, SLATier, default_policies
from app.domain.users import User, UserFactory
from app.repositories.memory import InMemoryUnitOfWork
from app.services.configuration import (
    CategoryChange,
    ConfigurationService,
    ServiceChange,
    active_strategy,
)

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_category(Category(1, "Network", required_skill_id=1, keywords=("wifi",)))
    unit.catalogue.save_service(ITService(1, "Database", criticality=3))
    unit.catalogue.save_service(ITService(2, "Fee Portal", criticality=3, depends_on=(1,)))
    unit.catalogue.save_policies(default_policies())
    return unit


@pytest.fixture
def admin() -> User:
    return UserFactory.create(
        Role.ADMINISTRATOR, user_id=9, email="admin@campus.edu", full_name="Admin"
    )


@pytest.fixture
def service(uow: InMemoryUnitOfWork) -> ConfigurationService:
    return ConfigurationService(uow, FakeClock(NOW))


def last_audit(uow: InMemoryUnitOfWork) -> dict[str, object]:
    record = uow.audit.records()[-1]
    assert record.action is AuditAction.CONFIGURATION_CHANGED
    assert record.actor_id == 9
    return dict(record.details)


# ---------------------------------------------------------------- categories
def test_a_new_category_gets_the_next_id_and_is_audited(
    service: ConfigurationService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    created = service.create_category(
        admin, CategoryChange("Printing", keywords=("Printer", " toner "))
    )
    assert created.id == 2
    assert created.keywords == ("printer", "toner")
    assert uow.catalogue.get_category(2).name == "Printing"
    assert last_audit(uow) == {"change": "category.created", "id": 2, "name": "Printing"}
    assert uow.committed == 1


def test_a_category_name_must_be_unique_ignoring_case(
    service: ConfigurationService, admin: User
) -> None:
    with pytest.raises(InvalidUserInputError) as refused:
        service.create_category(admin, CategoryChange(" network "))
    assert "name" in refused.value.field_errors


def test_editing_a_category_replaces_its_fields_and_can_retire_it(
    service: ConfigurationService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    service.update_category(
        admin,
        1,
        CategoryChange("Network", keywords=("lan",), minimum_priority=Priority.P2, active=False),
    )
    stored = uow.catalogue.get_category(1)
    assert stored.keywords == ("lan",)
    assert stored.required_skill_id is None
    assert stored.minimum_priority is Priority.P2
    assert stored.active is False
    assert uow.catalogue.categories(active_only=True) == ()


def test_an_unknown_skill_or_category_is_refused(
    service: ConfigurationService, admin: User
) -> None:
    with pytest.raises(InvalidUserInputError):
        service.create_category(admin, CategoryChange("Printing", required_skill_id=99))
    with pytest.raises(NotFoundError):
        service.update_category(admin, 99, CategoryChange("Nothing"))


# ---------------------------------------------------------------- services
def test_a_new_service_follows_its_criticality_unless_the_tier_is_pinned(
    service: ConfigurationService, admin: User
) -> None:
    followed = service.create_service(admin, ServiceChange("LMS", criticality=2, depends_on=(1,)))
    pinned = service.create_service(
        admin, ServiceChange("Printers", criticality=1, sla_tier=SLATier.GOLD)
    )
    assert (followed.id, followed.sla_tier, followed.tier_overridden) == (3, SLATier.SILVER, False)
    assert followed.depends_on == (1,)
    assert (pinned.sla_tier, pinned.tier_overridden) == (SLATier.GOLD, True)


def test_editing_a_service_replaces_its_dependencies(
    service: ConfigurationService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    service.create_service(admin, ServiceChange("Auth", criticality=3))
    service.update_service(admin, 2, ServiceChange("Fee Portal", criticality=2, depends_on=(3,)))
    stored = uow.catalogue.get_service(2)
    assert stored.depends_on == (3,)
    assert stored.sla_tier is SLATier.SILVER
    assert last_audit(uow)["change"] == "service.updated"


def test_a_dependency_cycle_is_refused(service: ConfigurationService, admin: User) -> None:
    with pytest.raises(InvalidUserInputError) as refused:
        service.update_service(admin, 1, ServiceChange("Database", criticality=3, depends_on=(2,)))
    assert "depends_on" in refused.value.field_errors


def test_a_dependency_on_an_unknown_service_or_on_itself_is_refused(
    service: ConfigurationService, admin: User
) -> None:
    with pytest.raises(InvalidUserInputError):
        service.create_service(admin, ServiceChange("LMS", criticality=2, depends_on=(42,)))
    with pytest.raises(InvalidUserInputError):
        service.update_service(admin, 1, ServiceChange("Database", criticality=3, depends_on=(1,)))


def test_dependency_cycle_follows_transitive_edges() -> None:
    a = ITService(1, "A", criticality=1, depends_on=(2,))
    b = ITService(2, "B", criticality=1, depends_on=(3,))
    c = ITService(3, "C", criticality=1)
    assert dependency_cycle([a, b, c], c) is False
    closing = ITService(3, "C", criticality=1, depends_on=(1,))
    assert dependency_cycle([a, b, c], closing) is True


# ---------------------------------------------------------------- SLA policies
def test_one_cell_of_the_sla_grid_changes_and_the_rest_stay(
    service: ConfigurationService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    service.set_policy(
        admin,
        SLATier.GOLD,
        Priority.P1,
        response=timedelta(minutes=3),
        resolution=timedelta(minutes=20),
    )
    book = uow.catalogue.policy_book()
    assert book.target_for(SLATier.GOLD, Priority.P1) == SLATarget(
        timedelta(minutes=3), timedelta(minutes=20)
    )
    assert book.target_for(SLATier.GOLD, Priority.P2) == GOLD_TARGETS[Priority.P2]
    assert len(service.policies()) == 12
    assert last_audit(uow) == {
        "change": "sla_policy.updated",
        "tier": "gold",
        "priority": "P1",
        "response_minutes": 3,
        "resolution_minutes": 20,
    }


@pytest.mark.parametrize(("response", "resolution"), [(0, 30), (30, 0), (60, 30)])
def test_an_impossible_sla_target_is_refused(
    service: ConfigurationService, admin: User, response: int, resolution: int
) -> None:
    with pytest.raises(InvalidUserInputError):
        service.set_policy(
            admin,
            SLATier.GOLD,
            Priority.P1,
            response=timedelta(minutes=response),
            resolution=timedelta(minutes=resolution),
        )


# ---------------------------------------------------------------- assignment
def test_the_default_assignment_is_the_smart_strategy_with_the_blueprint_weights(
    service: ConfigurationService, uow: InMemoryUnitOfWork
) -> None:
    assert service.assignment() == AssignmentSettings("smart", DEFAULT_SMART_WEIGHTS)
    assert isinstance(active_strategy(uow.settings), SmartStrategy)
    assert service.strategies() == strategy_names() == ("load_based", "skill_based", "smart")


def test_switching_strategy_takes_effect_for_the_next_assignment_and_is_audited(
    service: ConfigurationService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    service.set_assignment(admin, AssignmentSettings("load_based"))
    assert isinstance(active_strategy(uow.settings), LoadBasedStrategy)
    assert last_audit(uow)["change"] == "assignment.updated"

    service.set_assignment(admin, AssignmentSettings("smart", (0.1, 0.7, 0.1, 0.1)))
    chosen = active_strategy(uow.settings)
    assert isinstance(chosen, SmartStrategy)
    assert chosen.weights == (0.1, 0.7, 0.1, 0.1)


def test_settings_refuse_an_unknown_strategy_and_weights_that_do_not_sum_to_one() -> None:
    with pytest.raises(InvalidUserInputError):
        AssignmentSettings("random")
    with pytest.raises(InvalidUserInputError):
        AssignmentSettings("smart", (0.5, 0.5, 0.5, 0.5))
    with pytest.raises(InvalidUserInputError):
        AssignmentSettings("smart", (1.2, -0.2, 0.0, 0.0))


def test_stored_nonsense_falls_back_to_the_defaults() -> None:
    assert AssignmentSettings.from_mapping(None) == AssignmentSettings()
    assert AssignmentSettings.from_mapping({"strategy": "gone"}) == AssignmentSettings()
    assert (
        AssignmentSettings.from_mapping({"strategy": "load_based", "weights": "x"}).strategy
        == "load_based"
    )
    assert (
        AssignmentSettings.from_mapping({"strategy": "smart", "weights": [9, 9, 9, 9]})
        == AssignmentSettings()
    )


def test_weights_are_ignored_by_the_strategies_that_have_none() -> None:
    assert isinstance(strategy_for("load_based", (0.25, 0.25, 0.25, 0.25)), LoadBasedStrategy)
