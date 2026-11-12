"""The Google ID-token verifier (P4.10), with tokens signed by a key made for the test."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.adapters.google_identity import LEEWAY_SECONDS, GoogleIdTokenVerifier
from app.core.clock import FakeClock
from app.core.config import Settings
from app.domain.errors import InvalidLoginError, NetworkFailureError
from app.main import google_verifier

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
CLIENT = "client-123.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(signer: Any = KEY, **changes: Any) -> str:
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "sub": "1098765",
        "email": "asha@campus.edu",
        "email_verified": True,
        "name": "Asha Rao",
        "hd": "campus.edu",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
    }
    claims.update(changes)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, signer, algorithm="RS256", headers={"kid": "k1"})


def verifier(clock: FakeClock | None = None) -> GoogleIdTokenVerifier:
    return GoogleIdTokenVerifier(CLIENT, clock or FakeClock(NOW), keys=lambda _: KEY.public_key())


def test_a_good_token_gives_the_verified_identity() -> None:
    identity = verifier().verify(token())
    assert (identity.email, identity.full_name, identity.hosted_domain, identity.subject) == (
        "asha@campus.edu",
        "Asha Rao",
        "campus.edu",
        "1098765",
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"aud": "someone-elses-client"},
        {"iss": "https://evil.example.com"},
        {"email_verified": False},
        {"email_verified": None},
        {"sub": None},
    ],
)
def test_a_token_for_another_client_issuer_or_unverified_email_is_refused(
    bad: dict[str, Any],
) -> None:
    with pytest.raises(InvalidLoginError):
        verifier().verify(token(**bad))


def test_a_token_signed_by_another_key_or_mangled_is_refused() -> None:
    with pytest.raises(InvalidLoginError):
        verifier().verify(token(signer=OTHER_KEY))
    with pytest.raises(InvalidLoginError):
        verifier().verify(token()[:-5] + "abcde")


def test_expiry_is_judged_by_the_injected_clock_with_a_minute_of_leeway() -> None:
    clock = FakeClock(NOW + timedelta(hours=1, seconds=LEEWAY_SECONDS))
    assert verifier(clock).verify(token()).subject == "1098765"
    clock.advance(timedelta(seconds=1))
    with pytest.raises(InvalidLoginError):
        verifier(clock).verify(token())


def test_googles_keys_being_unreachable_is_a_network_failure_not_a_bad_token() -> None:
    def down(_: str) -> Any:
        raise jwt.PyJWKClientConnectionError("timed out")

    with pytest.raises(NetworkFailureError):
        GoogleIdTokenVerifier(CLIENT, FakeClock(NOW), keys=down).verify(token())


def test_the_verifier_is_wired_only_with_a_client_id_and_a_campus_domain(
    settings: Settings,
) -> None:
    clock = FakeClock(NOW)
    assert google_verifier(settings, clock) is None
    only_id = settings.model_copy(update={"google_client_id": CLIENT})
    assert google_verifier(only_id, clock) is None
    both = only_id.model_copy(update={"google_hd_domain": "campus.edu"})
    assert isinstance(google_verifier(both, clock), GoogleIdTokenVerifier)
