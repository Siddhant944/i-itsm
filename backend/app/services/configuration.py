"""What an administrator configures as data (blueprint §3): the catalogue, the SLA policy
table and the assignment strategy.

Each change is validated by the domain object it touches, written, and audited in the same
transaction (§8: "Audit covers ... configuration changes"), then committed. Nothing here needs
a deploy to take effect — the next incident reported reads the new values.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.core.clock import Clock
from app.domain.assignment import AssignmentSettings, AssignmentStrategy, strategy_names
from app.domain.audit import AuditAction
from app.domain.catalogue import Category, ITService, dependency_cycle
from app.domain.errors import InvalidUserInputError
from app.domain.priority import Priority
from app.domain.repositories import SettingsRepository, UnitOfWork
from app.domain.sla import SLATarget, SLATier
from app.domain.users import User
from app.services.audit import AuditService

ASSIGNMENT_KEY = "assignment"


def assignment_settings(settings: SettingsRepository) -> AssignmentSettings:
    """The saved strategy and weights, or the §5.3 defaults when nothing has been saved."""
    return AssignmentSettings.from_mapping(settings.get(ASSIGNMENT_KEY))


def active_strategy(settings: SettingsRepository) -> AssignmentStrategy:
    """The strategy every new assignment uses, resolved through the registry (§5.3)."""
    return assignment_settings(settings).build()


@dataclass(frozen=True, slots=True)
class CategoryChange:
    """The editable fields of a category (§3)."""

    name: str
    required_skill_id: int | None = None
    keywords: tuple[str, ...] = ()
    minimum_priority: Priority | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class ServiceChange:
    """The editable fields of a service (§3). ``sla_tier`` None means "follow criticality"."""

    name: str
    criticality: int
    sla_tier: SLATier | None = None
    required_skill_id: int | None = None
    depends_on: tuple[int, ...] = ()
    active: bool = True


class ConfigurationService:
    """The admin's configuration screens, one method per thing that can be changed."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self.__uow = uow
        self.__audit = AuditService(uow.audit, clock)

    # ------------------------------------------------------------ categories
    def create_category(self, actor: User, change: CategoryChange) -> Category:
        existing = self.__uow.catalogue.categories()
        self.__unique_name(change.name, (c.name for c in existing))
        self.__known_skill(change.required_skill_id)
        category = Category(
            max((c.id for c in existing), default=0) + 1,
            change.name,
            required_skill_id=change.required_skill_id,
            keywords=change.keywords,
            minimum_priority=change.minimum_priority,
            active=change.active,
        )
        self.__uow.catalogue.save_category(category)
        self.__record(actor, "category.created", category.id, category.name)
        return category

    def update_category(self, actor: User, category_id: int, change: CategoryChange) -> Category:
        category = self.__uow.catalogue.get_category(category_id)
        others = (c.name for c in self.__uow.catalogue.categories() if c.id != category_id)
        self.__unique_name(change.name, others)
        self.__known_skill(change.required_skill_id)
        category.rename(change.name)
        category.set_required_skill(change.required_skill_id)
        category.set_keywords(change.keywords)
        category.set_minimum_priority(change.minimum_priority)
        if change.active:
            category.restore()
        else:
            category.retire()
        self.__uow.catalogue.save_category(category)
        self.__record(actor, "category.updated", category.id, category.name)
        return category

    # ------------------------------------------------------------ services
    def create_service(self, actor: User, change: ServiceChange) -> ITService:
        existing = self.__uow.catalogue.services()
        self.__unique_name(change.name, (s.name for s in existing))
        self.__known_skill(change.required_skill_id)
        service = ITService(
            max((s.id for s in existing), default=0) + 1,
            change.name,
            criticality=change.criticality,
            sla_tier=change.sla_tier,
            required_skill_id=change.required_skill_id,
            depends_on=self.__known_services(change.depends_on, existing),
            active=change.active,
        )
        self.__uow.catalogue.save_service(service)
        self.__record(actor, "service.created", service.id, service.name)
        return service

    def update_service(self, actor: User, service_id: int, change: ServiceChange) -> ITService:
        service = self.__uow.catalogue.get_service(service_id)
        existing = self.__uow.catalogue.services()
        self.__unique_name(change.name, (s.name for s in existing if s.id != service_id))
        self.__known_skill(change.required_skill_id)
        wanted = self.__known_services(change.depends_on, existing)

        service.rename(change.name)
        service.set_criticality(change.criticality)
        if change.sla_tier is None:
            service.clear_sla_tier_override()
        else:
            service.set_sla_tier(change.sla_tier)
        service.set_required_skill(change.required_skill_id)
        for dependency in service.depends_on:
            if dependency not in wanted:
                service.remove_dependency(dependency)
        for dependency in wanted:
            service.add_dependency(dependency)
        if dependency_cycle(existing, service):
            raise InvalidUserInputError(
                {"depends_on": "These dependencies would make a service depend on itself."}
            )
        if change.active:
            service.restore()
        else:
            service.retire()
        self.__uow.catalogue.save_service(service)
        self.__record(actor, "service.updated", service.id, service.name)
        return service

    # ------------------------------------------------------------ SLA policies
    def policies(self) -> Mapping[tuple[SLATier, Priority], SLATarget]:
        return self.__uow.catalogue.policy_book().policies

    def set_policy(
        self,
        actor: User,
        tier: SLATier,
        priority: Priority,
        *,
        response: timedelta,
        resolution: timedelta,
    ) -> SLATarget:
        """Change one cell of the §5.2 grid. Incidents already open keep the target they had."""
        target = SLATarget(response, resolution)
        table = dict(self.policies())
        table[(tier, priority)] = target
        self.__uow.catalogue.save_policies(table)
        self.__audit.record(
            AuditAction.CONFIGURATION_CHANGED,
            actor_id=actor.id,
            details={
                "change": "sla_policy.updated",
                "tier": tier.value,
                "priority": priority.value,
                "response_minutes": int(response.total_seconds() // 60),
                "resolution_minutes": int(resolution.total_seconds() // 60),
            },
        )
        self.__uow.commit()
        return target

    # ------------------------------------------------------------ assignment
    def assignment(self) -> AssignmentSettings:
        return assignment_settings(self.__uow.settings)

    @staticmethod
    def strategies() -> tuple[str, ...]:
        return strategy_names()

    def set_assignment(self, actor: User, settings: AssignmentSettings) -> AssignmentSettings:
        """Switch strategy at runtime (§5.3); the next assignment uses it."""
        self.__uow.settings.put(ASSIGNMENT_KEY, settings.to_mapping(), updated_by=actor.id)
        self.__audit.record(
            AuditAction.CONFIGURATION_CHANGED,
            actor_id=actor.id,
            details={"change": "assignment.updated", **settings.to_mapping()},
        )
        self.__uow.commit()
        return settings

    # ------------------------------------------------------------ internals
    def __record(self, actor: User, change: str, entity_id: int, name: str) -> None:
        self.__audit.record(
            AuditAction.CONFIGURATION_CHANGED,
            actor_id=actor.id,
            details={"change": change, "id": entity_id, "name": name},
        )
        self.__uow.commit()

    @staticmethod
    def __unique_name(name: str, taken: Iterable[str]) -> None:
        wanted = name.strip().lower()
        if any(wanted == other.strip().lower() for other in taken):
            raise InvalidUserInputError({"name": "This name is already in use."})

    def __known_skill(self, skill_id: int | None) -> None:
        if skill_id is not None and skill_id not in self.__uow.catalogue.skill_names():
            raise InvalidUserInputError({"required_skill_id": "Unknown skill."})

    @staticmethod
    def __known_services(wanted: Iterable[int], existing: Iterable[ITService]) -> tuple[int, ...]:
        known = {service.id for service in existing}
        chosen = tuple(dict.fromkeys(wanted))
        if any(service_id not in known for service_id in chosen):
            raise InvalidUserInputError({"depends_on": "Unknown service."})
        return chosen
