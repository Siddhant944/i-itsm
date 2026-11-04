"""Login protection (blueprint §8): five failures lock an account for fifteen minutes."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.credentials import (
    LOCKOUT_DURATION,
    MAX_FAILED_ATTEMPTS,
    Credentials,
)
from app.domain.errors import InvalidUserInputError

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
HASH = "$argon2id$v=19$fake"


def fresh() -> Credentials:
    return Credentials(user_id=1, password_hash=HASH)


def test_a_new_account_is_unlocked_and_has_no_failures() -> None:
    credentials = fresh()
    assert credentials.failed_attempts == 0
    assert credentials.locked_until is None
    assert credentials.is_locked(NOW) is False
    assert credentials.has_password is True


def test_an_account_without_a_password_cannot_be_signed_into() -> None:
    credentials = Credentials(user_id=1)
    assert credentials.has_password is False
    assert credentials.password_hash is None


def test_the_fifth_failure_locks_the_account_for_fifteen_minutes() -> None:
    clock = FakeClock(NOW)
    credentials = fresh()
    for attempt in range(1, MAX_FAILED_ATTEMPTS):
        assert credentials.record_failure(clock.now()) is False
        assert credentials.failed_attempts == attempt
        assert credentials.is_locked(clock.now()) is False
        clock.advance(timedelta(seconds=5))

    assert credentials.record_failure(clock.now()) is True
    assert credentials.failed_attempts == MAX_FAILED_ATTEMPTS
    assert credentials.is_locked(clock.now()) is True
    assert credentials.locked_until == clock.now() + LOCKOUT_DURATION


def test_the_lock_lifts_exactly_when_it_expires() -> None:
    clock = FakeClock(NOW)
    credentials = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS):
        credentials.record_failure(clock.now())

    clock.advance(LOCKOUT_DURATION - timedelta(microseconds=1))
    assert credentials.is_locked(clock.now()) is True
    assert credentials.locked_for(clock.now()) > timedelta(0)

    clock.advance(timedelta(microseconds=1))
    assert credentials.is_locked(clock.now()) is False
    assert credentials.locked_for(clock.now()) == timedelta(0)


def test_an_expired_lock_starts_the_count_again() -> None:
    """Otherwise the very next mistake would lock the account straight away."""
    clock = FakeClock(NOW)
    credentials = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS):
        credentials.record_failure(clock.now())
    clock.advance(LOCKOUT_DURATION)

    assert credentials.record_failure(clock.now()) is False
    assert credentials.failed_attempts == 1
    assert credentials.is_locked(clock.now()) is False


def test_a_successful_sign_in_clears_the_failures() -> None:
    clock = FakeClock(NOW)
    credentials = fresh()
    credentials.record_failure(clock.now())
    credentials.record_failure(clock.now())
    credentials.record_success(clock.now())
    assert credentials.failed_attempts == 0
    assert credentials.locked_until is None
    assert credentials.last_login_at == clock.now()


def test_setting_a_new_password_releases_the_lock() -> None:
    clock = FakeClock(NOW)
    credentials = fresh()
    for _ in range(MAX_FAILED_ATTEMPTS):
        credentials.record_failure(clock.now())
    assert credentials.is_locked(clock.now()) is True

    credentials.set_password_hash("$argon2id$v=19$new")
    assert credentials.password_hash == "$argon2id$v=19$new"
    assert credentials.is_locked(clock.now()) is False
    assert credentials.failed_attempts == 0


def test_a_blank_password_hash_is_refused() -> None:
    with pytest.raises(InvalidUserInputError):
        fresh().set_password_hash("  ")


def test_restoring_keeps_the_stored_counters() -> None:
    locked_until = NOW + timedelta(minutes=5)
    credentials = Credentials(
        user_id=7,
        password_hash=HASH,
        failed_attempts=MAX_FAILED_ATTEMPTS,
        locked_until=locked_until,
        last_login_at=NOW - timedelta(days=1),
    )
    assert credentials.user_id == 7
    assert credentials.is_locked(NOW) is True
    assert credentials.locked_for(NOW) == timedelta(minutes=5)
    assert credentials.last_login_at == NOW - timedelta(days=1)
