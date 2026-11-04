import pytest

from app.domain.errors import InvalidUserInputError
from app.domain.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Portal,
    Role,
    escalation_level,
    permissions_for,
    portal_for,
)
from app.domain.users import (
    Administrator,
    Employee,
    ITManager,
    TeamLead,
    Technician,
    User,
    UserFactory,
)
from app.domain.value_objects import EmailAddress, SkillSet

P = Permission
REPORTER = {P.INCIDENT_CREATE, P.INCIDENT_VIEW_OWN, P.INCIDENT_ADD_INFO, P.INCIDENT_VERIFY}


def make(role: Role, **kwargs: object) -> User:
    return UserFactory.create(role, user_id=7, email="u@campus.edu", full_name="U", **kwargs)  # type: ignore[arg-type]


def test_every_role_has_a_permission_set() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize("role", list(Role))
def test_every_role_can_report_and_follow_its_own_incidents(role: Role) -> None:
    assert permissions_for(role) >= REPORTER


def test_employee_cannot_work_incidents_or_administer() -> None:
    employee = make(Role.EMPLOYEE)
    assert not employee.can(P.INCIDENT_WORK)
    assert not employee.can(P.USERS_MANAGE)
    assert not employee.can(P.INCIDENT_VIEW_ALL)


def test_technician_works_assigned_incidents_but_cannot_administer() -> None:
    technician = make(Role.TECHNICIAN)
    assert technician.can(P.INCIDENT_WORK)
    assert technician.can(P.WORKLOAD_VIEW_OWN)
    assert not technician.can(P.INCIDENT_REASSIGN)
    assert not technician.can(P.SLA_MANAGE)


def test_permission_sets_follow_the_is_a_hierarchy() -> None:
    assert permissions_for(Role.TEAM_LEAD) > permissions_for(Role.TECHNICIAN)
    assert permissions_for(Role.IT_MANAGER) >= permissions_for(Role.ADMINISTRATOR)
    assert make(Role.TEAM_LEAD).can(P.INCIDENT_REASSIGN)


def test_administrators_configure_the_system_and_may_act_on_any_incident() -> None:
    admin = make(Role.ADMINISTRATOR)
    for permission in (
        P.USERS_MANAGE,
        P.TECHNICIANS_MANAGE,
        P.CATALOGUE_MANAGE,
        P.SLA_MANAGE,
        P.STRATEGY_MANAGE,
        P.INCIDENT_VIEW_ALL,
        P.INCIDENT_WORK,
        P.AUDIT_VIEW,
        P.AUDIT_VERIFY,
        P.REPORTS_VIEW,
        P.SLA_VIOLATIONS_VIEW,
    ):
        assert admin.can(permission), permission


@pytest.mark.parametrize(
    ("role", "level"),
    [
        (Role.EMPLOYEE, None),
        (Role.TECHNICIAN, 0),
        (Role.TEAM_LEAD, 1),
        (Role.ADMINISTRATOR, 2),
        (Role.IT_MANAGER, 3),
    ],
)
def test_escalation_levels(role: Role, level: int | None) -> None:
    assert escalation_level(role) == level
    assert make(role).escalation_level == level


@pytest.mark.parametrize(
    ("role", "portal"),
    [
        (Role.EMPLOYEE, Portal.EMPLOYEE),
        (Role.TECHNICIAN, Portal.TECHNICIAN),
        (Role.TEAM_LEAD, Portal.TECHNICIAN),
        (Role.ADMINISTRATOR, Portal.ADMIN),
        (Role.IT_MANAGER, Portal.ADMIN),
    ],
)
def test_each_role_lands_in_its_portal(role: Role, portal: Portal) -> None:
    assert portal_for(role) is portal


@pytest.mark.parametrize(
    ("role", "cls"),
    [
        (Role.EMPLOYEE, Employee),
        (Role.TECHNICIAN, Technician),
        (Role.TEAM_LEAD, TeamLead),
        (Role.ADMINISTRATOR, Administrator),
        (Role.IT_MANAGER, ITManager),
    ],
)
def test_factory_builds_the_class_for_each_role(role: Role, cls: type[User]) -> None:
    user = make(role)
    assert type(user) is cls
    assert user.role is role


def test_inheritance_models_only_true_is_a_relationships() -> None:
    assert issubclass(TeamLead, Technician)
    assert issubclass(ITManager, Administrator)
    assert not issubclass(Technician, Employee)
    with pytest.raises(TypeError):
        User(1, EmailAddress("a@b.co"), "A")  # type: ignore[abstract]


def test_attributes_are_name_mangled_and_read_only() -> None:
    user = make(Role.EMPLOYEE)
    assert user.email == EmailAddress("u@campus.edu")
    assert "email" not in vars(user)
    with pytest.raises(AttributeError):
        user.email = EmailAddress("x@y.org")  # type: ignore[misc]


def test_deactivated_users_lose_every_permission() -> None:
    admin = make(Role.ADMINISTRATOR)
    admin.deactivate()
    assert not admin.active
    assert not admin.can(P.INCIDENT_CREATE)
    admin.activate()
    assert admin.can(P.INCIDENT_CREATE)


def test_technician_profile_changes_go_through_methods() -> None:
    tech = make(Role.TECHNICIAN, skills=SkillSet({"networking"}), experience_level=2)
    assert isinstance(tech, Technician)
    assert tech.skills == SkillSet({"networking"})
    assert tech.available
    tech.mark_unavailable()
    assert not tech.available
    tech.mark_available()
    tech.set_experience_level(3)
    tech.update_skills(SkillSet({"payments"}))
    assert (tech.experience_level, tech.skills.names) == (3, ("payments",))


@pytest.mark.parametrize("level", [0, 4])
def test_experience_level_must_be_1_to_3(level: int) -> None:
    with pytest.raises(InvalidUserInputError) as caught:
        make(Role.TECHNICIAN, experience_level=level)
    assert "experience_level" in caught.value.field_errors


def test_factory_rejects_technician_fields_for_other_roles() -> None:
    with pytest.raises(InvalidUserInputError):
        make(Role.EMPLOYEE, skills=SkillSet({"networking"}))


def test_full_name_is_required() -> None:
    with pytest.raises(InvalidUserInputError):
        UserFactory.create(Role.EMPLOYEE, user_id=1, email="a@b.co", full_name="  ")
