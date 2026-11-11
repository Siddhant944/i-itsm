"""The user hierarchy (blueprint §3): User (abstract) → Employee, Technician, Administrator;
TeamLead extends Technician; ITManager extends Administrator.

Inheritance is used only for these is-a relationships. What a user may do comes from the
role → permission map (``app.domain.permissions``), never from isinstance checks. Attributes are
name-mangled behind read-only properties and change only through intention-revealing methods.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from types import MappingProxyType

from app.domain.errors import InvalidUserInputError
from app.domain.permissions import Permission, Role, escalation_level, permissions_for
from app.domain.value_objects import EmailAddress, SkillSet

MIN_EXPERIENCE_LEVEL = 1  # blueprint §5.3: experience level 1-3 (x_t = level / 3)
MAX_EXPERIENCE_LEVEL = 3


class User(ABC):
    """Anyone who signs in. Abstract: every user has a concrete role."""

    def __init__(
        self, user_id: int, email: EmailAddress, full_name: str, *, active: bool = True
    ) -> None:
        if not full_name.strip():
            raise InvalidUserInputError({"full_name": "Enter a name."})
        self.__id = user_id
        self.__email = email
        self.__full_name = full_name.strip()
        self.__active = active

    @property
    @abstractmethod
    def role(self) -> Role:
        """The role that decides this user's permissions."""

    @property
    def id(self) -> int:
        return self.__id

    @property
    def email(self) -> EmailAddress:
        return self.__email

    @property
    def full_name(self) -> str:
        return self.__full_name

    @property
    def active(self) -> bool:
        return self.__active

    @property
    def escalation_level(self) -> int | None:
        """Level in the escalation chain (blueprint §5.5); None for employees."""
        return escalation_level(self.role)

    def can(self, permission: Permission) -> bool:
        """True when the user is active and the role grants ``permission``."""
        return self.__active and permission in permissions_for(self.role)

    def deactivate(self) -> None:
        """Block sign-in and every action; history is kept (users are never deleted)."""
        self.__active = False

    def activate(self) -> None:
        self.__active = True

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.__id}, email={self.__email})"


class Employee(User):
    """Reports incidents and follows their own."""

    @property
    def role(self) -> Role:
        return Role.EMPLOYEE


class Technician(User):
    """Resolves incidents; has skills, an experience level, availability and a team."""

    def __init__(
        self,
        user_id: int,
        email: EmailAddress,
        full_name: str,
        *,
        active: bool = True,
        skills: SkillSet | None = None,
        experience_level: int = MIN_EXPERIENCE_LEVEL,
        available: bool = True,
        team_id: int | None = None,
    ) -> None:
        super().__init__(user_id, email, full_name, active=active)
        self.__skills = skills or SkillSet()
        self.__experience_level = _checked_level(experience_level)
        self.__available = available
        self.__team_id = team_id

    @property
    def role(self) -> Role:
        return Role.TECHNICIAN

    @property
    def skills(self) -> SkillSet:
        return self.__skills

    @property
    def experience_level(self) -> int:
        return self.__experience_level

    @property
    def available(self) -> bool:
        """Unavailable technicians are never auto-assigned (BR-06)."""
        return self.__available

    @property
    def team_id(self) -> int | None:
        return self.__team_id

    def mark_available(self) -> None:
        self.__available = True

    def mark_unavailable(self) -> None:
        self.__available = False

    def update_skills(self, skills: SkillSet) -> None:
        self.__skills = skills

    def set_experience_level(self, level: int) -> None:
        self.__experience_level = _checked_level(level)

    def join_team(self, team_id: int | None) -> None:
        self.__team_id = team_id


class TeamLead(Technician):
    """A technician who also owns the team queue and takes level-1 escalations."""

    @property
    def role(self) -> Role:
        return Role.TEAM_LEAD


class Administrator(User):
    """Configures the system and monitors all incidents; escalation level 2."""

    @property
    def role(self) -> Role:
        return Role.ADMINISTRATOR


class ITManager(Administrator):
    """The final escalation level (3)."""

    @property
    def role(self) -> Role:
        return Role.IT_MANAGER


def _checked_level(level: int) -> int:
    if not MIN_EXPERIENCE_LEVEL <= level <= MAX_EXPERIENCE_LEVEL:
        raise InvalidUserInputError(
            {"experience_level": f"Must be {MIN_EXPERIENCE_LEVEL}-{MAX_EXPERIENCE_LEVEL}."}
        )
    return level


class UserFactory:
    """Pattern: Factory. Problem solved: callers (registration, seed data, the persistence
    layer rebuilding users from rows) need the right subclass for a role, with validated fields,
    without knowing the class hierarchy. A new role is one class plus one registry entry.
    """

    _BASIC: Mapping[Role, Callable[..., User]] = MappingProxyType(
        {Role.EMPLOYEE: Employee, Role.ADMINISTRATOR: Administrator, Role.IT_MANAGER: ITManager}
    )
    _SUPPORT: Mapping[Role, Callable[..., Technician]] = MappingProxyType(
        {Role.TECHNICIAN: Technician, Role.TEAM_LEAD: TeamLead}
    )

    @classmethod
    def is_support_role(cls, role: Role) -> bool:
        """True when the role has technician fields (skills, experience, availability, team)."""
        return role in cls._SUPPORT

    @classmethod
    def create(
        cls,
        role: Role,
        *,
        user_id: int,
        email: str,
        full_name: str,
        active: bool = True,
        skills: SkillSet | None = None,
        experience_level: int | None = None,
        available: bool | None = None,
        team_id: int | None = None,
    ) -> User:
        """Build a user of ``role``; technician fields are only accepted for support roles."""
        address = EmailAddress(email)
        if role in cls._SUPPORT:
            return cls._SUPPORT[role](
                user_id,
                address,
                full_name,
                active=active,
                skills=skills,
                experience_level=MIN_EXPERIENCE_LEVEL
                if experience_level is None
                else experience_level,
                available=True if available is None else available,
                team_id=team_id,
            )
        given = {
            "skills": skills,
            "experience_level": experience_level,
            "available": available,
            "team_id": team_id,
        }
        extra = {
            name: "Only technicians and team leads have this."
            for name, v in given.items()
            if v is not None
        }
        if extra:
            raise InvalidUserInputError(extra)
        return cls._BASIC[role](user_id, address, full_name, active=active)
