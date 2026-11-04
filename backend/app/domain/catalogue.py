"""The configurable catalogue (blueprint §3): skills, categories, IT services and teams.

Admins edit all of this in the UI with no code change, so each entity validates its own rules
and exposes read-only views: a category's keywords and a service's dependencies are tuples,
and a change goes through an intention-revealing method such as ``service.set_sla_tier``.

A `Team` ◇ `Technician` aggregation is held as member ids: a team groups technicians but does
not own them, so deleting a team never deletes its people.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.domain.errors import InvalidUserInputError
from app.domain.priority import Priority
from app.domain.sla import SLATier, tier_for_criticality
from app.domain.value_objects import SkillSet

MIN_CRITICALITY, MAX_CRITICALITY = 1, 3  # blueprint §3: a service's criticality is 1-3


def _name(value: str, field: str = "name") -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidUserInputError({field: "Must not be empty."})
    return cleaned


def _checked_criticality(value: int) -> int:
    if not MIN_CRITICALITY <= value <= MAX_CRITICALITY:
        raise InvalidUserInputError(
            {"criticality": f"Must be {MIN_CRITICALITY}-{MAX_CRITICALITY}."}
        )
    return value


@dataclass(frozen=True, slots=True)
class Skill:
    """A named capability, e.g. ``networking``. Compared by value and stored lower-cased."""

    id: int
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name).lower())


class Category:
    """An incident category: its required skill, classifier keywords and optional floor."""

    def __init__(
        self,
        category_id: int,
        name: str,
        *,
        required_skill_id: int | None = None,
        keywords: Iterable[str] = (),
        minimum_priority: Priority | None = None,
        active: bool = True,
    ) -> None:
        self.__id = category_id
        self.__name = _name(name)
        self.__required_skill_id = required_skill_id
        self.__keywords = _normalised_keywords(keywords)
        self.__minimum_priority = minimum_priority
        self.__active = active

    @property
    def id(self) -> int:
        return self.__id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def required_skill_id(self) -> int | None:
        return self.__required_skill_id

    @property
    def keywords(self) -> tuple[str, ...]:
        """Sorted, lower-cased keywords used by the rule-based classifier."""
        return self.__keywords

    @property
    def minimum_priority(self) -> Priority | None:
        """The category floor applied by the priority strategies (BR-05)."""
        return self.__minimum_priority

    @property
    def active(self) -> bool:
        return self.__active

    def rename(self, name: str) -> None:
        self.__name = _name(name)

    def set_required_skill(self, skill_id: int | None) -> None:
        self.__required_skill_id = skill_id

    def set_keywords(self, keywords: Iterable[str]) -> None:
        self.__keywords = _normalised_keywords(keywords)

    def set_minimum_priority(self, priority: Priority | None) -> None:
        self.__minimum_priority = priority

    def retire(self) -> None:
        """Hide the category from new reports; existing incidents keep it."""
        self.__active = False

    def restore(self) -> None:
        self.__active = True

    def __repr__(self) -> str:
        return f"Category(id={self.__id}, name={self.__name!r})"


class ITService:
    """A campus IT service, its criticality, SLA tier and the services it depends on."""

    def __init__(
        self,
        service_id: int,
        name: str,
        *,
        criticality: int,
        sla_tier: SLATier | None = None,
        required_skill_id: int | None = None,
        depends_on: Iterable[int] = (),
        active: bool = True,
    ) -> None:
        self.__id = service_id
        self.__name = _name(name)
        self.__criticality = _checked_criticality(criticality)
        self.__tier_overridden = sla_tier is not None
        self.__sla_tier = sla_tier or tier_for_criticality(self.__criticality)
        self.__required_skill_id = required_skill_id
        self.__depends_on: list[int] = []
        self.__active = active
        for dependency in depends_on:
            self.add_dependency(dependency)

    @property
    def id(self) -> int:
        return self.__id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def criticality(self) -> int:
        """1-3; feeds the priority score as C (blueprint §5.1)."""
        return self.__criticality

    @property
    def sla_tier(self) -> SLATier:
        return self.__sla_tier

    @property
    def tier_overridden(self) -> bool:
        """True when an admin pinned the tier, so criticality changes leave it alone."""
        return self.__tier_overridden

    @property
    def required_skill_id(self) -> int | None:
        """The service's own skill, unioned with the category's (D-002)."""
        return self.__required_skill_id

    @property
    def depends_on(self) -> tuple[int, ...]:
        """Ids of the services this one needs, in the order they were added."""
        return tuple(self.__depends_on)

    @property
    def active(self) -> bool:
        return self.__active

    def rename(self, name: str) -> None:
        self.__name = _name(name)

    def set_criticality(self, criticality: int) -> None:
        """Change C; the tier follows unless an admin pinned it."""
        self.__criticality = _checked_criticality(criticality)
        if not self.__tier_overridden:
            self.__sla_tier = tier_for_criticality(self.__criticality)

    def set_sla_tier(self, tier: SLATier) -> None:
        self.__sla_tier = tier
        self.__tier_overridden = True

    def clear_sla_tier_override(self) -> None:
        self.__tier_overridden = False
        self.__sla_tier = tier_for_criticality(self.__criticality)

    def set_required_skill(self, skill_id: int | None) -> None:
        self.__required_skill_id = skill_id

    def add_dependency(self, service_id: int) -> None:
        """Record that this service needs ``service_id`` (used for correlation, §6.2)."""
        if service_id == self.__id:
            raise InvalidUserInputError({"depends_on": "A service cannot depend on itself."})
        if service_id not in self.__depends_on:
            self.__depends_on.append(service_id)

    def remove_dependency(self, service_id: int) -> None:
        if service_id in self.__depends_on:
            self.__depends_on.remove(service_id)

    def retire(self) -> None:
        self.__active = False

    def restore(self) -> None:
        self.__active = True

    def __repr__(self) -> str:
        return f"ITService(id={self.__id}, name={self.__name!r})"


class Team:
    """A support team: its lead and its technicians (aggregation, blueprint §3)."""

    def __init__(self, team_id: int, name: str, *, lead_id: int | None = None) -> None:
        self.__id = team_id
        self.__name = _name(name)
        self.__lead_id = lead_id
        self.__member_ids: list[int] = []

    @property
    def id(self) -> int:
        return self.__id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def lead_id(self) -> int | None:
        """The TeamLead who owns the queue and takes level-1 escalations (D-004)."""
        return self.__lead_id

    @property
    def member_ids(self) -> tuple[int, ...]:
        return tuple(self.__member_ids)

    def rename(self, name: str) -> None:
        self.__name = _name(name)

    def add_member(self, user_id: int) -> None:
        if user_id not in self.__member_ids:
            self.__member_ids.append(user_id)

    def remove_member(self, user_id: int) -> None:
        if user_id in self.__member_ids:
            self.__member_ids.remove(user_id)

    def set_lead(self, user_id: int | None) -> None:
        """The lead must be one of the team's technicians once members are known."""
        if user_id is not None and self.__member_ids and user_id not in self.__member_ids:
            raise InvalidUserInputError({"lead_id": "The lead must be a member of the team."})
        self.__lead_id = user_id

    def __repr__(self) -> str:
        return f"Team(id={self.__id}, name={self.__name!r})"


def _normalised_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
    cleaned = {word.strip().lower() for word in keywords}
    return tuple(sorted(cleaned - {""}))


def required_skills_for(
    category: Category | None, service: ITService | None, skill_names: Mapping[int, str]
) -> SkillSet:
    """S_r for assignment: the category's skill plus the service's optional skill (D-002)."""
    ids = [
        skill_id
        for skill_id in (
            category.required_skill_id if category else None,
            service.required_skill_id if service else None,
        )
        if skill_id is not None
    ]
    return SkillSet(skill_names[skill_id] for skill_id in ids if skill_id in skill_names)
