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

**What exists so far:** a Google connection proof of concept and the Milestone 2 search pipeline on fake data. `src/ingest` has a command-line Calendar check, and `src/frontend` has a small web app that reads Calendar and Gmail, plus a "Search past threads" page over the demo mailboxes. The dashboard labels the signed-in user's 20 most recent emails with the `classifier` service (Gemini on Vertex AI, following `docs/data/labeling_rules.md`): a label, a "Needs response" badge and a one-line reason, cached per account and Gmail message id in `data/fixture.db` (deleted on sign-out), with the old keyword match as a fallback when the classifier is down. Emails that need a response get a "Draft reply" button: the web app gathers the thread, Calendar free/busy for 14 days, the calendar's time zone and recent emails with the sender (read-only), and the `drafter` service returns a reply whose times are computed and checked in code (never an unchecked draft); drafts are shown only, never stored or sent. Everything is read-only; nothing writes to a calendar, creates Gmail drafts or sends email yet. `ingest` and `preprocess` are working one-shot jobs over a generated, fictional email corpus of 4 users (see `docs/data/corpus_notes.md`; plan in `docs/data/generation/`); `rag` embeds each user's messages and threads with Vertex AI (`gemini-embedding-001`) into their own ChromaDB collection (each message chunk carries its thread subject and a "Replying to" excerpt; each thread also gets a chunk); `api` answers `GET /health`, `GET /users`, and `POST /search`, which searches one user's collection only and returns messages (never threads), ranked by their own and their thread's similarity; `src/rag/check_retrieval.py` scores 47 queries split into dev and test and logs every setup to `docs/evidence/rag_experiments.md`; `classifier` answers `GET /health` and `POST /classify`; `drafter` answers `GET /health` and `POST /draft`.

**Milestone 3:** the `classifier` is deployed to Cloud Run (`fixture-classifier`, us-east1, https://fixture-classifier-622192804476.us-east1.run.app), authentication required (callers need `roles/run.invoker`), with structured JSON logs, log-based metrics, a Monitoring dashboard, an uptime check and an error-rate alert. The web app uses the local classifier by default; with `CLASSIFIER_URL` set to the Cloud Run URL in `.env` it calls the deployed one with a Google ID token from the gcloud application-default credentials (`src/frontend/classifier_client.py`, cached until shortly before it expires; see the README's "Use the deployed classifier"). Evidence: `docs/evidence/ms3/`. Also in MS3: the `drafter` service (port 8003, Cloud Run-ready image, not deployed) and the dashboard's Draft reply; its 16 fake scenarios run against the real Gemini are in `docs/evidence/ms3/draft_scenarios.md`.

## Milestone 2

**Scope:** a searchable, per-user email pipeline on fake data. Generated multi-user scheduling emails flow through `ingest` → `preprocess` → `rag`, which indexes each user's messages in ChromaDB. The `api` searches one user's messages at a time, and the frontend gets a search page.

**The contract:** the "Data contract" section of `README.md` is the source of truth for file paths, the message schema, labels, id rules, the vector database layout, and the API. Read it before working on any service. Don't change it without telling the other person, and update it in the same PR as the change.

**Ownership:**
- **Will:** data generation, `src/ingest`, `src/preprocess`, DVC, labels, test scenarios
- **Dylan:** `src/rag`, `src/api`, `src/classifier`, `src/drafter`, the frontend (search page, live labels, Draft reply), the `chromadb`, `classifier` and `drafter` services, the mockup
- **Both:** `docker-compose.yml` (each edits only their own services), `README.md`, `docs/` and evidence

Will and Dylan build in parallel with separate Claude Code sessions. Stay inside your owner's area; if a change is needed in the other person's area, say so instead of making it.

## Current structure

This is the starting layout, not a final architecture. Folders and services may be renamed, merged, split, or removed.

```
docker-compose.yml   runs all services together, in pipeline order (see README)
.env.example         template for .env (copy it, never commit .env)
dvc.yaml, dvc.lock   DVC data pipeline (ingest -> preprocess) and its pinned hashes; rules in docs/data/versions.md
data/                data/source/ holds the data-v1 inputs (in DVC, bucket gs://fixture-ac215-96dhbm-dvc: `dvc pull`); data/eval/v1/
                     is the held-out classifier test set (committed; never tune or train on it, see its
                     README), frozen at tag eval-v1; data/eval/v1.1/ is the same set under labeling rules v1.5; everything else is local and git-ignored, e.g. fixture.db (the web app's
                     encrypted logins)
experiments/         one-off experiments, each its own uv project (gemini_baseline/: Gemini on the training data)
samples/             fake data safe to commit: users.json, messages_sample.jsonl (processed schema)
secrets/             local credentials (git-ignored), see "Google access" below
src/
  ingest/       validates and dedups source threads -> data/raw/threads.jsonl; validate.py checks thread files;
                also google_auth.py and list_events.py (Calendar check)
  preprocess/   cleans, anonymizes, flattens -> data/processed/messages.jsonl + manifest.json
  rag/          embeds each user's message and thread chunks with Vertex AI into ChromaDB (messages_<user_id>);
                embeddings.py and message_search.py are copied, identical, into api/ (tests check);
                query.py searches from the command line; check_retrieval.py scores retrieval_cases.json
                (dev/test split, never tune on test) and appends to docs/evidence/rag_experiments.md
  api/          FastAPI app (port 8000): GET /health, GET /users, POST /search; ChromaDB access in chroma_store.py;
                embeds queries with Vertex AI and refuses a collection built with another embedding model
  (chromadb)    ChromaDB server from a pinned image, no folder (host port 8001)
  classifier/   FastAPI service (port 8002, or $PORT): POST /classify labels one email in its thread with
                Gemini on Vertex AI (label, needs_response, reason); prompt.py builds the prompt from
                docs/data/labeling_rules.md minus "Not adopted" and "Change log" (it fails at
                startup if one of those headings is missing; training_conflicts.md is never read),
                gemini.py calls the model, logs.py writes allow-listed JSON log fields only; uses
                gcloud application-default credentials locally, never logs or saves email text.
                deploy.sh deploys to Cloud Run; cloud/ has setup.sh, build_context.sh (image =
                committed code + exact rules file), monitoring.sh and its configs; examples/ has
                fake requests
  drafter/      FastAPI service (port 8003, or $PORT): POST /draft drafts a reply to one email from the
                request alone (thread, user, busy times, past emails, optional classification; no Google
                user credentials). pipeline.py runs the steps: classification (or a call to the classifier
                through classifier_client.py, an identical copy of the frontend's: ID token if CLASSIFIER_URL
                is https; tests check the copies match), rules.py (rules/default_rules.json + per-user
                RulesStore + request overrides, versioned; busy events never offered, in code), slots.py
                (free slots/windows, DST-safe), context.py (top 5 past emails by gemini-embedding-001),
                draft.py (one Gemini call, JSON, picks slot ids), checker.py + mentions.py (every time and
                every date/time in the text checked in code; one retry, then status error, no draft);
                logs.py allow-lists log fields. scenarios/ + run_scenarios.py write
                docs/evidence/ms3/draft_scenarios.md
  frontend/     FastAPI web app (port 8501): Sign in with Google, then a dashboard of
                upcoming events (all checked calendars) and recent emails labeled by
                the classifier (keyword fallback when it's down), with Scheduling and
                Needs response filters and a Draft reply button on emails that need a response
                (POST /api/draft-reply); /search searches the demo mailboxes
                through the api and /about shows the pipeline and live status, both
                with no sign-in; one shared top bar (templates/_nav.html)
```

Inside `src/frontend/`: `main.py` (routes and sign-in), `google_data.py` (Google API calls and formatting), `credential_store.py` (encrypted SQLite storage for users' Google logins), `api_client.py` (calls to the api for the search page), `classifier_client.py` (calls to the classifier, with a Google ID token for Cloud Run; an identical copy is in `src/drafter`, tests check), `live_labels.py` (labels the dashboard's emails: cache, parallel calls, fallback), `classification_cache.py` (the label cache in `data/fixture.db`: a hash of the account's email, message id, label, needs_response, reason, model, rules version, time; never email text; deleted on sign-out), `cleaning.py` (copied from `src/preprocess/cleaning.py`; keep in sync by hand), `draft_inputs.py` (gathers the drafter's inputs for Draft reply: thread, free/busy, time zone, past emails with the sender, cached label; stores nothing), `drafter_client.py` (calls to the drafter), `templates/` (Jinja HTML), `static/` (CSS, and `draft.js` for the Draft reply panel), `test_*.py` (tests), and `conftest.py` (throwaway settings for tests).

For Milestone 2, the pipeline is ingest → preprocess → rag (one-shot jobs) → api → frontend, as described in the README's Data contract.

Each service under `src/` is currently self-contained, with its own `Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` (3.12), and `main.py`. Services don't import from each other, so `ingest` and `frontend` each have their own Google sign-in code.

## Google access

- Google Cloud project: `fixture-ac215-96dhbm`. Calendar and Gmail APIs are enabled.
- The OAuth consent screen is in Testing mode, so only listed test users can sign in, and logins expire after about 7 days.
- Cloud Run (classifier): the service runs as `fixture-classifier@` (only `roles/aiplatform.user` and `roles/logging.logWriter`) and Cloud Build as `fixture-builder@`; both are created by `src/classifier/cloud/setup.sh`. Ask before granting anyone `roles/run.invoker` or creating alerts that email anyone other than Dylan.
- Permissions are listed in one `SCOPES` list per service: `src/ingest/google_auth.py` (read-only Calendar) and `src/frontend/main.py` (read-only Calendar and Gmail, plus basic profile). Ask before adding write permissions. Draft reply uses only these (free/busy and the calendar's time zone come from `calendar.readonly`, the sender search from `gmail.readonly`); the drafter itself has no Google user permissions and uses application-default credentials for Vertex AI only. The classifier uses no Google user permissions: it gets email text from the web app and calls Vertex AI with gcloud application-default credentials (`aiplatform.googleapis.com` is enabled; Docker mounts `~/.config/gcloud` read-only). `rag` and `api` use the same credentials for Vertex AI embeddings (`EMBEDDING_MODEL`, default `gemini-embedding-001`; `EMBEDDING_LOCATION`, default `us-central1`; on this project `gemini-embedding-2` only works in `global` and ignores task types). Indexing and search send email text to Vertex AI in our own GCP project; never log it.
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

rag (from `src/rag`; needs `gcloud auth application-default login` once and ChromaDB on localhost:8001, e.g. `docker compose up -d chromadb`):

```sh
uv run main.py                                  # index data/processed (or samples/) with Vertex AI
uv run python check_retrieval.py                # score the dev queries (add --split all --record "name" to log a row)
```

API (from `src/api`; same credentials; then open http://localhost:8000/health):

```sh
uv run uvicorn main:app --port 8000 --reload
```

Classifier (from `src/classifier`; needs `gcloud auth application-default login` once; then open http://localhost:8002/health). Run the web app as above and it finds the classifier at `CLASSIFIER_URL` (default `http://localhost:8002`):

```sh
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8002 --reload
```

Drafter (from `src/drafter`; same credentials; then open http://localhost:8003/health). The web app finds it at `DRAFTER_URL` (default `http://localhost:8003`); it calls the classifier at `CLASSIFIER_URL` (default `http://localhost:8002`) when the web app has no cached label:

```sh
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8003 --reload
uv run python run_scenarios.py   # 16 fake scenarios against the real Gemini; rewrites docs/evidence/ms3/draft_scenarios.md
```

Deploy the classifier to Cloud Run (commit first; it builds from the last commit with Cloud Build, no local Docker needed):

```sh
src/classifier/deploy.sh
```

Data (from the repo root; needs `uv tool install "dvc[gs]==3.67.1"` and gcloud application-default credentials; rules in `docs/data/versions.md`):

```sh
dvc pull     # fetch the data for this commit
dvc repro    # rerun ingest -> preprocess if inputs or code changed; commit dvc.lock with the code
dvc push     # upload new data before pushing the commit
```

Tests (from any service folder: `src/ingest`, `src/preprocess`, `src/rag`, `src/api`, `src/classifier`, `src/drafter`, or `src/frontend`):

```sh
uv run pytest
```

## Working rules

- **Never commit secrets:** that includes `.env`, credentials, API keys, tokens, and personal email or calendar data. Use fake data in `samples/`.
- **Real email stays private:** live classification and Draft reply send the signed-in user's email text (and, for drafts, free/busy times) to Gemini in our own GCP project. Never log or save real email bodies, subjects, senders or drafts (logs may hold message ids, labels, statuses, counts and timing), and never put real email in tests, samples or commits.
- **Drafts are checked in code:** the drafter returns a draft only when every check in `src/drafter/checker.py` passes. Don't add a path that returns or shows an unchecked draft, and keep "busy events are never offered" in code, not in the editable rules.
- **Keep code simple, readable, and commented:** both team members must be able to explain any part of it.
- **Add tests for new features.**
- **Work on a feature branch in its own git worktree:** Will and Dylan each work in a separate worktree so parallel sessions don't collide. Merge into `main` only through a pull request.
- **Don't change the Data contract without telling the other person** (see "Milestone 2" above).
- **`docs/data/labeling_rules.md` is the source of truth for labels and `needs_response`:** any rule change must update that file, bump its version, add a change log entry, and re-check the affected messages.
- **Ask before making major design decisions:** see "Project status and flexibility" above.
