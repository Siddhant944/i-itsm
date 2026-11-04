"""Who may see and act on an incident (BR-01, BR-02, BR-03)."""

from datetime import UTC, datetime

import pytest

from app.core.clock import FakeClock
from app.domain.access import (
    can_view,
    can_work,
    ensure_can_cancel,
    ensure_can_view,
    ensure_can_work,
    ensure_is_reporter,
)
from app.domain.errors import UnauthorizedOperationError
from app.domain.incident import Incident, IncidentFactory
from app.domain.permissions import Role
from app.domain.users import User, UserFactory

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
REPORTER_ID, OTHER_EMPLOYEE_ID, ASSIGNEE_ID, OTHER_TECH_ID, LEAD_ID, ADMIN_ID = 1, 2, 3, 4, 5, 6
TEAM = frozenset({ASSIGNEE_ID, OTHER_TECH_ID, LEAD_ID})


def user(role: Role, user_id: int) -> User:
    return UserFactory.create(role, user_id=user_id, email=f"u{user_id}@campus.edu", full_name="U")


@pytest.fixture
def incident() -> Incident:
    clock = FakeClock(NOW)
    built = IncidentFactory.create(
        sequence=1,
        clock=clock,
        reporter_id=REPORTER_ID,
        title="Wi-Fi down",
        description="No signal",
        service_id=1,
        impact=2,
        urgency=2,
    )
    built.classify(1, None, clock)
    built.assign(ASSIGNEE_ID, None, clock)
    return built


# ---------------------------------------------------------------- BR-01
def test_BR01_an_employee_sees_only_their_own_incidents(incident: Incident) -> None:
    assert can_view(user(Role.EMPLOYEE, REPORTER_ID), incident) is True
    assert can_view(user(Role.EMPLOYEE, OTHER_EMPLOYEE_ID), incident) is False


def test_BR01_viewing_someone_elses_incident_is_refused(incident: Incident) -> None:
    ensure_can_view(user(Role.EMPLOYEE, REPORTER_ID), incident)
    with pytest.raises(UnauthorizedOperationError):
        ensure_can_view(user(Role.EMPLOYEE, OTHER_EMPLOYEE_ID), incident)


def test_BR01_an_employee_cannot_work_on_their_own_incident(incident: Incident) -> None:
    """Reporting it is not permission to resolve it."""
    assert can_work(user(Role.EMPLOYEE, REPORTER_ID), incident) is False
    with pytest.raises(UnauthorizedOperationError):
        ensure_can_work(user(Role.EMPLOYEE, REPORTER_ID), incident)


def test_a_deactivated_user_may_do_nothing(incident: Incident) -> None:
    blocked = user(Role.ADMINISTRATOR, ADMIN_ID)
    blocked.deactivate()
    assert can_view(blocked, incident) is False
    assert can_work(blocked, incident) is False


# ---------------------------------------------------------------- BR-02
def test_BR02_only_the_assignee_an_admin_or_the_team_lead_may_work(incident: Incident) -> None:
    assert can_work(user(Role.TECHNICIAN, ASSIGNEE_ID), incident) is True
    assert can_work(user(Role.TECHNICIAN, OTHER_TECH_ID), incident) is False
    assert can_work(user(Role.ADMINISTRATOR, ADMIN_ID), incident) is True
    assert can_work(user(Role.IT_MANAGER, ADMIN_ID), incident) is True
    assert can_work(user(Role.TEAM_LEAD, LEAD_ID), incident, TEAM) is True


def test_BR02_a_team_lead_of_another_team_may_not_work(incident: Incident) -> None:
    assert can_work(user(Role.TEAM_LEAD, LEAD_ID), incident, frozenset({99})) is False


def test_BR02_the_escalation_owner_may_work(incident: Incident) -> None:
    """Escalation hands the incident over, so the new owner is simply the assignee now."""
    clock = FakeClock(NOW)
    incident.escalate(LEAD_ID, 1, None, clock)
    assert can_work(user(Role.TEAM_LEAD, LEAD_ID), incident) is True
    assert can_work(user(Role.TECHNICIAN, ASSIGNEE_ID), incident) is False


def test_an_unassigned_incident_may_only_be_worked_by_an_admin() -> None:
    clock = FakeClock(NOW)
    unassigned = IncidentFactory.create(
        sequence=2,
        clock=clock,
        reporter_id=REPORTER_ID,
        title="New",
        description="Nobody owns it yet",
        service_id=1,
        impact=1,
        urgency=1,
    )
    assert can_work(user(Role.TECHNICIAN, ASSIGNEE_ID), unassigned) is False
    assert can_work(user(Role.TEAM_LEAD, LEAD_ID), unassigned, TEAM) is False
    assert can_work(user(Role.ADMINISTRATOR, ADMIN_ID), unassigned) is True


# ---------------------------------------------------------------- viewing, by role
def test_a_technician_sees_what_is_assigned_to_them(incident: Incident) -> None:
    assert can_view(user(Role.TECHNICIAN, ASSIGNEE_ID), incident) is True
    assert can_view(user(Role.TECHNICIAN, OTHER_TECH_ID), incident) is False
    assert can_view(user(Role.TEAM_LEAD, LEAD_ID), incident, TEAM) is True
    assert can_view(user(Role.ADMINISTRATOR, ADMIN_ID), incident) is True


# ---------------------------------------------------------------- BR-03 and cancelling
def test_BR03_only_the_reporter_verifies_or_rejects(incident: Incident) -> None:
    ensure_is_reporter(user(Role.EMPLOYEE, REPORTER_ID), incident)
    for role, user_id in ((Role.TECHNICIAN, ASSIGNEE_ID), (Role.ADMINISTRATOR, ADMIN_ID)):
        with pytest.raises(UnauthorizedOperationError):
            ensure_is_reporter(user(role, user_id), incident)


def test_the_reporter_may_withdraw_and_an_admin_may_cancel_any(incident: Incident) -> None:
    ensure_can_cancel(user(Role.EMPLOYEE, REPORTER_ID), incident)
    ensure_can_cancel(user(Role.ADMINISTRATOR, ADMIN_ID), incident)
    for role, user_id in ((Role.EMPLOYEE, OTHER_EMPLOYEE_ID), (Role.TECHNICIAN, ASSIGNEE_ID)):
        with pytest.raises(UnauthorizedOperationError):
            ensure_can_cancel(user(role, user_id), incident)
