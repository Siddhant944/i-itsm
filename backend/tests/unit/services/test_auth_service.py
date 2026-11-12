"""Registration, sign-in, lockout and token checks (blueprint §8, D-008).

Every case runs on a FakeClock and the in-memory repositories, so the fifth failure locking the
account and the fifteen minutes passing are both exact rather than approximate.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.core.security import FakePasswordHasher, JwtTokenService
from app.domain.audit import AuditAction, verify_chain
from app.domain.credentials import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS
from app.domain.errors import (
    InvalidLoginError,
    InvalidUserInputError,
    NetworkFailureError,
    UnauthorizedOperationError,
)
from app.domain.permissions import Permission, Role
from app.domain.ports import IdentityVerifier, VerifiedIdentity
from app.domain.users import UserFactory
from app.domain.value_objects import EmailAddress
from app.repositories.memory import InMemoryUnitOfWork
from app.services.auth_service import AuthPolicy, AuthService

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SECRET = "a-test-signing-secret-of-adequate-length"
GOOD_PASSWORD = "correct horse battery"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork()


@pytest.fixture
def auth(uow: InMemoryUnitOfWork, clock: FakeClock) -> AuthService:
    return AuthService(
        uow, FakePasswordHasher(), JwtTokenService(SECRET, timedelta(minutes=30)), clock
    )


def register(auth: AuthService, email: str = "devika@campus.edu") -> None:
    auth.register(email, "Devika Rao", GOOD_PASSWORD)


def actions(uow: InMemoryUnitOfWork) -> list[AuditAction]:
    return [record.action for record in uow.audit.records(limit=100)]


# ---------------------------------------------------------------- registration
def test_self_registration_creates_an_employee(auth: AuthService, uow: InMemoryUnitOfWork) -> None:
    """Blueprint §8: a self-registered account is an Employee; admins assign other roles."""
    user = auth.register("devika@campus.edu", "  Devika Rao ", GOOD_PASSWORD)
    assert user.role is Role.EMPLOYEE
    assert user.full_name == "Devika Rao"
    assert str(user.email) == "devika@campus.edu"
    assert uow.credentials.get(user.id).has_password is True
    assert AuditAction.USER_REGISTERED in actions(uow)


def test_registration_refuses_a_duplicate_email(auth: AuthService) -> None:
    register(auth)
    with pytest.raises(InvalidUserInputError) as caught:
        auth.register("DEVIKA@campus.edu", "Someone Else", GOOD_PASSWORD)
    assert "email" in caught.value.field_errors


def test_registration_refuses_a_weak_password_and_a_bad_email(auth: AuthService) -> None:
    with pytest.raises(InvalidUserInputError) as weak:
        auth.register("new@campus.edu", "New Person", "short")
    assert "password" in weak.value.field_errors
    with pytest.raises(InvalidUserInputError) as bad:
        auth.register("not-an-email", "New Person", GOOD_PASSWORD)
    assert "email" in bad.value.field_errors


def test_registration_honours_allowed_domains(uow: InMemoryUnitOfWork, clock: FakeClock) -> None:
    """D-008: open to any email unless ALLOWED_EMAIL_DOMAINS is set."""
    restricted = AuthService(
        uow,
        FakePasswordHasher(),
        JwtTokenService(SECRET, timedelta(minutes=30)),
        clock,
        AuthPolicy(allowed_email_domains=("campus.edu",)),
    )
    assert restricted.register("ok@campus.edu", "Ok Person", GOOD_PASSWORD).id > 0
    with pytest.raises(InvalidUserInputError):
        restricted.register("nope@gmail.com", "Outside Person", GOOD_PASSWORD)


def test_registered_users_get_distinct_ids(auth: AuthService) -> None:
    first = auth.register("one@campus.edu", "One Person", GOOD_PASSWORD)
    second = auth.register("two@campus.edu", "Two Person", GOOD_PASSWORD)
    assert first.id != second.id


# ---------------------------------------------------------------- sign-in
def test_a_correct_password_returns_a_usable_token(
    auth: AuthService, uow: InMemoryUnitOfWork
) -> None:
    register(auth)
    issued = auth.login("DEVIKA@campus.edu", GOOD_PASSWORD)
    assert issued.role is Role.EMPLOYEE
    assert issued.portal == "employee"
    assert issued.expires_in_seconds == 1800
    assert auth.authenticate(issued.token).id == issued.user_id
    assert AuditAction.LOGIN_SUCCEEDED in actions(uow)
    assert uow.credentials.get(issued.user_id).last_login_at == NOW


def test_a_wrong_password_is_refused_and_counted(
    auth: AuthService, uow: InMemoryUnitOfWork
) -> None:
    register(auth)
    with pytest.raises(InvalidLoginError):
        auth.login("devika@campus.edu", "wrong password")
    assert uow.credentials.get(1).failed_attempts == 1
    assert actions(uow).count(AuditAction.LOGIN_FAILED) == 1


def test_every_kind_of_sign_in_failure_looks_the_same(
    auth: AuthService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """D-019: the endpoint must not tell an attacker which addresses have accounts.

    Unknown email, wrong password, locked account and deactivated account all answer
    identically; what actually happened is recorded in the audit trail instead.
    """
    register(auth, "devika@campus.edu")
    register(auth, "blocked@campus.edu")
    blocked = uow.users.get(2)
    blocked.deactivate()
    uow.users.save(blocked)

    messages = set()
    for email, password in (
        ("nobody@campus.edu", GOOD_PASSWORD),  # no such account
        ("devika@campus.edu", "wrong password"),  # wrong password
        ("blocked@campus.edu", GOOD_PASSWORD),  # deactivated
        ("not-an-email", GOOD_PASSWORD),  # malformed
    ):
        with pytest.raises(InvalidLoginError) as refused:
            auth.login(email, password)
        messages.add(refused.value.message)

    # And once the account is locked, that answers the same way too.
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")
    with pytest.raises(InvalidLoginError) as locked:
        auth.login("devika@campus.edu", GOOD_PASSWORD)
    messages.add(locked.value.message)

    assert len(messages) == 1, f"these answers differ: {messages}"
    assert AuditAction.ACCOUNT_LOCKED in actions(uow)


def test_a_malformed_email_is_a_failed_sign_in(auth: AuthService) -> None:
    with pytest.raises(InvalidLoginError):
        auth.login("not-an-email", GOOD_PASSWORD)


def test_a_deactivated_account_cannot_sign_in(auth: AuthService, uow: InMemoryUnitOfWork) -> None:
    user = auth.register("devika@campus.edu", "Devika Rao", GOOD_PASSWORD)
    user.deactivate()
    uow.users.save(user)
    with pytest.raises(InvalidLoginError) as refused:
        auth.login("devika@campus.edu", GOOD_PASSWORD)
    # D-019: indistinguishable from a wrong password; the reason is in the audit trail.
    assert "deactivated" not in refused.value.message
    reasons = [
        record.details.get("reason")
        for record in uow.audit.records(limit=100)
        if record.action is AuditAction.LOGIN_FAILED
    ]
    assert "inactive" in reasons


def test_an_account_with_no_password_cannot_sign_in(
    auth: AuthService, uow: InMemoryUnitOfWork
) -> None:
    """Seeded staff accounts exist before anyone sets a password."""
    uow.users.add(
        UserFactory.create(Role.TECHNICIAN, user_id=50, email="t@campus.edu", full_name="T")
    )
    with pytest.raises(InvalidLoginError):
        auth.login("t@campus.edu", GOOD_PASSWORD)


# ---------------------------------------------------------------- lockout (§8)
def test_the_fifth_failure_locks_the_account_and_is_audited(
    auth: AuthService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    register(auth)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")

    assert AuditAction.ACCOUNT_LOCKED in actions(uow)
    locked_record = next(
        record
        for record in uow.audit.records(limit=100)
        if record.action is AuditAction.ACCOUNT_LOCKED
    )
    assert locked_record.details["attempts"] == MAX_FAILED_ATTEMPTS
    assert locked_record.details["locked_for_minutes"] == 15

    # Even the right password is refused while the lock holds, and says nothing about why.
    with pytest.raises(InvalidLoginError) as while_locked:
        auth.login("devika@campus.edu", GOOD_PASSWORD)
    assert while_locked.value.message == InvalidLoginError().message
    clock.advance(LOCKOUT_DURATION - timedelta(seconds=1))
    with pytest.raises(InvalidLoginError):
        auth.login("devika@campus.edu", GOOD_PASSWORD)


def test_fifteen_minutes_later_the_account_unlocks(auth: AuthService, clock: FakeClock) -> None:
    register(auth)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")

    clock.advance(LOCKOUT_DURATION)
    issued = auth.login("devika@campus.edu", GOOD_PASSWORD)
    assert issued.user_id > 0


def test_a_successful_sign_in_resets_the_count(auth: AuthService, uow: InMemoryUnitOfWork) -> None:
    register(auth)
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")
    issued = auth.login("devika@campus.edu", GOOD_PASSWORD)
    assert uow.credentials.get(issued.user_id).failed_attempts == 0

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")


# ---------------------------------------------------------------- tokens and roles
def test_an_expired_or_forged_token_is_refused(auth: AuthService, clock: FakeClock) -> None:
    register(auth)
    token = auth.login("devika@campus.edu", GOOD_PASSWORD).token
    clock.advance(timedelta(minutes=30))
    with pytest.raises(InvalidLoginError):
        auth.authenticate(token)
    with pytest.raises(InvalidLoginError):
        auth.authenticate("not-a-token")


def test_a_token_for_a_deleted_or_deactivated_user_is_refused(
    auth: AuthService, uow: InMemoryUnitOfWork
) -> None:
    user = auth.register("devika@campus.edu", "Devika Rao", GOOD_PASSWORD)
    token = auth.login("devika@campus.edu", GOOD_PASSWORD).token
    user.deactivate()
    uow.users.save(user)
    with pytest.raises(InvalidLoginError):
        auth.authenticate(token)


def test_a_token_whose_role_has_changed_is_refused(
    auth: AuthService, uow: InMemoryUnitOfWork
) -> None:
    """An admin promoting someone must not let their old token keep the old role."""
    user = auth.register("devika@campus.edu", "Devika Rao", GOOD_PASSWORD)
    token = auth.login("devika@campus.edu", GOOD_PASSWORD).token
    promoted = UserFactory.create(
        Role.TECHNICIAN, user_id=user.id, email=str(user.email), full_name=user.full_name
    )
    uow.users.save(promoted)
    with pytest.raises(InvalidLoginError):
        auth.authenticate(token)


def test_permission_checks_refuse_with_what_the_audit_needs(auth: AuthService) -> None:
    """The API audits the refusal after rolling the request back (issue #8)."""
    user = auth.register("devika@campus.edu", "Devika Rao", GOOD_PASSWORD)
    auth.require(user, Permission.INCIDENT_CREATE)  # allowed: no exception

    with pytest.raises(UnauthorizedOperationError) as refused:
        auth.require(user, Permission.AUDIT_VERIFY)
    assert refused.value.actor_id == user.id
    assert refused.value.audit_details["permission"] == Permission.AUDIT_VERIFY.value
    assert "permission" not in refused.value.details  # never sent to the caller


def test_the_permission_list_matches_the_role(auth: AuthService) -> None:
    employee = auth.register("devika@campus.edu", "Devika Rao", GOOD_PASSWORD)
    granted = AuthService.permissions(employee)
    assert Permission.INCIDENT_CREATE.value in granted
    assert Permission.INCIDENT_VIEW_ALL.value not in granted
    assert granted == sorted(granted)


def test_every_audited_sign_in_keeps_the_chain_intact(
    auth: AuthService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    register(auth)
    for _ in range(3):
        with pytest.raises(InvalidLoginError):
            auth.login("devika@campus.edu", "wrong password")
        clock.advance(timedelta(seconds=30))
    auth.login("devika@campus.edu", GOOD_PASSWORD)
    records = uow.audit.records(limit=100)
    assert len(records) >= 5
    assert verify_chain(records).intact is True


# ---------------------------------------------------------------- Google Sign-In (P4.10)
class FakeGoogle(IdentityVerifier):
    """Says whatever the test tells it; the real token checks are the adapter's own tests."""

    def __init__(self, identity: VerifiedIdentity | None = None) -> None:
        self.identity = identity

    def verify(self, token: str) -> VerifiedIdentity:
        if self.identity is None:
            raise InvalidLoginError("bad token")
        return self.identity


def campus(
    email: str = "asha@campus.edu", sub: str = "g-1", hd: str | None = "campus.edu"
) -> VerifiedIdentity:
    return VerifiedIdentity(email=email, full_name="Asha Rao", hosted_domain=hd, subject=sub)


def google_auth(
    uow: InMemoryUnitOfWork, clock: FakeClock, google: FakeGoogle, domain: str = "campus.edu"
) -> AuthService:
    return AuthService(
        uow,
        FakePasswordHasher(),
        JwtTokenService(SECRET, timedelta(minutes=30)),
        clock,
        AuthPolicy(google_hosted_domain=domain),
        identity=google,
    )


def test_the_first_google_sign_in_creates_an_employee_and_the_next_finds_it(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    auth = google_auth(uow, clock, FakeGoogle(campus()))
    first = auth.google_sign_in("token")
    user = uow.users.get(first.user_id)
    assert (user.role, user.full_name, str(user.email)) == (
        Role.EMPLOYEE,
        "Asha Rao",
        "asha@campus.edu",
    )
    assert uow.credentials.get(user.id).google_subject == "g-1"
    assert uow.credentials.get(user.id).has_password is False  # Google only, no password
    assert auth.google_sign_in("token").user_id == first.user_id
    assert actions(uow).count(AuditAction.USER_REGISTERED) == 1
    assert actions(uow).count(AuditAction.LOGIN_SUCCEEDED) == 2


def test_D008_a_google_account_outside_the_campus_domain_is_refused_and_audited(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    for hd in ("gmail.com", None, "campus.edu.evil.com"):
        auth = google_auth(uow, clock, FakeGoogle(campus(email="x@gmail.com", hd=hd)))
        with pytest.raises(InvalidLoginError) as refused:
            auth.google_sign_in("token")
        assert "campus.edu" in refused.value.message
    assert uow.users.find_by_email(EmailAddress("x@gmail.com")) is None
    assert actions(uow).count(AuditAction.LOGIN_FAILED) == 3


def test_an_existing_password_account_is_linked_but_never_to_a_second_google_account(
    auth: AuthService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    register(auth, "asha@campus.edu")
    linked = google_auth(uow, clock, FakeGoogle(campus(sub="g-1"))).google_sign_in("token")
    assert uow.credentials.get(linked.user_id).google_subject == "g-1"

    impostor = google_auth(uow, clock, FakeGoogle(campus(sub="g-2")))
    with pytest.raises(InvalidLoginError):
        impostor.google_sign_in("token")
    assert uow.credentials.get(linked.user_id).google_subject == "g-1"


def test_a_deactivated_account_cannot_sign_in_with_google(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    auth = google_auth(uow, clock, FakeGoogle(campus()))
    user = uow.users.get(auth.google_sign_in("token").user_id)
    user.deactivate()
    uow.users.save(user)
    with pytest.raises(InvalidLoginError):
        auth.google_sign_in("token")


def test_google_sign_in_is_unavailable_until_both_settings_exist(
    uow: InMemoryUnitOfWork, clock: FakeClock, auth: AuthService
) -> None:
    with pytest.raises(NetworkFailureError):
        auth.google_sign_in("token")  # no verifier
    with pytest.raises(NetworkFailureError):
        google_auth(uow, clock, FakeGoogle(campus()), domain="").google_sign_in("token")
    with pytest.raises(InvalidLoginError):
        google_auth(uow, clock, FakeGoogle(None)).google_sign_in("token")  # a bad token


def test_BR01_a_password_someone_else_registered_stops_working_once_google_proves_the_owner(
    auth: AuthService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """P4 review: registering asha@ with a password proves nothing about owning the address.
    When the real Asha signs in with Google, the squatter's password must not keep working."""
    register(auth, "asha@campus.edu")  # anyone could have done this
    linked = google_auth(uow, clock, FakeGoogle(campus())).google_sign_in("token")
    with pytest.raises(InvalidLoginError):
        auth.login("asha@campus.edu", GOOD_PASSWORD)
    assert uow.credentials.get(linked.user_id).has_password is False
    assert AuditAction.PASSWORD_CHANGED in actions(uow)
