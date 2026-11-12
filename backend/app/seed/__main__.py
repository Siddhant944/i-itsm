"""``python -m app.seed`` (behind ``make seed``): seed the database at DATABASE_URL.

``--if-empty`` seeds only a database that has never been seeded, and otherwise touches nothing.
A deployment runs it on every start (SEED_ON_START), so it must never overwrite what an
administrator has configured since, which a plain re-seed of the catalogue would.
"""

import sys

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.security import Argon2PasswordHasher
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork, make_session_factory
from app.seed.runner import already_seeded, seed


def main(argv: list[str] | None = None) -> int:
    only_if_empty = "--if-empty" in (sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(make_session_factory(engine), SystemClock())
        try:
            if only_if_empty and already_seeded(uow):
                print("seed: already seeded; nothing changed")
                return 0
            hasher = Argon2PasswordHasher()
            print(seed(uow, SystemClock(), hash_password=hasher.hash).summary())
        finally:
            uow.close()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
