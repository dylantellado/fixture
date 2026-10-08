# CLAUDE.md

Guidance for AI coding agents working in this repo.

## Project

Fixture is a Harvard AC215 course project by Dylan Tellado and Will Sherwood. It is an autonomous scheduling assistant for students who are recruiting or building their networks. After the user sends the first email, Fixture handles the back-and-forth through a confirmed meeting and updates the user's calendar on its own, without asking for approval at each step. Users will also be able to text it to ask about their schedule.

**Core goal: trust.** Fixture must never break a rule the user has set, such as moving or booking over a commitment marked as fixed.

**Approach:** an AI agent reads and responds to scheduling emails. Separate, deterministic logic checks every proposed action against the user's rules before anything changes on the calendar. Models, data, and tools are not decided yet.

## Status

Early stage. Every service is a placeholder: each `main.py` only prints a message, and no service has dependencies yet. There are no tests yet.

## Structure

```
docker-compose.yml   runs all services together
.env.example         template for .env (copy it, never commit .env)
data/                local data (git-ignored)
samples/             sample inputs that are safe to commit
secrets/             local credentials (git-ignored)
src/
  ingest/       bringing data into the system
  preprocess/   cleaning and transforming data
  rag/          retrieval-augmented generation
  api/          HTTP API (port 8000 in compose)
  frontend/     user interface (port 8501 in compose)
```

Each service under `src/` is self-contained, with its own `Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` (3.12), and `main.py`. Don't import code across services. Add dependencies to the service that needs them.

## Commands

Whole stack (from the repo root):

```sh
cp .env.example .env
docker compose up --build
```

Single service (from its folder, e.g. `src/api`):

```sh
uv run main.py
uv add <package>   # adds a dependency and updates uv.lock
```

## Working rules

- **Never commit secrets:** that includes `.env`, credentials, API keys, tokens, and personal email or calendar data. Use fake data in `samples/`.
- **Keep code simple, readable, and commented:** both team members must be able to explain any part of it.
- **Add tests for new features.**
- **Work on a feature branch:** merge into `main` only through a pull request.
- **Ask before making major design decisions:** that includes picking models, frameworks, data stores, or service boundaries, because the implementation isn't settled.
