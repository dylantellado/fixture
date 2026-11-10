# Fixture drafter image (Cloud Run-ready; not deployed yet).
#
# The image holds only this service's code and rules/default_rules.json. It reads
# no files from the rest of the repo, so the build folder is just src/drafter.

# --- Stage 1: install the locked dependencies with uv -------------------------
FROM python:3.12-slim AS build

# Pinned uv version, so builds are repeatable.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version ./
# --locked: fail if uv.lock is out of date with pyproject.toml.
# --no-dev: leave out pytest (tests only).
RUN uv sync --locked --no-dev --no-install-project

# --- Stage 2: the runtime image: Python, the virtualenv and the code (no uv) ----
FROM python:3.12-slim

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# The code and rules/default_rules.json. .dockerignore keeps tests, scenarios and docs out.
COPY . .

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Cloud Run sets $PORT (8080). docker compose doesn't, so the service stays on 8003.
# No access log: Cloud Run already logs every request, and /draft logs its own line.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8003} --no-access-log"]
