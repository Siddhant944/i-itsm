import inspect

import pytest

from app.domain import errors
from app.domain.errors import (
    AssignmentError,
    AuthenticationError,
    AuthorizationError,
    ConcurrentModificationError,
    ConfigurationError,
    ConflictError,
    DatabaseFailureError,
    DuplicateIncidentError,
    IncidentNotFoundError,
    InfrastructureError,
    InvalidIncidentError,
    InvalidLoginError,
    InvalidStateTransitionError,
    InvalidUserInputError,
    ITSMError,
    MissingSLAConfigurationError,
    NetworkFailureError,
    NotFoundError,
    ServiceNotFoundError,
    TechnicianUnavailableError,
    UnauthorizedOperationError,
    ValidationError,
    WorkloadExceededError,
)

# Blueprint §8: group -> specific exceptions.
HIERARCHY: dict[type[ITSMError], set[type[ITSMError]]] = {
    AuthenticationError: {InvalidLoginError},
    AuthorizationError: {UnauthorizedOperationError},
    ValidationError: {InvalidUserInputError, InvalidIncidentError},
    NotFoundError: {ServiceNotFoundError, IncidentNotFoundError},
    ConflictError: {
        InvalidStateTransitionError,
        DuplicateIncidentError,
        ConcurrentModificationError,
    },
    AssignmentError: {TechnicianUnavailableError, WorkloadExceededError},
    ConfigurationError: {MissingSLAConfigurationError},
    InfrastructureError: {DatabaseFailureError, NetworkFailureError},
}

ALL_ERRORS = [
    obj
    for _, obj in inspect.getmembers(errors, inspect.isclass)
    if issubclass(obj, ITSMError) and obj is not ITSMError
]


def test_hierarchy_has_exactly_8_groups_and_14_specific_errors() -> None:
    groups = {cls for cls in ALL_ERRORS if ITSMError in cls.__bases__}
    specifics = {cls for cls in ALL_ERRORS if cls not in groups}

    assert groups == set(HIERARCHY)
    assert len(specifics) == 14
    for group, members in HIERARCHY.items():
        assert {cls for cls in specifics if cls.__bases__ == (group,)} == members


def test_specific_names_use_the_error_suffix_and_codes_are_unique() -> None:
    assert all(cls.__name__.endswith("Error") for cls in ALL_ERRORS)
    codes = [cls.code for cls in ALL_ERRORS]
    assert len(codes) == len(set(codes))


def test_every_error_is_an_itsm_error_and_an_exception() -> None:
    error = InvalidLoginError()
    assert isinstance(error, AuthenticationError)
    assert isinstance(error, ITSMError)
    assert isinstance(error, Exception)
    assert error.code == "invalid_login"
    assert str(error) == error.message


def test_invalid_state_transition_names_both_states() -> None:
    error = InvalidStateTransitionError("NEW", "CLOSED")
    assert error.from_state == "NEW"
    assert error.to_state == "CLOSED"
    assert "NEW" in error.message
    assert "CLOSED" in error.message
    assert dict(error.details) == {"from_state": "NEW", "to_state": "CLOSED"}


def test_duplicate_incident_links_the_existing_ticket() -> None:
    error = DuplicateIncidentError("INC-2026-0042")
    assert error.existing_incident_id == "INC-2026-0042"
    assert error.details["existing_incident_id"] == "INC-2026-0042"


def test_invalid_user_input_carries_read_only_field_errors() -> None:
    error = InvalidUserInputError({"title": "must not be empty"})
    assert error.field_errors["title"] == "must not be empty"
    with pytest.raises(TypeError):
        error.field_errors["title"] = "changed"  # type: ignore[index]


def test_custom_message_overrides_the_default() -> None:
    assert IncidentNotFoundError("No incident INC-1").message == "No incident INC-1"
    assert IncidentNotFoundError().message == IncidentNotFoundError.default_message
