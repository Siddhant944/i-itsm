# API image: Python 3.12 + uv, production dependencies only.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN useradd --create-home --uid 10001 itsm
USER itsm
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"
# Migrate, then serve: the schema is always at head before the first request.
# SEED_ON_START=true fills a never-seeded database with the demo data, catching the SLA monitor
# up on that history, and is a no-op afterwards.
# DEMO_RESET_ON_START=true (with APP_ENV=demo) wipes and re-stages the database on every start
# instead, for a demo instance on the x10 clock (P5.5, D-036); it never runs with APP_ENV=prod.
# PORT is set by hosts such as Render; locally and in Compose it stays 8000.
CMD ["sh", "-c", "alembic upgrade head && if [ \"$DEMO_RESET_ON_START\" = \"true\" ]; then python -m app.demo; elif [ \"$SEED_ON_START\" = \"true\" ]; then python -m app.demo --seed-if-empty; fi && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
