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
from app.domain.permissions import Permission, Role, escalation_level, permissions_for
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
    """Create accounts, give roles, switch accounts off, and keep technician profiles.

    The rules that stop a click from orphaning work (D-025): nobody edits their own role or
    switches themselves off, nobody manages a role above their own, a person holding open
    incidents keeps a role that can work them and stays active, and a team keeps its lead.
    """

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
        self.__may_manage(actor, role)
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

    def update(
        self,
        actor: User,
        user_id: int,
        *,
        role: Role | None = None,
        active: bool | None = None,
        technician: TechnicianFields | None = None,
    ) -> User:
        """Change an account's role, whether it is active, and its technician profile.

        Everything asked for is checked and applied before the one commit, so an edit that
        fails half-way leaves nothing behind (blueprint §8: the change and its audit record
        commit together).
        """
        user = self.__uow.users.get(user_id)
        self.__may_manage(actor, user.role)
        changes: list[tuple[str, dict[str, str]]] = []

        if role is not None and role is not user.role:
            previous = user.role
            user = self.__with_role(actor, user, role)
            changes.append(("role_changed", {"previous": previous.value}))
        if technician is not None:
            self.__apply_profile(user, technician)
            changes.append(("technician_updated", {}))
        if active is not None and active is not user.active:
            if active:
                user.activate()
            else:
                self.__not_self(actor, user, "deactivate your own account")
                self.__holds_nothing(user, "deactivating the account")
                self.__leads_no_team(user)
                user.deactivate()
            changes.append(("activated" if active else "deactivated", {}))

        if not changes:
            return user
        self.__uow.users.save(user)
        for change, extra in changes:
            self.__audit.record(
                AuditAction.USER_MANAGED,
                actor_id=actor.id,
                details={"change": change, "user_id": user.id, "role": user.role.value, **extra},
            )
        self.__uow.commit()
        return user

    def set_active(self, actor: User, user_id: int, *, active: bool) -> User:
        return self.update(actor, user_id, active=active)

    def change_role(self, actor: User, user_id: int, role: Role) -> User:
        """Give ``user_id`` another role, keeping the technician profile where both have one."""
        return self.update(actor, user_id, role=role)

    def update_technician(self, actor: User, user_id: int, fields: TechnicianFields) -> Technician:
        user = self.update(actor, user_id, technician=fields)
        assert isinstance(user, Technician)  # noqa: S101 - __apply_profile refused otherwise
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

    def __with_role(self, actor: User, user: User, role: Role) -> User:
        """``user`` rebuilt with ``role``, carrying the technician profile where both have one."""
        self.__not_self(actor, user, "change your own role")
        self.__may_manage(actor, role)
        if Permission.INCIDENT_WORK not in permissions_for(role):
            # Decided from permissions, not the class: escalation hands incidents to
            # administrators too, and they would be stranded with someone who cannot open them.
            self.__holds_nothing(user, "changing the role")
        if role is not Role.TEAM_LEAD:
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
        return self.__build(
            role,
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            active=user.active,
            technician=carried,
        )

    def __apply_profile(self, user: User, fields: TechnicianFields) -> None:
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

    @staticmethod
    def __may_manage(actor: User, role: Role) -> None:
        """Nobody manages, or hands out, a role above their own (§3: the IT Manager is level 3).

        Administrators and IT Managers hold the same permissions, so without this an
        administrator could demote or switch off the IT Manager, or mint a new one.
        """
        if (escalation_level(role) or 0) > (actor.escalation_level or 0):
            raise UnauthorizedOperationError(
                "Only someone at or above that role can create or change such an account."
            )

    def __holds_nothing(self, user: User, before: str) -> None:
        if self.__uow.incidents.workloads().get(user.id, 0) > 0:
            raise InvalidUserInputError(
                {"user_id": f"Reassign this person's open incidents before {before}."}
            )

    def __leads_no_team(self, user: User) -> None:
        if any(team.lead_id == user.id for team in self.__uow.catalogue.teams()):
            raise InvalidUserInputError(
                {"user_id": "This person leads a team; give the team another lead first."}
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
