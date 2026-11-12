"""Registration, sign-in and "who is this request" (blueprint §8, D-008).

Every outcome is audited inside the same transaction as the change it describes: a successful
sign-in, a failed one, a lockout, a registration, a refused authorisation. The service owns the
hasher and the token service, so the domain stays free of both, and it reads time from the
injected Clock so lockouts and token expiry are testable.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.clock import Clock
from app.core.security import (
    InvalidTokenError,
    PasswordHasher,
    TokenService,
    password_problem,
)
from app.domain.audit import AuditAction
from app.domain.credentials import MAX_FAILED_ATTEMPTS, Credentials
from app.domain.errors import (
    InvalidLoginError,
    InvalidUserInputError,
    NetworkFailureError,
    UnauthorizedOperationError,
)
from app.domain.permissions import Permission, Role, permissions_for, portal_for
from app.domain.ports import IdentityVerifier
from app.domain.repositories import UnitOfWork
from app.domain.users import User, UserFactory
from app.domain.value_objects import EmailAddress
from app.services.audit import AuditService

#: Self-registration creates an Employee; admins assign every other role (blueprint §8).
SELF_REGISTRATION_ROLE = Role.EMPLOYEE


@dataclass(frozen=True, slots=True)
class AccessToken:
    """What a successful sign-in hands back."""

    token: str
    expires_in_seconds: int
    user_id: int
    role: Role
    portal: str
    full_name: str


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    """Settings the service needs, passed in so it never reads configuration itself."""

    allowed_email_domains: tuple[str, ...] = ()
    #: D-008: Google Sign-In is accepted only for this Workspace domain (the ``hd`` claim).
    google_hosted_domain: str = ""

    def permits(self, email: EmailAddress) -> bool:
        """D-008: any email, unless the deployment limits the domains."""
        if not self.allowed_email_domains:
            return True
        return email.domain in {domain.strip().lower() for domain in self.allowed_email_domains}


class AuthService:
    """The only place that turns a password or a token into a user."""

    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        tokens: TokenService,
        clock: Clock,
        policy: AuthPolicy | None = None,
        identity: IdentityVerifier | None = None,
    ) -> None:
        self.__uow = uow
        self.__identity = identity
        self.__hasher = hasher
        self.__tokens = tokens
        self.__clock = clock
        self.__policy = policy or AuthPolicy()
        self.__audit = AuditService(uow.audit, clock)

    # ------------------------------------------------------------ the caller's own profile
    def link_telegram(self, user: User, chat_id: str) -> User:
        """Send this user's P1/P2 alerts to a Telegram chat (§5.4, P4.9); audited."""
        user.link_telegram(chat_id)
        return self.__save_profile(user, {"telegram": "linked"})

    def unlink_telegram(self, user: User) -> User:
        user.unlink_telegram()
        return self.__save_profile(user, {"telegram": "unlinked"})

    def __save_profile(self, user: User, details: dict[str, object]) -> User:
        self.__uow.users.save(user)
        self.__audit.record(
            AuditAction.USER_MANAGED, actor_id=user.id, details={"user_id": user.id, **details}
        )
        self.__uow.commit()
        return user

    # ------------------------------------------------------------ registration
    def register(self, email: str, full_name: str, password: str) -> User:
        """Create an Employee account. Commits, so the caller can sign in straight away."""
        address = self.__checked_email(email)
        problem = password_problem(password)
        if problem is not None:
            raise InvalidUserInputError({"password": problem})
        if self.__uow.users.find_by_email(address) is not None:
            raise InvalidUserInputError({"email": "An account with this email already exists."})

        user = UserFactory.create(
            SELF_REGISTRATION_ROLE,
            user_id=self.__next_user_id(),
            email=str(address),
            full_name=full_name,
        )
        self.__uow.users.add(user)
        credentials = self.__uow.credentials.get(user.id)
        credentials.set_password_hash(self.__hasher.hash(password))
        self.__uow.credentials.save(credentials)
        self.__audit.record(
            AuditAction.USER_REGISTERED,
            actor_id=user.id,
            details={"email": str(address), "role": user.role.value},
        )
        self.__uow.commit()
        return user

    # ------------------------------------------------------------ Google Sign-In (P4.10)
    def google_sign_in(self, credential: str) -> AccessToken:
        """Sign in with a Google ID token; the first sign-in creates an Employee (D-008).

        The token's signature, audience, issuer, expiry and verified email are checked by the
        verifier; here the ``hd`` claim must be the campus domain, and an account already
        linked to another Google account is refused.
        """
        domain = self.__policy.google_hosted_domain.strip().lower()
        if self.__identity is None or not domain:
            raise NetworkFailureError("Google Sign-In is not set up on this deployment.")
        identity = self.__identity.verify(credential)
        if (identity.hosted_domain or "").lower() != domain:
            self.__audit.record(
                AuditAction.LOGIN_FAILED,
                details={
                    "method": "google",
                    "reason": "hosted domain",
                    "hosted_domain": identity.hosted_domain,
                },
            )
            self.__uow.commit()
            raise InvalidLoginError(f"Sign in with your {domain} Google account.")

        address = EmailAddress(identity.email)
        credentials = self.__uow.credentials.find_by_email(address)
        if credentials is None:
            user = UserFactory.create(
                SELF_REGISTRATION_ROLE,
                user_id=self.__next_user_id(),
                email=str(address),
                full_name=identity.full_name.strip() or str(address).split("@", 1)[0],
            )
            self.__uow.users.add(user)
            credentials = self.__uow.credentials.get(user.id)
            self.__audit.record(
                AuditAction.USER_REGISTERED,
                actor_id=user.id,
                details={"email": str(address), "role": user.role.value, "method": "google"},
            )
        else:
            user = self.__uow.users.get(credentials.user_id)

        if not credentials.accepts_google(identity.subject) or not user.active:
            reason = "inactive" if user.active is False else "another Google account"
            self.__audit.record(
                AuditAction.LOGIN_FAILED,
                actor_id=user.id,
                details={"method": "google", "reason": reason},
            )
            self.__uow.commit()
            raise InvalidLoginError()

        if credentials.google_subject is None and credentials.has_password:
            # Registering a password never proved the email belonged to whoever chose it;
            # Google has just proved it does belong to this person. A password set by someone
            # else would otherwise keep working alongside theirs (P4 review), so it goes.
            credentials.drop_password()
            self.__audit.record(
                AuditAction.PASSWORD_CHANGED,
                actor_id=user.id,
                details={"reason": "dropped when the account was linked to Google"},
            )
        credentials.link_google(identity.subject)
        credentials.record_success(self.__clock.now())
        self.__uow.credentials.save(credentials)
        self.__audit.record(
            AuditAction.LOGIN_SUCCEEDED, actor_id=user.id, details={"method": "google"}
        )
        self.__uow.commit()
        return self.__token_for(user)

    # ------------------------------------------------------------ sign-in
    def login(self, email: str, password: str) -> AccessToken:
        """Sign in, or raise InvalidLoginError. Commits either way, so failures are counted.

        Every failure gives the same answer — unknown email, wrong password, locked account,
        deactivated account — so the endpoint cannot be used to discover which addresses have
        accounts (D-019). What actually happened goes to the audit trail instead.
        """
        address = self.__safe_email(email)
        credentials = None if address is None else self.__uow.credentials.find_by_email(address)
        if credentials is None:
            # No account: audited, and answered exactly like every other failure so the
            # response cannot reveal which emails exist (D-019).
            self.__audit.record(AuditAction.LOGIN_FAILED, details={"email": email[:255]})
            self.__uow.commit()
            raise InvalidLoginError()

        user = self.__uow.users.get(credentials.user_id)
        now = self.__clock.now()
        if credentials.is_locked(now):
            # The same answer as a wrong password: saying "locked, try again in 12 minutes"
            # would tell an attacker that this address has an account (D-019). The lockout and
            # its remaining time are in the audit trail, where an admin can see them.
            self.__fail(credentials, user.id, locked=True)
            raise InvalidLoginError()

        if not credentials.has_password or not self.__hasher.verify(
            password, credentials.password_hash or ""
        ):
            just_locked = credentials.record_failure(now)
            self.__uow.credentials.save(credentials)
            self.__fail(credentials, user.id, locked=just_locked)
            raise InvalidLoginError()

        if not user.active:
            # Also indistinguishable from a wrong password (D-019); the reason is audited.
            self.__audit.record(
                AuditAction.LOGIN_FAILED, actor_id=user.id, details={"reason": "inactive"}
            )
            self.__uow.commit()
            raise InvalidLoginError()

        credentials.record_success(now)
        self.__uow.credentials.save(credentials)
        self.__audit.record(AuditAction.LOGIN_SUCCEEDED, actor_id=user.id)
        self.__uow.commit()
        return self.__token_for(user)

    def authenticate(self, token: str) -> User:
        """The user a bearer token stands for, or raise InvalidLoginError (HTTP 401)."""
        try:
            claims = self.__tokens.read(token, self.__clock.now())
        except InvalidTokenError as error:
            raise InvalidLoginError("Sign in again.") from error
        try:
            user = self.__uow.users.get(claims.user_id)
        except Exception as error:
            raise InvalidLoginError("Sign in again.") from error
        if not user.active or user.role.value != claims.role:
            # A deactivated account, or a role changed since the token was issued.
            raise InvalidLoginError("Sign in again.")
        return user

    # ------------------------------------------------------------ authorisation
    def require(self, user: User, permission: Permission) -> None:
        """Raise UnauthorizedOperationError (HTTP 403) unless the role grants ``permission``."""
        if user.can(permission):
            return
        self.__audit.record(
            AuditAction.UNAUTHORIZED_ATTEMPT,
            actor_id=user.id,
            details={"permission": permission.value, "role": user.role.value},
        )
        raise UnauthorizedOperationError(f"Your role may not {permission.value}.")

    @staticmethod
    def permissions(user: User) -> Sequence[str]:
        """What the frontend may show, after the server has already decided what it may do."""
        return sorted(permission.value for permission in permissions_for(user.role))

    # ------------------------------------------------------------ internals
    def __token_for(self, user: User) -> AccessToken:
        token = self.__tokens.issue(user.id, user.role.value, self.__clock.now())
        claims = self.__tokens.read(token, self.__clock.now())
        return AccessToken(
            token=token,
            expires_in_seconds=int((claims.expires_at - claims.issued_at).total_seconds()),
            user_id=user.id,
            role=user.role,
            portal=portal_for(user.role).value,
            full_name=user.full_name,
        )

    def __fail(self, credentials: Credentials, user_id: int, *, locked: bool) -> None:
        """Audit the failure, and the lockout when this is one, then commit the counters."""
        self.__audit.record(
            AuditAction.LOGIN_FAILED,
            actor_id=user_id,
            details={"attempts": credentials.failed_attempts},
        )
        if locked:
            minutes = max(1, round(credentials.locked_for(self.__clock.now()).total_seconds() / 60))
            self.__audit.record(
                AuditAction.ACCOUNT_LOCKED,
                actor_id=user_id,
                details={"attempts": MAX_FAILED_ATTEMPTS, "locked_for_minutes": minutes},
            )
        self.__uow.commit()

    def __checked_email(self, email: str) -> EmailAddress:
        address = EmailAddress(email)
        if not self.__policy.permits(address):
            raise InvalidUserInputError({"email": "Use your campus email address."})
        return address

    def __safe_email(self, email: str) -> EmailAddress | None:
        """A malformed email is a failed sign-in, not a validation error on the login form."""
        try:
            return EmailAddress(email)
        except InvalidUserInputError:
            return None

    def __next_user_id(self) -> int:
        return self.__uow.users.next_id()
