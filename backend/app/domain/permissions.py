"""Roles, permissions and the role -> permission map (blueprint §3).

Authorisation asks ``permissions_for(role)``; it never inspects a user's class. Each role's set
is built from the one below it, mirroring the is-a hierarchy (TeamLead ⊃ Technician,
ITManager ⊇ Administrator) without isinstance checks.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Role(StrEnum):
    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    TEAM_LEAD = "team_lead"
    ADMINISTRATOR = "administrator"
    IT_MANAGER = "it_manager"


class Portal(StrEnum):
    """The three visibly different frontends."""

    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    ADMIN = "admin"


class Permission(StrEnum):
    # reporter capabilities (any role may report and follow its own incidents)
    INCIDENT_CREATE = "incident:create"
    INCIDENT_VIEW_OWN = "incident:view_own"
    INCIDENT_ADD_INFO = "incident:add_info"
    INCIDENT_VERIFY = "incident:verify"
    INCIDENT_CANCEL_OWN = "incident:cancel_own"
    # support work
    INCIDENT_VIEW_ASSIGNED = "incident:view_assigned"
    INCIDENT_WORK = "incident:work"
    INCIDENT_OVERRIDE_PRIORITY = "incident:override_priority"
    INCIDENT_OVERRIDE_CATEGORY = "incident:override_category"
    INCIDENT_CONFIRM_DUPLICATE = "incident:confirm_duplicate"
    WORKLOAD_VIEW_OWN = "workload:view_own"
    # team lead
    INCIDENT_VIEW_TEAM = "incident:view_team"
    INCIDENT_REASSIGN = "incident:reassign"
    WORKLOAD_VIEW_TEAM = "workload:view_team"
    # administration
    INCIDENT_VIEW_ALL = "incident:view_all"
    INCIDENT_CANCEL_ANY = "incident:cancel_any"
    USERS_MANAGE = "users:manage"
    TECHNICIANS_MANAGE = "technicians:manage"
    CATALOGUE_MANAGE = "catalogue:manage"
    SLA_MANAGE = "sla:manage"
    STRATEGY_MANAGE = "strategy:manage"
    SLA_VIOLATIONS_VIEW = "sla:view_violations"
    REPORTS_VIEW = "reports:view"
    AUDIT_VIEW = "audit:view"
    AUDIT_VERIFY = "audit:verify"


P = Permission
_REPORTER = frozenset(
    {
        P.INCIDENT_CREATE,
        P.INCIDENT_VIEW_OWN,
        P.INCIDENT_ADD_INFO,
        P.INCIDENT_VERIFY,
        P.INCIDENT_CANCEL_OWN,
    }
)
_TECHNICIAN = _REPORTER | {
    P.INCIDENT_VIEW_ASSIGNED,
    P.INCIDENT_WORK,
    P.INCIDENT_OVERRIDE_PRIORITY,
    P.INCIDENT_OVERRIDE_CATEGORY,
    P.INCIDENT_CONFIRM_DUPLICATE,
    P.WORKLOAD_VIEW_OWN,
}
_TEAM_LEAD = _TECHNICIAN | {P.INCIDENT_VIEW_TEAM, P.INCIDENT_REASSIGN, P.WORKLOAD_VIEW_TEAM}
_ADMINISTRATOR = _TEAM_LEAD | {
    P.INCIDENT_VIEW_ALL,
    P.INCIDENT_CANCEL_ANY,
    P.USERS_MANAGE,
    P.TECHNICIANS_MANAGE,
    P.CATALOGUE_MANAGE,
    P.SLA_MANAGE,
    P.STRATEGY_MANAGE,
    P.SLA_VIOLATIONS_VIEW,
    P.REPORTS_VIEW,
    P.AUDIT_VIEW,
    P.AUDIT_VERIFY,
}

ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.EMPLOYEE: _REPORTER,
        Role.TECHNICIAN: _TECHNICIAN,
        Role.TEAM_LEAD: _TEAM_LEAD,
        Role.ADMINISTRATOR: _ADMINISTRATOR,
        Role.IT_MANAGER: _ADMINISTRATOR,
    }
)

# Escalation chain levels (blueprint §3, §5.5); employees are not in the chain.
_ESCALATION_LEVEL: Mapping[Role, int] = MappingProxyType(
    {Role.TECHNICIAN: 0, Role.TEAM_LEAD: 1, Role.ADMINISTRATOR: 2, Role.IT_MANAGER: 3}
)

_PORTAL: Mapping[Role, Portal] = MappingProxyType(
    {
        Role.EMPLOYEE: Portal.EMPLOYEE,
        Role.TECHNICIAN: Portal.TECHNICIAN,
        Role.TEAM_LEAD: Portal.TECHNICIAN,
        Role.ADMINISTRATOR: Portal.ADMIN,
        Role.IT_MANAGER: Portal.ADMIN,
    }
)


def permissions_for(role: Role) -> frozenset[Permission]:
    """Every permission granted to ``role``."""
    return ROLE_PERMISSIONS[role]


def escalation_level(role: Role) -> int | None:
    """The role's level in the escalation chain, or None for employees."""
    return _ESCALATION_LEVEL.get(role)


def portal_for(role: Role) -> Portal:
    """The frontend portal a user of ``role`` lands in."""
    return _PORTAL[role]
