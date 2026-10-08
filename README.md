# fixture

Multi-service Python project orchestrated with Docker Compose.

## Layout

```
data/        local data (git-ignored)
samples/     sample inputs checked into the repo
secrets/     local credentials (git-ignored)
src/
  ingest/      data ingestion
  preprocess/  cleaning and transformation
  rag/         retrieval-augmented generation
  api/         HTTP API
  frontend/    user interface
```

Each service under `src/` is its own [uv](https://docs.astral.sh/uv/) project with a `pyproject.toml`, `uv.lock`, `Dockerfile`, and `main.py`.

## Getting started

```sh
cp .env.example .env
docker compose up --build
```

To work on a single service locally:

```sh
cd src/api
uv run main.py
```

Add dependencies with `uv add <package>` from inside the service directory.
