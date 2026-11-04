"""``python -m app.seed`` (behind ``make seed``): seed the database at DATABASE_URL."""

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork, make_session_factory
from app.seed.runner import seed


def main() -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), SystemClock())
        try:
            print(seed(uow, SystemClock()).summary())
        finally:
            uow.close()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
