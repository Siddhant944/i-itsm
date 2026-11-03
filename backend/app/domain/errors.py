"""The ITSMError hierarchy (blueprint §8): 8 groups and 14 specific errors.

Only these exceptions cross layer boundaries. Each has a stable ``code``; the API layer's
global handlers map the groups to HTTP statuses (P2.6) and never expose stack traces.
Read-only ``details`` give handlers and the UI structured context.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar


class ITSMError(Exception):
    """Base of every domain and application error."""

    code: ClassVar[str] = "itsm_error"
    default_message: ClassVar[str] = "An I-ITSM error occurred."

    def __init__(
        self, message: str | None = None, details: Mapping[str, object] | None = None
    ) -> None:
        self.__message = message or self.default_message
        self.__details: Mapping[str, object] = MappingProxyType(dict(details or {}))
        super().__init__(self.__message)

    @property
    def message(self) -> str:
        """Human-readable, safe-to-show description."""
        return self.__message

    @property
    def details(self) -> Mapping[str, object]:
        """Read-only structured context (never secrets or stack traces)."""
        return self.__details


# ------------------------------------------------------------------ groups
class AuthenticationError(ITSMError):
    """The caller's identity could not be established (HTTP 401)."""

    code = "authentication_error"


class AuthorizationError(ITSMError):
    """The caller may not perform this operation (HTTP 403; audited)."""

    code = "authorization_error"


class ValidationError(ITSMError):
    """The input breaks a rule (HTTP 422 with field errors)."""

    code = "validation_error"


class NotFoundError(ITSMError):
    """A referenced entity does not exist (HTTP 404)."""

    code = "not_found"


class ConflictError(ITSMError):
    """The request conflicts with the current state (HTTP 409)."""

    code = "conflict"


class AssignmentError(ITSMError):
    """No technician can take the incident (queued for the Team Lead, or 409 when manual)."""

    code = "assignment_error"


class ConfigurationError(ITSMError):
    """Required configuration is missing (default applied and the admin alerted)."""

    code = "configuration_error"


class InfrastructureError(ITSMError):
    """A database or network dependency failed (HTTP 503 with rollback)."""

    code = "infrastructure_error"


# ------------------------------------------------------------------ specific errors
class InvalidLoginError(AuthenticationError):
    """Wrong credentials or a locked account; counts toward lockout."""

    code = "invalid_login"
    default_message = "Invalid email or password."


class UnauthorizedOperationError(AuthorizationError):
    """The user's role or ownership does not allow this action (BR-01, BR-02)."""

    code = "unauthorized_operation"
    default_message = "You are not allowed to perform this operation."


class InvalidUserInputError(ValidationError):
    """One or more fields are invalid."""

    code = "invalid_user_input"
    default_message = "Some fields are invalid."

    def __init__(self, field_errors: Mapping[str, str], message: str | None = None) -> None:
        self.__field_errors: Mapping[str, str] = MappingProxyType(dict(field_errors))
        super().__init__(message, {"field_errors": dict(field_errors)})

    @property
    def field_errors(self) -> Mapping[str, str]:
        """Read-only map of field name to problem."""
        return self.__field_errors


class InvalidIncidentError(ValidationError):
    """An incident would break a domain invariant (e.g. resolving without a summary)."""

    code = "invalid_incident"
    default_message = "The incident is not valid."


class ServiceNotFoundError(NotFoundError):
    """The referenced IT service does not exist."""

    code = "service_not_found"
    default_message = "IT service not found."


class IncidentNotFoundError(NotFoundError):
    """The referenced incident does not exist."""

    code = "incident_not_found"
    default_message = "Incident not found."


class InvalidStateTransitionError(ConflictError):
    """The lifecycle does not allow moving between these states (blueprint §4)."""

    code = "invalid_state_transition"

    def __init__(self, from_state: str, to_state: str) -> None:
        self.__from_state = from_state
        self.__to_state = to_state
        super().__init__(
            f"An incident cannot move from {from_state} to {to_state}.",
            {"from_state": from_state, "to_state": to_state},
        )

    @property
    def from_state(self) -> str:
        return self.__from_state

    @property
    def to_state(self) -> str:
        return self.__to_state


class DuplicateIncidentError(ConflictError):
    """A near-identical incident from the same reporter already exists (BR-09)."""

    code = "duplicate_incident"

    def __init__(self, existing_incident_id: str) -> None:
        self.__existing_incident_id = existing_incident_id
        super().__init__(
            f"This looks like {existing_incident_id}, which you reported recently.",
            {"existing_incident_id": existing_incident_id},
        )

    @property
    def existing_incident_id(self) -> str:
        return self.__existing_incident_id


class ConcurrentModificationError(ConflictError):
    """Someone else changed the record first (optimistic locking)."""

    code = "concurrent_modification"
    default_message = "This incident was changed by someone else. Reload and try again."


class TechnicianUnavailableError(AssignmentError):
    """No available technician has spare capacity (BR-06)."""

    code = "technician_unavailable"
    default_message = "No technician is available; the incident is queued for the Team Lead."


class WorkloadExceededError(AssignmentError):
    """The assignment would push a technician above the 10-point cap (BR-06)."""

    code = "workload_exceeded"
    default_message = "This assignment would exceed the technician's workload limit."


class MissingSLAConfigurationError(ConfigurationError):
    """No SLA policy exists for the tier and priority (blueprint §5.2)."""

    code = "missing_sla_configuration"
    default_message = "No SLA policy is configured for this tier and priority."


class DatabaseFailureError(InfrastructureError):
    """The database could not complete the operation."""

    code = "database_failure"
    default_message = "The database is unavailable. Please try again."


class NetworkFailureError(InfrastructureError):
    """An external service could not be reached."""

    code = "network_failure"
    default_message = "An external service could not be reached."
