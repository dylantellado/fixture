# Fixture classifier image.
#
# Built two ways:
#   - Cloud Run (deploy.sh): the build folder is made by cloud/build_context.sh. It holds
#     only this service's committed code plus the exact docs/data/labeling_rules.md from
#     git, copied in as labeling_rules.md, so the image is self-contained.
#   - docker compose (local): the build folder is src/classifier (no rules file); compose
#     mounts the repo's rules file and sets RULES_PATH=/rules/labeling_rules.md.
# Either way the service logs the rules version and sha256 at startup.

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
# --no-dev: leave out pytest and httpx (tests only).
RUN uv sync --locked --no-dev --no-install-project

# --- Stage 2: the runtime image: Python, the virtualenv and the code (no uv) ----
FROM python:3.12-slim

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# The code (and labeling_rules.md when deploy.sh built the folder). .dockerignore
# keeps tests, docs and deploy scripts out.
COPY . .

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RULES_PATH=/app/labeling_rules.md

# Cloud Run sets $PORT (8080). docker compose doesn't, so the service stays on 8002.
# No access log: Cloud Run already logs every request, and /classify logs its own line.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8002} --no-access-log"]
