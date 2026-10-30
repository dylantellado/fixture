# Fixture

An autonomous scheduling assistant for students who are recruiting or networking. After you send the first email, Fixture handles the back-and-forth through a confirmed meeting and updates your calendar, without ever breaking a rule you've set. Harvard AC215 project by Dylan Tellado and Will Sherwood.

Multi-service Python project orchestrated with Docker Compose.

## Milestone 2 deliverables

Where each Milestone 2 requirement lives in this repo:

| Requirement | Where |
|---|---|
| Environment setup and documentation | [Getting started](#getting-started) (Docker + `uv`). Running containers: `docs/evidence/running_containers.png` and [`compose_ps.txt`](docs/evidence/compose_ps.txt). |
| Containerized pipeline, one command | [`docker-compose.yml`](docker-compose.yml): `ingest` → `preprocess` → `rag` → `api` → `frontend`, started with `docker compose up --build`. Each service has its own `Dockerfile` and `pyproject.toml` (managed with `uv`). |
| Data and version tracking | Every stage logs the sha256 of what it reads and writes; `preprocess` writes `manifest.json` (counts, hashes, git commit); each ChromaDB collection stores its input hash. See the [evidence README](docs/evidence/README.md#data-version). |
| Pipeline logs and sample input/output | [`full_pipeline_run.log`](docs/evidence/full_pipeline_run.log), [`preprocess_examples.json`](docs/evidence/preprocess_examples.json) (before/after), [`samples/`](samples/) (small fake inputs). |
| RAG: collection, chunking, vector database | `ingest` + `preprocess` (collection and cleaning), [`src/rag`](src/rag/README.md) (chunking, embeddings, one ChromaDB collection per user). |
| One end-to-end retrieval example | [`retrieval_example.md`](docs/evidence/retrieval_example.md) (query → retrieved context) and [`api_search_response.json`](docs/evidence/api_search_response.json) (the same through the API). [`retrieval_check.md`](docs/evidence/retrieval_check.md) checks 15 example queries for quality and per-user isolation. |
| Mock-up and app skeleton | [`docs/mockup/`](docs/mockup/README.md) (screens, Milestone 1 wireframe, what changed). Working skeleton: [`src/frontend`](src/frontend) (search and "How it works" pages) calling [`src/api`](src/api/README.md) (`GET /users`, `POST /search`). |
| Tests | `uv run pytest` in each service folder under `src/`. |

## Layout

```
data/        data/source/ holds the data-v1 inputs (in git); data/eval/v1/ is the held-out classifier
             test set (in git, never tune on it); everything else in data/ is local and git-ignored
docs/        data notes, evidence of pipeline runs, and the app mock-up
experiments/ one-off experiments, e.g. gemini_baseline/ (Gemini labeling the training data)
samples/     fake sample data checked into the repo
secrets/     local credentials (git-ignored)
src/
  ingest/      validates and deduplicates generated email threads
  preprocess/  cleans threads into one record per message
  rag/         indexes messages into ChromaDB (one-shot job)
  api/         HTTP API: health check and search
  classifier/  labels one email with Gemini (label, needs_response, reason)
  frontend/    web app: Google sign-in, dashboard with live email labels, search page
```

eval-v1 is frozen at tag eval-v1. Never used for tuning. Rule changes create eval-v1.1: `data/eval/v1.1/` is eval-v1 under labeling rules v1.5 (one answer changed).

Each service under `src/` is its own [uv](https://docs.astral.sh/uv/) project with a `pyproject.toml`, `uv.lock`, `Dockerfile`, and `main.py`.

## Getting started

1. Copy the settings template, then fill in `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY` (`.env.example` shows how):

   ```sh
   cp .env.example .env
   ```

2. Run the whole pipeline and app with one command. `GIT_COMMIT` is recorded in `data/processed/manifest.json`, so you can see which code produced the data. The input data (data-v1, see `docs/data/corpus_notes.md`) is already in `data/source/`:

   ```sh
   GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build
   ```

Startup order: `ingest` → `preprocess` → `rag` run once and exit, each waiting for the previous one to succeed. `rag` also waits for `chromadb` to be healthy. `api` starts after `rag` finishes, and `frontend` starts after `api` is healthy. `classifier` starts on its own; until it's up, the dashboard uses keyword tags.

The `classifier` needs Google application-default credentials for Vertex AI. Run `gcloud auth application-default login` once; Docker mounts `~/.config/gcloud` read-only. Without them the app still runs and the dashboard falls back to keyword tags.

**Privacy:** live classification sends the signed-in user's email text (the 20 most recent inbox emails and their threads, quoted replies and signatures removed) to Gemini in our own GCP project (`fixture-ac215-96dhbm`). Email text is never logged or saved; `data/fixture.db` keeps only a hash of the account's email and each message id's label, `needs_response`, reason, model, rules version and time, and signing out deletes that account's rows.

| Service  | Host URL               |
|----------|------------------------|
| frontend | http://localhost:8501  |
| api      | http://localhost:8000  |
| chromadb | http://localhost:8001  |
| classifier | http://localhost:8002 |

To work on a single service locally, run it from its folder (e.g. `src/rag`):

```sh
uv run main.py                                      # one-shot jobs
uv run uvicorn main:app --port 8000 --reload        # api
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm \
  uv run uvicorn main:app --port 8002 --reload      # classifier (the web app finds it at CLASSIFIER_URL, default http://localhost:8002)
uv add <package>                                    # add a dependency
```

## Data contract

This is the source of truth for how the data side (Will) and the search side (Dylan) fit together. Don't change it without telling the other person, and update this section in the same PR as the change.

### Pipeline files

| File | Written by | Contents |
|------|------------|----------|
| `data/source/users.json` | data generation | The fake users: a JSON list of `{"user_id", "name", "email"}`. |
| `data/source/generated_threads.jsonl` | data generation | One JSON object per thread: `user_id`, `thread_id`, `subject`, `participants`, `messages` (each: `sender`, `recipients`, `timestamp`, `body`, `label`). `timestamp` is the email "Date" header format, e.g. `Tue, 13 Oct 2026 09:12:00 -0400`. Committed to git for now (data-v1, fictional, ~300 KB) so a fresh clone runs end to end; DVC will take over once its storage bucket exists. |
| `data/source/annotations.jsonl` | labeling | One line per source message, keyed by `user_id`, `thread_id` and `position` (0-based index in the thread): `needs_response` (bool), the `rule` that set it, `rationale` and `rules_version`, following `docs/data/labeling_rules.md`. Not read by the pipeline; it is the ground truth for scoring `needs_response`. |
| `data/raw/threads.jsonl` | `ingest` | Same shape as the source threads, validated and deduplicated, sorted by `(user_id, thread_id)`, with `user_id` kept. Adds `source` (`"generated"`) and `provenance` (`file`, `line`, `sha256` of the thread). |
| `data/processed/messages.jsonl` | `preprocess` | One JSON object per message (schema below). This is what `rag` indexes. |
| `data/processed/manifest.json` | `preprocess` | Counts, file hashes, and provenance (below). |

`samples/` has small, fake, committed versions of the files the search side reads: `samples/users.json` (the four generated users) and `samples/messages_sample.jsonl` (20 hand-made messages, two users, all six labels). `samples/generated_threads_sample.jsonl` has 16 source threads covering every user and every shared contact. The full corpus is described in `docs/data/corpus_notes.md`.

### `messages.jsonl` schema

One JSON object per line:

| Field | Type | Notes |
|-------|------|-------|
| `message_id` | string | Deterministic, unique across all users (rule below). |
| `user_id` | string | Whose mailbox this is, e.g. `user_01`. |
| `thread_id` | string | Unique within a user. |
| `source` | string | `"generated"` for now. |
| `sender` | string | `"Display Name <placeholder>"`, e.g. `"Jordan Lee <EMAIL_003>"`. |
| `recipients` | list of strings | Same format as `sender`. Always a list, possibly empty. |
| `timestamp` | string | Always `YYYY-MM-DDTHH:MM:SS±HH:MM`, in the sender's offset, e.g. `2026-10-13T09:12:00-04:00`. UTC is `+00:00`, never `Z`. |
| `subject` | string | The thread's subject (the same for every message in a thread). |
| `body` | string | Cleaned text: no quoted replies, signatures, or HTML. |
| `label` | string | One of the labels below. |

Labels:

| Label | Meaning |
|-------|---------|
| `new_request` | Someone asks to set up a meeting. |
| `proposed_times` | Specific times are offered. |
| `acceptance` | A time is confirmed. |
| `reschedule` | A confirmed meeting needs to move. |
| `assistant_handoff` | Someone hands scheduling to an assistant (e.g. a professor copying their assistant). |
| `none` | Not about scheduling. |

[`docs/data/labeling_rules.md`](docs/data/labeling_rules.md) is the source of truth for labels and `needs_response`: the exact definitions, priority rule and edge cases. Any rule change must update that file, bump its version, add a change log entry, and re-check the affected messages.

### Rules the search side depends on

- **`user_id` format:** lowercase letters, digits, and underscores only (e.g. `user_01`), because it becomes part of a ChromaDB collection name.
- **`message_id` is deterministic, never random:** the first 16 hex characters of `sha256("<user_id>|<thread_id>|<position>")`, where `position` is the message's 0-based index in its thread in `data/raw/threads.jsonl` (preprocess never drops a message, so positions never shift). Re-running the pipeline gives the same ids, and ids never collide across users.
- **No nulls:** `message_id`, `user_id`, `thread_id`, `sender`, `timestamp`, `source`, `subject`, and `label` are always strings (`""` if missing). `recipients` is always a list and `body` is always a string.
- **Anonymization:** email addresses become `EMAIL_###` and phone numbers become `PHONE_###`, using one placeholder map shared across all users, so the same address always gets the same placeholder. Display names stay readable. Placeholders are numbered in sorted order of the addresses and numbers in the whole corpus, so they are stable for a given data version but can renumber when data is added (rag rebuilds each collection from scratch, so that's fine). Treat them as opaque strings: there are three digits today, more past 999. An address with no display name is written `<EMAIL_005>`. Phone numbers are normalized before numbering, so every way of writing a number gets one placeholder.
- **Sorting by time:** offsets differ between messages, so sort by parsed time, not by the `timestamp` string (rag stores a numeric timestamp for this).
- **Safe failure:** `preprocess` exits non-zero on any failure and never leaves half-written files (write to a temporary file, then rename).

### `manifest.json`

```json
{
  "created_at": "2026-10-19T14:00:00Z",
  "git_commit": "eed41cd...",
  "counts": {"total": 20, "per_user": {"user_01": 10, "user_02": 10}},
  "sha256": {
    "data/raw/threads.jsonl": "...",
    "data/processed/messages.jsonl": "..."
  }
}
```

`sha256` covers every input and output file of `preprocess`.

### Vector database

- A ChromaDB server container (`chromadb` in `docker-compose.yml`, pinned version).
- One collection per user, named `messages_<user_id>` (e.g. `messages_user_01`), using cosine distance. `rag` rebuilds every collection from scratch on each run and deletes `messages_*` collections for users no longer in `users.json`. Every user in `users.json` gets a collection, even with no messages.
- Collection metadata: `user_id`, `user_name` (display name from `users.json`), `indexed_at` (UTC ISO time), `input_path` and `input_sha256` (the indexed messages file), `used_sample_data` (bool), `manifest_git_commit` and `manifest_created_at` (from `manifest.json`, `""` if absent), `embedding_model`.
- One chunk per message; bodies over ~1,000 characters are split into overlapping pieces. Chunk id: `<message_id>-<chunk index>` (index starts at 0). Chunk text: `From: <sender display name>\nSubject: <subject>\nDate: <timestamp>\n\n<body>`, with the header repeated on every piece (`From:` falls back to the raw sender when there is no display name).
- Chunk metadata (all strings or ints, never null): `message_id`, `user_id`, `thread_id`, `sender`, `sender_name` (`""` if the sender has no display name), `timestamp`, `timestamp_epoch` (int Unix seconds with the UTC offset applied, `0` if `timestamp` is `""`; use it to sort, never the string), `source`, `subject`, `label`, `chunk_index` (int).
- Embeddings: `all-MiniLM-L6-v2` through Chroma's built-in default embedding function, `chromadb.utils.embedding_functions.DefaultEmbeddingFunction()` from `chromadb==1.5.9` (runs locally with ONNX, no API key). Indexing and search must use this same function. Search score = `1 - cosine distance`.
- `rag` requires timestamps to be ISO 8601 with a UTC offset (or `""`), every message's `user_id` to be in `users.json`, and `user_id`s not to end with `_` (Chroma collection names must end with a letter or digit). Otherwise it exits non-zero without touching the index.
- If `data/processed/messages.jsonl` is missing, `rag` indexes `samples/` instead and logs a warning (`used_sample_data` is then `true`).
- The model is cached in the `model_cache` Docker volume, shared by `rag` and `api`, so it downloads once. Details: `src/rag/README.md`.

### API

- `GET /health` → `{"status": "ok"}`
- `GET /users` → users that have a `messages_<user_id>` collection, read from collection metadata (`user_name` and `indexed_at`, set by `rag`):

  ```json
  [{"user_id": "user_01", "name": "Priya Shah", "indexed_at": "2026-10-20T01:20:48+00:00"}]
  ```

- `POST /search` with `{"user_id": str, "query": str, "k": int = 5, "label": str | null = null}` returns:

  ```json
  {
    "user_id": "user_01",
    "query": "when is my Northbridge interview?",
    "results": [{"text": "...", "score": 0.82, "metadata": {"message_id": "...", "user_id": "user_01"}}]
  }
  ```

  It only searches `messages_<user_id>`, never another user's collection. Results come best first, and `score` is `1 - cosine distance`, rounded to 3 places. `k` is 1–20, `query` can't be blank, and the optional `label` (one of the six labels) limits results to that label. A `user_id` that doesn't match `^[a-z0-9_]+$` or has no collection returns `400` `{"detail": "unknown user"}`. Other invalid input returns `422`. If ChromaDB is unreachable, `/users` and `/search` return `503`.

  See `src/api/README.md` for examples.

### Classifier

Labels live Gmail emails for the web app; it doesn't read the pipeline's files. Details and examples: `src/classifier/README.md`.

- `GET /health` → `{"status": "ok", "model": "gemini-3.8-flash", "rules_version": "1.2"}`. `rules_version` comes from `docs/data/labeling_rules.md`.
- `POST /classify` with `{"thread": [{"from", "date", "subject", "body", "to"?, "from_user"?}], "target_index": int, "message_id"?: str}` returns `{"label", "needs_response", "reason", "model", "rules_version", "latency_ms"}`. `label` is one of the six labels above. Earlier messages are context; messages after `target_index` are ignored. Errors (`422`, `502`, `503`) never include a label.
- The web app caches answers in `data/fixture.db` (table `classifications`), keyed by account (sha256 of the signed-in email) and Gmail message id, classifies again when `rules_version` changes, and deletes the account's rows on sign-out.
- The prompt includes `docs/data/labeling_rules.md` except its "Not adopted", "Training data" and "Change log" sections; the classifier won't start if one of those headings is missing, so moving a section means updating `EXCLUDED_SECTIONS` in `src/classifier/prompt.py`.

Inside Docker, `rag` and `api` reach ChromaDB at `CHROMA_HOST=chromadb`, `CHROMA_PORT=8000`, the frontend reaches the API at `API_URL=http://api:8000`, and the classifier at `CLASSIFIER_URL=http://classifier:8002`.
