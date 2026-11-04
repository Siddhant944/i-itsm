"""Password hashing and access tokens (blueprint §8)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    Argon2PasswordHasher,
    FakePasswordHasher,
    InvalidTokenError,
    JwtTokenService,
    PasswordHasher,
    password_problem,
)

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SECRET = "a-test-signing-secret-of-adequate-length"
OTHER_SECRET = "a-different-signing-secret-entirely"


@pytest.fixture(params=["argon2", "fake"])
def hasher(request: pytest.FixtureRequest) -> PasswordHasher:
    return Argon2PasswordHasher() if request.param == "argon2" else FakePasswordHasher()


def test_a_hash_verifies_only_the_password_it_was_made_from(hasher: PasswordHasher) -> None:
    hashed = hasher.hash("correct horse battery")
    assert hasher.verify("correct horse battery", hashed) is True
    assert hasher.verify("Correct horse battery", hashed) is False
    assert hasher.verify("", hashed) is False


def test_a_hash_never_contains_the_password(hasher: PasswordHasher) -> None:
    if isinstance(hasher, FakePasswordHasher):
        pytest.skip("the fake is deliberately transparent; only the real hasher must hide it")
    assert "correct horse battery" not in hasher.hash("correct horse battery")


def test_the_same_password_hashes_differently_each_time() -> None:
    """Argon2 salts every hash, so two users with one password do not look alike."""
    hasher = Argon2PasswordHasher()
    assert hasher.hash("same password") != hasher.hash("same password")


def test_a_corrupt_stored_hash_is_a_failed_check_not_a_crash(hasher: PasswordHasher) -> None:
    assert hasher.verify("anything", "not-a-hash-at-all") is False
    assert hasher.verify("anything", "") is False


def test_password_rules_reject_short_long_and_padded(hasher: PasswordHasher) -> None:
    assert password_problem("x" * MIN_PASSWORD_LENGTH) is None
    assert password_problem("x" * (MIN_PASSWORD_LENGTH - 1)) is not None
    assert password_problem("x" * (MAX_PASSWORD_LENGTH + 1)) is not None
    assert password_problem(" padded ") is not None


def test_a_token_round_trips_its_claims() -> None:
    tokens = JwtTokenService(SECRET, timedelta(minutes=30))
    claims = tokens.read(tokens.issue(7, "technician", NOW), NOW)
    assert (claims.user_id, claims.role) == (7, "technician")
    assert claims.issued_at == NOW
    assert claims.expires_at == NOW + timedelta(minutes=30)


def test_a_token_expires_on_the_injected_clock_not_the_system_clock() -> None:
    """The demo runs on an accelerated clock, so expiry must follow the clock we pass in."""
    tokens = JwtTokenService(SECRET, timedelta(minutes=30))
    token = tokens.issue(7, "employee", NOW)
    assert tokens.read(token, NOW + timedelta(minutes=29, seconds=59)).user_id == 7
    with pytest.raises(InvalidTokenError):
        tokens.read(token, NOW + timedelta(minutes=30))


def test_a_token_signed_with_another_key_is_refused() -> None:
    token = JwtTokenService(OTHER_SECRET, timedelta(minutes=30)).issue(7, "employee", NOW)
    with pytest.raises(InvalidTokenError):
        JwtTokenService(SECRET, timedelta(minutes=30)).read(token, NOW)


@pytest.mark.parametrize("token", ["", "not.a.token", "a.b.c", "x" * 40])
def test_a_malformed_token_is_refused(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        JwtTokenService(SECRET, timedelta(minutes=30)).read(token, NOW)


def test_a_token_missing_a_claim_is_refused() -> None:
    import jwt

    token = jwt.encode({"sub": "7"}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        JwtTokenService(SECRET, timedelta(minutes=30)).read(token, NOW)


def test_an_unsigned_token_is_refused() -> None:
    """ "alg": "none" must never be accepted."""
    import jwt

    token = jwt.encode(
        {"sub": "7", "role": "administrator", "iat": 0, "exp": 9999999999},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        JwtTokenService(SECRET, timedelta(minutes=30)).read(token, NOW)


def test_a_token_service_needs_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        JwtTokenService("", timedelta(minutes=30))
