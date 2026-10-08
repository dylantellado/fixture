# CLAUDE.md

Guidance for AI coding agents working in this repo.

## Project

Fixture is a Harvard AC215 course project by Dylan Tellado and Will Sherwood. It is an autonomous scheduling assistant for students who are recruiting or building their networks. After the user sends the first email, Fixture handles the back-and-forth through a confirmed meeting and updates the user's calendar on its own, without asking for approval at each step. Users will also be able to text it to ask about their schedule.

**Core goal: trust.** Fixture must never break a rule the user has set, such as moving or booking over a commitment marked as fixed.

**Current thinking:** an AI agent reads and responds to scheduling emails. Separate, predictable logic checks every proposed action against the user's rules before anything changes on the calendar. Models, data, and tools are not decided yet.

## Project status and flexibility

- **Early and exploratory:** the overall goal (a trustworthy, autonomous scheduling assistant) is set. The design, features, data, models, and tools are all open to change.
- **Nothing is final:** that includes existing code, file structure, and past decisions. If a request conflicts with what's already in the repo, follow the request and point out the conflict.
- **Don't lock in on one approach:** for a meaningful design choice, briefly lay out the options and tradeoffs and ask which we want. Don't pick one and build heavily around it.
- **Prefer simple, easy-to-change solutions** so we can pivot without large rewrites.
- **Keep this file current:** if a request changes the project's direction, update CLAUDE.md to match.

Right now every service is a placeholder: each `main.py` only prints a message, no service has dependencies, and there are no tests.

## Current structure

This is the starting layout, not a final architecture. Folders and services may be renamed, merged, split, or removed.

```
docker-compose.yml   runs all services together
.env.example         template for .env (copy it, never commit .env)
data/                local data (git-ignored)
samples/             sample inputs that are safe to commit
secrets/             local credentials (git-ignored)
src/
  ingest/       placeholder
  preprocess/   placeholder
  rag/          placeholder
  api/          placeholder (port 8000 in compose)
  frontend/     placeholder (port 8501 in compose)
```

The service names suggest a rough pipeline (ingest → preprocess → rag → api → frontend), but what each one does hasn't been decided.

Each service under `src/` is currently self-contained, with its own `Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` (3.12), and `main.py`.

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
- **Ask before making major design decisions:** see "Project status and flexibility" above.
