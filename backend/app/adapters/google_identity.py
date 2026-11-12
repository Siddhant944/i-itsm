"""Google Sign-In: checking an ID token from Google Identity Services (blueprint §8, P4.10).

Pattern: Adapter. Problem solved: the auth service wants "who is this, and are they on the
campus domain?" without knowing JWTs, Google's signing keys or its issuer names. This class
checks the RS256 signature against Google's published keys, the audience (our client id), the
issuer, the expiry (against the injected Clock, never the wall clock) and that Google has
verified the email. What it returns is trusted; anything it rejects is an InvalidLoginError.
"""

from collections.abc import Callable
from typing import Any

import jwt

from app.core.clock import Clock
from app.domain.errors import InvalidLoginError, NetworkFailureError
from app.domain.ports import IdentityVerifier, VerifiedIdentity

GOOGLE_KEYS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
#: Tolerated clock difference between Google and us, in seconds.
LEEWAY_SECONDS = 60
REJECTED = "Google could not confirm who you are. Try signing in again."

#: Returns the public key that signed ``token`` (looked up by its ``kid``).
KeyLookup = Callable[[str], Any]


class GoogleIdTokenVerifier(IdentityVerifier):
    """Verifies ID tokens issued to one OAuth client id."""

    def __init__(self, client_id: str, clock: Clock, keys: KeyLookup | None = None) -> None:
        self.__client_id = client_id
        self.__clock = clock
        self.__keys = keys or google_keys()

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            key = self.__keys(token)
        except jwt.PyJWKClientConnectionError as error:
            raise NetworkFailureError("Google's signing keys could not be fetched.") from error
        except jwt.PyJWTError as error:
            raise InvalidLoginError(REJECTED) from error
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.__client_id,
                issuer=list(ISSUERS),
                # Expiry is checked below against the injected Clock (AGENTS.md: Time).
                options={"verify_exp": False, "require": ["exp", "iat", "sub", "email"]},
            )
        except jwt.PyJWTError as error:
            raise InvalidLoginError(REJECTED) from error
        now = self.__clock.now().timestamp()
        if float(claims["exp"]) + LEEWAY_SECONDS < now:
            raise InvalidLoginError(REJECTED)
        if claims.get("email_verified") is not True:
            raise InvalidLoginError("Google has not verified this email address.")
        return VerifiedIdentity(
            email=str(claims["email"]),
            full_name=str(claims.get("name") or ""),
            hosted_domain=None if claims.get("hd") is None else str(claims["hd"]),
            subject=str(claims["sub"]),
        )


def google_keys() -> KeyLookup:
    """Google's published keys, fetched on first use and cached by PyJWT."""
    client = jwt.PyJWKClient(GOOGLE_KEYS_URL, cache_keys=True, lifespan=3600, timeout=5)

    def lookup(token: str) -> Any:
        return client.get_signing_key_from_jwt(token).key

    return lookup
