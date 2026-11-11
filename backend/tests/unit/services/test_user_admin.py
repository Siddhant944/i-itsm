"""Managing accounts (blueprint §3, §8): roles are given by an administrator, and audited."""

from datetime import UTC, datetime

import pytest

from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher
from app.domain.audit import AuditAction
from app.domain.catalogue import Skill, Team
from app.domain.errors import InvalidUserInputError, NotFoundError, UnauthorizedOperationError
from app.domain.permissions import Role
from app.domain.users import Employee, TeamLead, Technician, User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.user_admin import TechnicianFields, UserAdminService

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
EMPLOYEE, OTHER, TECH, LEAD, ADMIN = 1, 2, 3, 4, 5
PASSWORD = "a long enough password"


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_skill(Skill(2, "email"))
    people: tuple[tuple[int, Role], ...] = (
        (EMPLOYEE, Role.EMPLOYEE),
        (OTHER, Role.EMPLOYEE),
        (TECH, Role.TECHNICIAN),
        (LEAD, Role.TEAM_LEAD),
        (ADMIN, Role.ADMINISTRATOR),
    )
    for user_id, role in people:
        support = UserFactory.is_support_role(role)
        unit.users.add(
            UserFactory.create(
                role,
                user_id=user_id,
                email=f"user{user_id}@campus.edu",
                full_name=f"User {user_id}",
                skills=SkillSet({"networking"}) if support else None,
                team_id=None,
            )
        )
    team = Team(1, "Network Operations")
    team.add_member(TECH)
    team.add_member(LEAD)
    team.set_lead(LEAD)
    unit.catalogue.save_team(team)
    return unit


@pytest.fixture
def service(uow: InMemoryUnitOfWork) -> UserAdminService:
    return UserAdminService(uow, FakeClock(NOW), FakePasswordHasher())


@pytest.fixture
def admin(uow: InMemoryUnitOfWork) -> User:
    return uow.users.get(ADMIN)


def test_an_employee_sees_only_support_staff_and_themselves_in_the_directory(
    service: UserAdminService, uow: InMemoryUnitOfWork
) -> None:
    seen = {user.id for user in service.directory(uow.users.get(EMPLOYEE))}
    assert seen == {EMPLOYEE, TECH, LEAD, ADMIN}
    assert {user.id for user in service.directory(uow.users.get(TECH))} == {1, 2, 3, 4, 5}


def test_creating_a_technician_stores_the_profile_a_password_and_an_audit_record(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    created = service.create(
        admin,
        email="New.Tech@campus.edu",
        full_name="New Tech",
        password=PASSWORD,
        role=Role.TECHNICIAN,
        technician=TechnicianFields(skills=("Email",), experience_level=3, team_id=1),
    )
    assert isinstance(created, Technician)
    assert created.id == 6
    assert created.skills.names == ("email",)
    assert (created.experience_level, created.team_id, created.available) == (3, 1, True)
    assert uow.credentials.get(6).has_password
    record = uow.audit.records()[-1]
    assert record.action is AuditAction.USER_MANAGED
    assert record.details == {"change": "created", "user_id": 6, "role": "technician"}
    assert record.actor_id == ADMIN


def test_creation_refuses_a_taken_email_a_weak_password_and_an_unknown_skill(
    service: UserAdminService, admin: User
) -> None:
    def create(**changes: object) -> User:
        fields: dict[str, object] = {
            "email": "fresh@campus.edu",
            "full_name": "Fresh",
            "password": PASSWORD,
            "role": Role.TECHNICIAN,
        }
        fields.update(changes)
        return service.create(admin, **fields)  # type: ignore[arg-type]

    with pytest.raises(InvalidUserInputError, match="fields"):
        create(email="user1@campus.edu")
    with pytest.raises(InvalidUserInputError):
        create(password="short")
    with pytest.raises(InvalidUserInputError):
        create(technician=TechnicianFields(skills=("juggling",)))
    with pytest.raises(InvalidUserInputError):
        create(technician=TechnicianFields(team_id=77))


def test_an_account_can_be_switched_off_and_on_but_not_ones_own(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    assert service.set_active(admin, EMPLOYEE, active=False).active is False
    assert uow.users.get(EMPLOYEE).active is False
    assert service.set_active(admin, EMPLOYEE, active=True).active is True
    with pytest.raises(UnauthorizedOperationError):
        service.set_active(admin, ADMIN, active=False)
    with pytest.raises(NotFoundError):
        service.set_active(admin, 99, active=False)


def test_an_employee_can_be_made_a_technician_and_a_technician_a_team_lead(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    promoted = service.change_role(admin, EMPLOYEE, Role.TECHNICIAN)
    assert isinstance(promoted, Technician)
    assert isinstance(uow.users.get(EMPLOYEE), Technician)

    lead = service.change_role(admin, TECH, Role.TEAM_LEAD)
    assert isinstance(lead, TeamLead)
    assert lead.skills.names == ("networking",)
    assert lead.team_id == 1
    assert uow.audit.records()[-1].details == {
        "change": "role_changed",
        "user_id": TECH,
        "role": "team_lead",
        "previous": "technician",
    }


def test_a_technician_with_no_open_work_can_go_back_to_being_an_employee(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    demoted = service.change_role(admin, TECH, Role.EMPLOYEE)
    assert isinstance(demoted, Employee)
    assert TECH not in {t.id for t in uow.users.technicians()}


def test_a_role_change_is_refused_for_oneself_and_for_someone_leading_a_team(
    service: UserAdminService, admin: User
) -> None:
    with pytest.raises(UnauthorizedOperationError):
        service.change_role(admin, ADMIN, Role.EMPLOYEE)
    with pytest.raises(InvalidUserInputError):
        service.change_role(admin, LEAD, Role.TECHNICIAN)


def test_the_same_role_again_changes_nothing(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    service.change_role(admin, TECH, Role.TECHNICIAN)
    assert uow.audit.records() == ()


def test_a_technicians_profile_is_edited_in_one_step(
    service: UserAdminService, uow: InMemoryUnitOfWork, admin: User
) -> None:
    updated = service.update_technician(
        admin,
        TECH,
        TechnicianFields(skills=("email", "networking"), experience_level=3, available=False),
    )
    assert updated.skills.names == ("email", "networking")
    assert (updated.experience_level, updated.available, updated.team_id) == (3, False, None)
    assert uow.catalogue.get_team(1).member_ids == (LEAD,)


def test_only_support_staff_have_a_profile_and_a_lead_stays_in_their_team(
    service: UserAdminService, admin: User
) -> None:
    with pytest.raises(InvalidUserInputError):
        service.update_technician(admin, EMPLOYEE, TechnicianFields())
    with pytest.raises(InvalidUserInputError):
        service.update_technician(admin, LEAD, TechnicianFields(team_id=None))
