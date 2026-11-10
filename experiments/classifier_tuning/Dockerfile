# Image for one tuning run on Vertex AI (a custom job). Built by cloud/run_vertex_job.sh
# from a folder that mirrors the repo layout:
#   /app/experiments/classifier_tuning/   code + harnesses/ (no tests)
#   /app/docs/data/labeling_rules.md      the rules file the harnesses point to
# Data is not in the image: the job reads it from Cloud Storage (--data-root gs://...),
# copied there by run_vertex_job.sh under its md5, so every run names its exact data.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv
WORKDIR /app/experiments/classifier_tuning
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY experiments/classifier_tuning/pyproject.toml experiments/classifier_tuning/uv.lock \
     experiments/classifier_tuning/.python-version ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim
WORKDIR /app/experiments/classifier_tuning
COPY --from=build /app/experiments/classifier_tuning/.venv ./.venv
COPY . /app/
ENV PATH="/app/experiments/classifier_tuning/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "main.py"]
