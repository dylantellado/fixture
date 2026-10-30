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

**What exists so far:** a Google connection proof of concept and the Milestone 2 search pipeline on fake data. `src/ingest` has a command-line Calendar check, and `src/frontend` has a small web app that reads Calendar and Gmail, plus a "Search past threads" page over the demo mailboxes. Everything is read-only; nothing writes to a calendar or sends email yet. `ingest` and `preprocess` are working one-shot jobs over a generated, fictional email corpus of 4 users (see `docs/data/corpus_notes.md`; plan in `docs/data/generation/`); `rag` indexes each user's messages into their own ChromaDB collection; `api` answers `GET /health`, `GET /users`, and `POST /search`, which searches one user's collection only.

## Milestone 2

**Scope:** a searchable, per-user email pipeline on fake data. Generated multi-user scheduling emails flow through `ingest` → `preprocess` → `rag`, which indexes each user's messages in ChromaDB. The `api` searches one user's messages at a time, and the frontend gets a search page.

**The contract:** the "Data contract" section of `README.md` is the source of truth for file paths, the message schema, labels, id rules, the vector database layout, and the API. Read it before working on any service. Don't change it without telling the other person, and update it in the same PR as the change.

**Ownership:**
- **Will:** data generation, `src/ingest`, `src/preprocess`, DVC, labels, test scenarios
- **Dylan:** `src/rag`, `src/api`, the frontend search page, the `chromadb` service, the mockup
- **Both:** `docker-compose.yml` (each edits only their own services), `README.md`, `docs/` and evidence

Will and Dylan build in parallel with separate Claude Code sessions. Stay inside your owner's area; if a change is needed in the other person's area, say so instead of making it.

## Current structure

This is the starting layout, not a final architecture. Folders and services may be renamed, merged, split, or removed.

```
docker-compose.yml   runs all services together, in pipeline order (see README)
.env.example         template for .env (copy it, never commit .env)
data/                data/source/ holds the data-v1 inputs (committed until DVC is set up); data/eval/v1/
                     is the held-out classifier test set (committed; never tune or train on it, see its
                     README), frozen at tag eval-v1; data/eval/v1.1/ is the same set under labeling rules v1.4; everything else is local and git-ignored, e.g. fixture.db (the web app's
                     encrypted logins)
experiments/         one-off experiments, each its own uv project (gemini_baseline/: Gemini on the training data)
samples/             fake data safe to commit: users.json, messages_sample.jsonl (processed schema)
secrets/             local credentials (git-ignored), see "Google access" below
src/
  ingest/       validates and dedups source threads -> data/raw/threads.jsonl; validate.py checks thread files;
                also google_auth.py and list_events.py (Calendar check)
  preprocess/   cleans, anonymizes, flattens -> data/processed/messages.jsonl + manifest.json
  rag/          indexes each user's messages into ChromaDB (messages_<user_id>); query.py searches from the command line
  api/          FastAPI app (port 8000): GET /health, GET /users, POST /search; ChromaDB access in chroma_store.py
  (chromadb)    ChromaDB server from a pinned image, no folder (host port 8001)
  frontend/     FastAPI web app (port 8501): Sign in with Google, then a dashboard of
                upcoming events (all checked calendars) and recent emails with a
                keyword-based scheduling filter; /search searches the demo mailboxes
                through the api and /about shows the pipeline and live status, both
                with no sign-in; one shared top bar (templates/_nav.html)
```

Inside `src/frontend/`: `main.py` (routes and sign-in), `google_data.py` (Google API calls and formatting), `credential_store.py` (encrypted SQLite storage for users' Google logins), `api_client.py` (calls to the api for the search page), `templates/` (Jinja HTML), `static/` (CSS), `test_*.py` (tests), and `conftest.py` (throwaway settings for tests).

For Milestone 2, the pipeline is ingest → preprocess → rag (one-shot jobs) → api → frontend, as described in the README's Data contract.

Each service under `src/` is currently self-contained, with its own `Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` (3.12), and `main.py`. Services don't import from each other, so `ingest` and `frontend` each have their own Google sign-in code.

## Google access

- Google Cloud project: `fixture-ac215-96dhbm`. Calendar and Gmail APIs are enabled.
- The OAuth consent screen is in Testing mode, so only listed test users can sign in, and logins expire after about 7 days.
- Permissions are listed in one `SCOPES` list per service: `src/ingest/google_auth.py` (read-only Calendar) and `src/frontend/main.py` (read-only Calendar and Gmail, plus basic profile). Ask before adding write permissions.
- Files in `secrets/` (never commit them; get them from a teammate privately):
  - `credentials.json`: "Fixture Desktop" OAuth client, used by `src/ingest`
  - `web_credentials.json`: "Fixture Web" OAuth client, used by `src/frontend` (redirect URI `http://localhost:8501/auth/callback`)
  - `token.json`: your personal login for `src/ingest`, created on first run
- The web app saves each user's Google login, encrypted, in `data/fixture.db` (keyed by email), so logins survive server restarts. The browser cookie holds only the signed-in email. Expired access tokens are refreshed and saved; revoked or expired logins are deleted and the user signs in again. Logging out deletes the stored login.
- The web app needs two values in `.env` at the repo root (each person generates their own; `.env.example` shows how):
  - `SESSION_SECRET`: signs the browser cookie. Changing it signs everyone out.
  - `TOKEN_ENCRYPTION_KEY`: encrypts stored logins. Changing it makes old records unreadable, so everyone signs in again.

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

Calendar check (from `src/ingest`; opens a browser to sign in the first time):

```sh
uv run python list_events.py
```

Web app (from `src/frontend`; needs `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY` in `.env`; then open http://localhost:8501):

```sh
uv run uvicorn main:app --port 8501 --reload
```

API (from `src/api`; then open http://localhost:8000/health):

```sh
uv run uvicorn main:app --port 8000 --reload
```

Tests (from any service folder: `src/ingest`, `src/preprocess`, `src/rag`, `src/api`, or `src/frontend`):

```sh
uv run pytest
```

## Working rules

- **Never commit secrets:** that includes `.env`, credentials, API keys, tokens, and personal email or calendar data. Use fake data in `samples/`.
- **Keep code simple, readable, and commented:** both team members must be able to explain any part of it.
- **Add tests for new features.**
- **Work on a feature branch in its own git worktree:** Will and Dylan each work in a separate worktree so parallel sessions don't collide. Merge into `main` only through a pull request.
- **Don't change the Data contract without telling the other person** (see "Milestone 2" above).
- **`docs/data/labeling_rules.md` is the source of truth for labels and `needs_response`:** any rule change must update that file, bump its version, add a change log entry, and re-check the affected messages.
- **Ask before making major design decisions:** see "Project status and flexibility" above.
