"""Who may see and who may act on an incident (BR-01, BR-02, BR-03).

These are the rules the §8 table turns into 403s. They live in the domain so one function
answers the question for the API, the services and the tests alike, and so neither the routers
nor the service layer ever reaches for ``isinstance``: everything is decided from the role's
permissions plus the incident's own reporter, assignee and team.
"""

from collections.abc import Collection

from app.domain.errors import UnauthorizedOperationError
from app.domain.incident import Incident
from app.domain.permissions import Permission
from app.domain.search import AWAITING_ASSIGNMENT
from app.domain.users import User

NO_TEAM: frozenset[int] = frozenset()


def awaits_a_lead(incident: Incident) -> bool:
    """True for an incident nobody holds yet (§5.3: "queued for the Team Lead").

    It belongs to no team until someone assigns it, so every Team Lead may see and assign it;
    otherwise the queue the blueprint describes would be one that no lead could open.
    """
    return incident.assignee_id is None and incident.status in AWAITING_ASSIGNMENT


def can_view(user: User, incident: Incident, team_member_ids: Collection[int] = NO_TEAM) -> bool:
    """BR-01: an employee sees only their own incidents; staff see what they work on.

    ``team_member_ids`` are the technicians in the viewer's team, which only matters for a
    Team Lead looking at their team's queue.
    """
    if not user.active:
        return False
    if user.can(Permission.INCIDENT_VIEW_ALL):
        return True
    if incident.reporter_id == user.id:
        return True
    if incident.assignee_id == user.id and user.can(Permission.INCIDENT_VIEW_ASSIGNED):
        return True
    if user.can(Permission.INCIDENT_VIEW_TEAM) and awaits_a_lead(incident):
        return True
    return (
        user.can(Permission.INCIDENT_VIEW_TEAM)
        and incident.assignee_id is not None
        and incident.assignee_id in team_member_ids
    )


def can_work(user: User, incident: Incident, team_member_ids: Collection[int] = NO_TEAM) -> bool:
    """BR-02: only the assignee, the escalation owner or an admin may work an incident.

    Escalation moves the incident to its new owner, so "the escalation owner" is simply
    whoever the assignee is now. A Team Lead may also act on their team's incidents.
    """
    if not user.active or not user.can(Permission.INCIDENT_WORK):
        return False
    if user.can(Permission.INCIDENT_VIEW_ALL):
        return True
    if incident.assignee_id == user.id:
        return True
    if user.can(Permission.INCIDENT_REASSIGN) and awaits_a_lead(incident):
        return True
    return (
        user.can(Permission.INCIDENT_REASSIGN)
        and incident.assignee_id is not None
        and incident.assignee_id in team_member_ids
    )


def can_cancel(user: User, incident: Incident) -> bool:
    """The reporter may withdraw their own incident; an admin may cancel any."""
    if not user.active:
        return False
    if user.can(Permission.INCIDENT_CANCEL_ANY):
        return True
    return incident.reporter_id == user.id and user.can(Permission.INCIDENT_CANCEL_OWN)


def ensure_can_view(
    user: User, incident: Incident, team_member_ids: Collection[int] = NO_TEAM
) -> None:
    if not can_view(user, incident, team_member_ids):
        raise UnauthorizedOperationError(f"You may not view {incident.id}.")


def ensure_can_work(
    user: User, incident: Incident, team_member_ids: Collection[int] = NO_TEAM
) -> None:
    if not can_work(user, incident, team_member_ids):
        raise UnauthorizedOperationError(f"You may not work on {incident.id}.")


def ensure_can_cancel(user: User, incident: Incident) -> None:
    if not can_cancel(user, incident):
        raise UnauthorizedOperationError(f"You may not cancel {incident.id}.")


def ensure_is_reporter(user: User, incident: Incident) -> None:
    """BR-03: only the reporter verifies or rejects a fix."""
    if user.id != incident.reporter_id:
        raise UnauthorizedOperationError("Only the person who reported it can verify the fix.")
