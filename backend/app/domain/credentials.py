"""Sign-in state for one account (blueprint §8).

The password itself never reaches the domain: only the hash a hasher produced, so the rule
"five failures lock the account for fifteen minutes" can be tested without Argon2 and without
reading the wall clock. The hash is compared in the service layer, which owns the hasher.
"""

from datetime import datetime, timedelta

from app.domain.errors import InvalidUserInputError

MAX_FAILED_ATTEMPTS = 5  # §8: locked after 5 failed attempts
LOCKOUT_DURATION = timedelta(minutes=15)


class Credentials:
    """What is known about an account's sign-ins: its password hash and its recent failures."""

    def __init__(
        self,
        *,
        user_id: int,
        password_hash: str | None = None,
        failed_attempts: int = 0,
        locked_until: datetime | None = None,
        last_login_at: datetime | None = None,
    ) -> None:
        self.__user_id = user_id
        self.__password_hash = password_hash
        self.__failed_attempts = failed_attempts
        self.__locked_until = locked_until
        self.__last_login_at = last_login_at

    @property
    def user_id(self) -> int:
        return self.__user_id

    @property
    def password_hash(self) -> str | None:
        """The stored hash, or None for an account that has never set a password."""
        return self.__password_hash

    @property
    def has_password(self) -> bool:
        return self.__password_hash is not None

    @property
    def failed_attempts(self) -> int:
        return self.__failed_attempts

    @property
    def locked_until(self) -> datetime | None:
        return self.__locked_until

    @property
    def last_login_at(self) -> datetime | None:
        return self.__last_login_at

    def is_locked(self, now: datetime) -> bool:
        return self.__locked_until is not None and now < self.__locked_until

    def locked_for(self, now: datetime) -> timedelta:
        """How long the account stays locked; zero once the lock has expired."""
        if not self.is_locked(now) or self.__locked_until is None:
            return timedelta(0)
        return self.__locked_until - now

    def record_failure(self, now: datetime) -> bool:
        """Count a failed sign-in. Returns True when this failure locked the account.

        An expired lock starts the count again, so one later mistake cannot lock the account
        straight back out.
        """
        if self.__locked_until is not None and not self.is_locked(now):
            self.__failed_attempts = 0
            self.__locked_until = None
        self.__failed_attempts += 1
        if self.__failed_attempts >= MAX_FAILED_ATTEMPTS:
            self.__locked_until = now + LOCKOUT_DURATION
            return True
        return False

    def record_success(self, now: datetime) -> None:
        self.__failed_attempts = 0
        self.__locked_until = None
        self.__last_login_at = now

    def set_password_hash(self, hashed: str) -> None:
        """Store a new hash; setting a password also releases any lock."""
        if not hashed.strip():
            raise InvalidUserInputError({"password": "Must not be empty."})
        self.__password_hash = hashed.strip()
        self.__failed_attempts = 0
        self.__locked_until = None

    def __repr__(self) -> str:
        return f"Credentials(user_id={self.__user_id}, failures={self.__failed_attempts})"
