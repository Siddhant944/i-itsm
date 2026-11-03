"""Composition root: builds the FastAPI app and wires implementations to interfaces.

This is the only module allowed to import every layer. Run with
``uvicorn app.main:create_app --factory``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.repositories.database import make_engine, ping


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application for the given settings (defaults to the environment)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.db_probe = lambda: ping(engine)
    app.dependency_overrides[get_settings] = lambda: settings

    app.include_router(health.router)
    return app
