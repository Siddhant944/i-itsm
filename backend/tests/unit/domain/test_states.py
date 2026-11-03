"""The 100-pair lifecycle matrix (blueprint §4): exactly 20 legal transitions."""

from collections.abc import Callable

import pytest

from app.domain.errors import InvalidStateTransitionError
from app.domain.states import IncidentState, IncidentStatus, state_for

S = IncidentStatus
LEGAL = {
    (S.NEW, S.CLASSIFIED),
    (S.NEW, S.CANCELLED),
    (S.CLASSIFIED, S.ASSIGNED),
    (S.CLASSIFIED, S.CANCELLED),
    (S.ASSIGNED, S.ACKNOWLEDGED),
    (S.ASSIGNED, S.ASSIGNED),
    (S.ASSIGNED, S.CANCELLED),
    (S.ACKNOWLEDGED, S.IN_PROGRESS),
    (S.ACKNOWLEDGED, S.ASSIGNED),
    (S.ACKNOWLEDGED, S.CANCELLED),
    (S.IN_PROGRESS, S.ON_HOLD),
    (S.IN_PROGRESS, S.RESOLVED),
    (S.IN_PROGRESS, S.ASSIGNED),
    (S.IN_PROGRESS, S.CANCELLED),
    (S.ON_HOLD, S.IN_PROGRESS),
    (S.ON_HOLD, S.CANCELLED),
    (S.RESOLVED, S.VERIFIED),
    (S.RESOLVED, S.IN_PROGRESS),
    (S.RESOLVED, S.CLOSED),
    (S.VERIFIED, S.CLOSED),
}

# Every trigger that could lead to each target state.
TRIGGERS: dict[IncidentStatus, list[Callable[[IncidentState], IncidentStatus]]] = {
    S.NEW: [],
    S.CLASSIFIED: [lambda s: s.classify()],
    S.ASSIGNED: [lambda s: s.assign()],
    S.ACKNOWLEDGED: [lambda s: s.acknowledge()],
    S.IN_PROGRESS: [lambda s: s.start(), lambda s: s.resume(), lambda s: s.reject()],
    S.ON_HOLD: [lambda s: s.hold()],
    S.RESOLVED: [lambda s: s.resolve()],
    S.VERIFIED: [lambda s: s.verify()],
    S.CLOSED: [lambda s: s.close(), lambda s: s.auto_close()],
    S.CANCELLED: [lambda s: s.cancel()],
}


def attempt(source: IncidentStatus, target: IncidentStatus) -> bool:
    for trigger in TRIGGERS[target]:
        try:
            if trigger(state_for(source)) is target:
                return True
        except InvalidStateTransitionError:
            continue
    return False


def test_there_are_10_states_and_exactly_20_legal_transitions() -> None:
    assert len(IncidentStatus) == 10
    assert len(LEGAL) == 20


@pytest.mark.parametrize("target", list(IncidentStatus))
@pytest.mark.parametrize("source", list(IncidentStatus))
def test_transition_matrix(source: IncidentStatus, target: IncidentStatus) -> None:
    assert attempt(source, target) is ((source, target) in LEGAL)


def test_illegal_trigger_names_both_states() -> None:
    with pytest.raises(InvalidStateTransitionError) as caught:
        state_for(S.NEW).close()
    assert (caught.value.from_state, caught.value.to_state) == ("NEW", "CLOSED")


@pytest.mark.parametrize("status", [S.CLOSED, S.CANCELLED])
def test_terminal_states_allow_nothing(status: IncidentStatus) -> None:
    state = state_for(status)
    assert state.is_terminal
    assert not any(attempt(status, target) for target in IncidentStatus)


def test_registry_returns_one_state_object_per_status() -> None:
    for status in IncidentStatus:
        assert state_for(status).status is status
        assert state_for(status) is state_for(status)
