"""Password hashing and access tokens (blueprint §8).

Both are interfaces with one real implementation and one fast fake, so the service layer can
be tested without Argon2's deliberate slowness and without the wall clock. Token expiry is
checked against an injected Clock rather than the system time, which is what lets the demo run
on an accelerated clock and Playwright move time about (D-009).

This module is in ``core``: it depends on nothing above it, and nothing here knows about users,
roles or HTTP.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

ALGORITHM: Final = "HS256"
MIN_PASSWORD_LENGTH: Final = 8
MAX_PASSWORD_LENGTH: Final = 128  # Argon2 accepts more; a cap keeps a huge body cheap to reject


class PasswordHasher(ABC):
    """Hashes and checks passwords. A new algorithm is one class (blueprint §8)."""

    @abstractmethod
    def hash(self, password: str) -> str: ...

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        """True when ``password`` matches ``hashed``; never raises for a wrong password."""


class Argon2PasswordHasher(PasswordHasher):
    """Argon2id with the reference library's defaults (memory-hard, salted per password)."""

    def __init__(self) -> None:
        self.__hasher = Argon2Hasher()

    def hash(self, password: str) -> str:
        return self.__hasher.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            return self.__hasher.verify(hashed, password)
        except (VerifyMismatchError, InvalidHashError, ValueError):
            return False


class FakePasswordHasher(PasswordHasher):
    """Test double: the same shape, instantly. Never used outside tests and fixtures."""

    PREFIX: Final = "fake-hash:"

    def hash(self, password: str) -> str:
        return f"{self.PREFIX}{password}"

    def verify(self, password: str, hashed: str) -> bool:
        return hashed == self.hash(password)


class InvalidTokenError(Exception):
    """The token is missing, malformed, signed with another key, or past its expiry."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """What a verified access token asserts."""

    user_id: int
    role: str
    issued_at: datetime
    expires_at: datetime


class TokenService(ABC):
    """Issues and reads short-lived access tokens."""

    @abstractmethod
    def issue(self, user_id: int, role: str, now: datetime) -> str: ...

    @abstractmethod
    def read(self, token: str, now: datetime) -> TokenClaims:
        """Raise InvalidTokenError unless the token verifies and has not expired."""


class JwtTokenService(TokenService):
    """HS256 JWTs. Expiry is checked against the caller's clock, not the system clock."""

    def __init__(self, secret: str, ttl: timedelta) -> None:
        if not secret:
            msg = "A signing secret is required."
            raise ValueError(msg)
        self.__secret = secret
        self.__ttl = ttl

    @property
    def ttl(self) -> timedelta:
        return self.__ttl

    def issue(self, user_id: int, role: str, now: datetime) -> str:
        expires_at = now + self.__ttl
        return jwt.encode(
            {
                "sub": str(user_id),
                "role": role,
                "iat": int(now.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            self.__secret,
            algorithm=ALGORITHM,
        )

    def read(self, token: str, now: datetime) -> TokenClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.__secret,
                algorithms=[ALGORITHM],
                # Times are compared with the injected clock below, so PyJWT must not use
                # its own: on an accelerated or fake clock its answer would be wrong.
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "require": ["sub", "role", "iat", "exp"],
                },
            )
            claims = TokenClaims(
                user_id=int(payload["sub"]),
                role=str(payload["role"]),
                issued_at=_moment(payload["iat"]),
                expires_at=_moment(payload["exp"]),
            )
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise InvalidTokenError(str(error)) from error
        if now >= claims.expires_at:
            msg = "The access token has expired."
            raise InvalidTokenError(msg)
        return claims


def _moment(value: object) -> datetime:
    return datetime.fromtimestamp(int(str(value)), UTC)


def password_problem(password: str) -> str | None:
    """Why ``password`` is unacceptable, or None when it is fine (blueprint §8)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    if password.strip() != password:
        return "Must not start or end with a space."
    return None
