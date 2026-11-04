"""Composition root: builds the FastAPI app and wires implementations to interfaces.

This is the only module allowed to import every layer. Everything built once — the engine, the
clock, the password hasher, the token service — is put on ``app.state.services``, where the
request dependencies in ``app.api.deps`` pick it up. Run with
``uvicorn app.main:create_app --factory``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.adapters.smtp_email import EmailSettings, email_sender_for
from app.api import health
from app.api.deps import Services
from app.api.errors import register_error_handlers
from app.api.routers import auth as auth_router
from app.api.routers import catalogue as catalogue_router
from app.api.routers import dev as dev_router
from app.api.routers import incidents as incidents_router
from app.api.routers import notifications as notifications_router
from app.api.routers import reports as reports_router
from app.api.routers import violations as violations_router
from app.core.clock import AcceleratedClock, Clock, FakeClock, SystemClock
from app.core.config import ClockMode, Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import Argon2PasswordHasher, JwtTokenService
from app.domain.errors import ITSMError
from app.domain.repositories import UnitOfWork
from app.domain.rule_advisor import RuleBasedAdvisor
from app.repositories.database import make_engine, ping
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork, make_session_factory
from app.services.auth_service import AuthPolicy
from app.services.notifications import EmailChannel, default_factory
from app.services.notifications.service import NotificationService
from app.services.scheduler import MonitorScheduler
from app.services.sla_monitor import SLAMonitor, TickReport


def make_clock(settings: Settings) -> Clock:
    """The clock every service reads (blueprint §5.2; ×10 in the demo, D-003)."""
    if settings.clock_mode is ClockMode.ACCELERATED:
        return AcceleratedClock(settings.clock_acceleration)
    if settings.clock_mode is ClockMode.FAKE:
        # D-009: stands still until /dev/clock moves it, for Playwright and the demo.
        return FakeClock(SystemClock().now())
    return SystemClock()


def email_settings(settings: Settings) -> EmailSettings:
    """The SMTP fields only; an empty SMTP_HOST means the console fallback (§5.4)."""
    return EmailSettings(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=(settings.smtp_password.get_secret_value() if settings.smtp_password else ""),
        sender=settings.smtp_from,
        starttls=settings.smtp_starttls,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application for the given settings (defaults to the environment)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings.database_url)
    sessions = make_session_factory(engine)
    clock = make_clock(settings)

    @asynccontextmanager
    async def lifespan(built: FastAPI) -> AsyncIterator[None]:
        monitor: MonitorScheduler | None = getattr(built.state, "scheduler", None)
        if monitor is not None:
            monitor.start()
        yield
        if monitor is not None:
            monitor.stop()
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # Our own handler owns 422 (blueprint §8), so the generated client sees one error shape.
        responses={422: {"description": "Validation error"}},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.services = Services(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(sessions, clock),
        clock=clock,
        hasher=Argon2PasswordHasher(),
        tokens=JwtTokenService(
            settings.jwt_secret.get_secret_value(),
            timedelta(minutes=settings.jwt_access_ttl_minutes),
        ),
        policy=AuthPolicy(allowed_email_domains=tuple(settings.allowed_email_domains)),
        email=email_sender_for(email_settings(settings)),
        # §6.1: Gemini arrives in P4.4 with this rule-based advisor as its fallback.
        advisor=RuleBasedAdvisor(),
    )
    app.state.db_probe = lambda: ping(engine)
    app.state.settings = settings
    app.dependency_overrides[get_settings] = lambda: settings

    scheduler = _schedule_monitor(app, settings, sessions, clock)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(catalogue_router.router)
    app.include_router(incidents_router.router)
    app.include_router(notifications_router.router)
    app.include_router(reports_router.router)
    app.include_router(violations_router.router)
    if settings.clock_control_enabled:
        # D-009: controlling time is for the test and demo environments only.
        app.include_router(dev_router.router)
    app.state.scheduler = scheduler
    return app


def _schedule_monitor(
    app: FastAPI,
    settings: Settings,
    sessions: sessionmaker[Session],
    clock: Clock,
) -> MonitorScheduler | None:
    """The background SLA monitor, unless SLA_TICK_SECONDS is 0 (D-003).

    Each tick gets its own Unit of Work and its own notification channels, exactly as a request
    would, and closes them afterwards.
    """
    if settings.sla_tick_seconds <= 0:
        return None

    email = email_sender_for(email_settings(settings))

    def tick() -> TickReport:
        uow = SqlAlchemyUnitOfWork(sessions, clock)
        try:
            channels = default_factory(
                email=EmailChannel(email, lambda user_id: _address(uow, user_id))
            )
            notifications = NotificationService(uow, clock, channels)
            return SLAMonitor(uow, clock, notify=notifications.notify).tick()
        finally:
            uow.close()

    return MonitorScheduler(tick, clock, timedelta(seconds=settings.sla_tick_seconds))


def _address(uow: UnitOfWork, user_id: int) -> str | None:
    try:
        return str(uow.users.get(user_id).email)
    except ITSMError:
        return None
