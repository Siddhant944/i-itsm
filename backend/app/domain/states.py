"""Incident lifecycle (blueprint §4): 10 states and exactly 20 legal transitions.

Pattern: State. Problem solved: which actions are legal depends on the current status; putting
each rule in its own state class makes illegal moves (such as NEW → CLOSED) impossible instead
of relying on scattered if-statements. Every trigger on the base class raises
InvalidStateTransitionError; each concrete state overrides only its legal triggers.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.domain.errors import InvalidStateTransitionError


class IncidentStatus(StrEnum):
    NEW = "NEW"
    CLASSIFIED = "CLASSIFIED"
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


S = IncidentStatus


class IncidentState:
    """Base state: every trigger is illegal unless a subclass allows it.

    Each trigger returns the status the incident moves to.
    """

    status: S = S.NEW  # overridden by every concrete state

    def _refuse(self, target: S) -> S:
        raise InvalidStateTransitionError(self.status.value, target.value)

    @property
    def is_terminal(self) -> bool:
        return False

    def classify(self) -> S:
        return self._refuse(S.CLASSIFIED)

    def assign(self) -> S:
        """Assign, reassign or escalate to a new owner."""
        return self._refuse(S.ASSIGNED)

    def acknowledge(self) -> S:
        return self._refuse(S.ACKNOWLEDGED)

    def start(self) -> S:
        return self._refuse(S.IN_PROGRESS)

    def hold(self) -> S:
        return self._refuse(S.ON_HOLD)

    def resume(self) -> S:
        return self._refuse(S.IN_PROGRESS)

    def resolve(self) -> S:
        return self._refuse(S.RESOLVED)

    def verify(self) -> S:
        return self._refuse(S.VERIFIED)

    def reject(self) -> S:
        """The reporter rejects the fix and the incident reopens."""
        return self._refuse(S.IN_PROGRESS)

    def close(self) -> S:
        return self._refuse(S.CLOSED)

    def auto_close(self) -> S:
        """Close an unverified resolution after 72 h (BR-03)."""
        return self._refuse(S.CLOSED)

    def cancel(self) -> S:
        return self._refuse(S.CANCELLED)


class _Cancellable(IncidentState):
    def cancel(self) -> S:
        return S.CANCELLED


class _Reassignable(_Cancellable):
    def assign(self) -> S:
        return S.ASSIGNED


class NewState(_Cancellable):
    status = S.NEW

    def classify(self) -> S:
        return S.CLASSIFIED


class ClassifiedState(_Reassignable):
    status = S.CLASSIFIED


class AssignedState(_Reassignable):
    status = S.ASSIGNED

    def acknowledge(self) -> S:
        return S.ACKNOWLEDGED


class AcknowledgedState(_Reassignable):
    status = S.ACKNOWLEDGED

    def start(self) -> S:
        return S.IN_PROGRESS


class InProgressState(_Reassignable):
    status = S.IN_PROGRESS

    def hold(self) -> S:
        return S.ON_HOLD

    def resolve(self) -> S:
        return S.RESOLVED


class OnHoldState(_Cancellable):
    status = S.ON_HOLD

    def resume(self) -> S:
        return S.IN_PROGRESS


class ResolvedState(IncidentState):
    status = S.RESOLVED

    def verify(self) -> S:
        return S.VERIFIED

    def reject(self) -> S:
        return S.IN_PROGRESS

    def auto_close(self) -> S:
        return S.CLOSED


class VerifiedState(IncidentState):
    status = S.VERIFIED

    def close(self) -> S:
        return S.CLOSED


class _TerminalState(IncidentState):
    @property
    def is_terminal(self) -> bool:
        return True


class ClosedState(_TerminalState):
    status = S.CLOSED


class CancelledState(_TerminalState):
    status = S.CANCELLED


_REGISTRY: Mapping[S, IncidentState] = MappingProxyType(
    {
        state.status: state
        for state in (
            NewState(),
            ClassifiedState(),
            AssignedState(),
            AcknowledgedState(),
            InProgressState(),
            OnHoldState(),
            ResolvedState(),
            VerifiedState(),
            ClosedState(),
            CancelledState(),
        )
    }
)


def state_for(status: S) -> IncidentState:
    """Turn a stored status back into its (stateless, shared) state object."""
    return _REGISTRY[status]
