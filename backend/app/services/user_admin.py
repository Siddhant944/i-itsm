"""Managing accounts (blueprint §3, §8): the admin's users and technicians screen.

Self-registration only ever creates Employees (D-008); every other role is given here, by
someone whose role carries ``users:manage``. Each change is audited in the same transaction.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.core.clock import Clock
from app.core.security import PasswordHasher, password_problem
from app.domain.audit import AuditAction
from app.domain.errors import InvalidUserInputError, UnauthorizedOperationError
from app.domain.permissions import Permission, Role
from app.domain.repositories import UnitOfWork
from app.domain.users import Technician, User, UserFactory
from app.domain.value_objects import EmailAddress, SkillSet
from app.services.audit import AuditService


@dataclass(frozen=True, slots=True)
class TechnicianFields:
    """What only technicians and team leads have (§3)."""

    skills: tuple[str, ...] = ()
    experience_level: int = 1
    available: bool = True
    team_id: int | None = None


class UserAdminService:
    """Create accounts, give roles, switch accounts off, and keep technician profiles."""

    def __init__(self, uow: UnitOfWork, clock: Clock, hasher: PasswordHasher) -> None:
        self.__uow = uow
        self.__hasher = hasher
        self.__audit = AuditService(uow.audit, clock)

    def everyone(self) -> tuple[User, ...]:
        return self.__uow.users.all()

    def get(self, user_id: int) -> User:
        return self.__uow.users.get(user_id)

    def directory(self, viewer: User) -> tuple[User, ...]:
        """The names a screen needs to show beside ids.

        Support staff see everyone. An employee sees the support staff — the people who may be
        working on their incident — and themselves, never the other employees (BR-01).
        """
        if viewer.can(Permission.INCIDENT_VIEW_ASSIGNED):
            return self.__uow.users.all()
        return tuple(
            user
            for user in self.__uow.users.all()
            if user.id == viewer.id or user.can(Permission.INCIDENT_VIEW_ASSIGNED)
        )

    def create(
        self,
        actor: User,
        *,
        email: str,
        full_name: str,
        password: str,
        role: Role,
        technician: TechnicianFields | None = None,
    ) -> User:
        address = EmailAddress(email)
        problem = password_problem(password)
        if problem is not None:
            raise InvalidUserInputError({"password": problem})
        if self.__uow.users.find_by_email(address) is not None:
            raise InvalidUserInputError({"email": "An account with this email already exists."})

        user = self.__build(
            role,
            user_id=self.__uow.users.next_id(),
            email=str(address),
            full_name=full_name,
            active=True,
            technician=technician,
        )
        self.__uow.users.add(user)
        credentials = self.__uow.credentials.get(user.id)
        credentials.set_password_hash(self.__hasher.hash(password))
        self.__uow.credentials.save(credentials)
        self.__record(actor, user, "created")
        return user

    def set_active(self, actor: User, user_id: int, *, active: bool) -> User:
        user = self.__uow.users.get(user_id)
        if not active:
            self.__not_self(actor, user, "deactivate your own account")
            user.deactivate()
        else:
            user.activate()
        self.__uow.users.save(user)
        self.__record(actor, user, "activated" if active else "deactivated")
        return user

    def change_role(self, actor: User, user_id: int, role: Role) -> User:
        """Give ``user_id`` another role, keeping the technician profile where both have one."""
        user = self.__uow.users.get(user_id)
        if user.role is role:
            return user
        self.__not_self(actor, user, "change your own role")
        leaving_support = isinstance(user, Technician) and not UserFactory.is_support_role(role)
        if leaving_support:
            self.__nothing_assigned(user)
        if isinstance(user, Technician) and role is not Role.TEAM_LEAD:
            self.__leads_no_team(user)
        carried = (
            TechnicianFields(
                skills=user.skills.names,
                experience_level=user.experience_level,
                available=user.available,
                team_id=user.team_id,
            )
            if isinstance(user, Technician)
            else None
        )
        changed = self.__build(
            role,
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            active=user.active,
            technician=carried,
        )
        self.__uow.users.save(changed)
        self.__record(actor, changed, "role_changed", previous=user.role.value)
        return changed

    def update_technician(self, actor: User, user_id: int, fields: TechnicianFields) -> Technician:
        user = self.__uow.users.get(user_id)
        if not isinstance(user, Technician):
            raise InvalidUserInputError({"user_id": "Only technicians and team leads have this."})
        self.__known_team(fields.team_id)
        if fields.team_id != user.team_id:
            self.__leads_no_team(user)
        user.update_skills(SkillSet(self.__known_skills(fields.skills)))
        user.set_experience_level(fields.experience_level)
        if fields.available:
            user.mark_available()
        else:
            user.mark_unavailable()
        user.join_team(fields.team_id)
        self.__uow.users.save(user)
        self.__record(actor, user, "technician_updated")
        return user

    # ------------------------------------------------------------ internals
    def __build(
        self,
        role: Role,
        *,
        user_id: int,
        email: str,
        full_name: str,
        active: bool,
        technician: TechnicianFields | None,
    ) -> User:
        if not UserFactory.is_support_role(role):
            return UserFactory.create(
                role, user_id=user_id, email=email, full_name=full_name, active=active
            )
        fields = technician or TechnicianFields()
        self.__known_team(fields.team_id)
        return UserFactory.create(
            role,
            user_id=user_id,
            email=email,
            full_name=full_name,
            active=active,
            skills=SkillSet(self.__known_skills(fields.skills)),
            experience_level=fields.experience_level,
            available=fields.available,
            team_id=fields.team_id,
        )

    def __known_skills(self, names: Iterable[str]) -> tuple[str, ...]:
        known = set(self.__uow.catalogue.skill_names().values())
        chosen = tuple(dict.fromkeys(name.strip().lower() for name in names if name.strip()))
        unknown = [name for name in chosen if name not in known]
        if unknown:
            raise InvalidUserInputError({"skills": f"Unknown skill: {', '.join(unknown)}."})
        return chosen

    def __known_team(self, team_id: int | None) -> None:
        if team_id is not None and team_id not in {t.id for t in self.__uow.catalogue.teams()}:
            raise InvalidUserInputError({"team_id": "Unknown team."})

    def __nothing_assigned(self, user: User) -> None:
        if self.__uow.incidents.workloads().get(user.id, 0) > 0:
            raise InvalidUserInputError(
                {"role": "Reassign this person's open incidents before changing the role."}
            )

    def __leads_no_team(self, user: User) -> None:
        if any(team.lead_id == user.id for team in self.__uow.catalogue.teams()):
            raise InvalidUserInputError(
                {"role": "This person leads a team; a team lead cannot be moved or demoted."}
            )

    @staticmethod
    def __not_self(actor: User, user: User, what: str) -> None:
        if actor.id == user.id:
            raise UnauthorizedOperationError(f"You cannot {what}.")

    def __record(self, actor: User, user: User, change: str, **extra: str) -> None:
        self.__audit.record(
            AuditAction.USER_MANAGED,
            actor_id=actor.id,
            details={"change": change, "user_id": user.id, "role": user.role.value, **extra},
        )
        self.__uow.commit()
