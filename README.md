# Fixture

An autonomous scheduling assistant for students who are recruiting or networking. After you send the first email, Fixture handles the back-and-forth through a confirmed meeting and updates your calendar, without ever breaking a rule you've set. Harvard AC215 project by Dylan Tellado and Will Sherwood.

Multi-service Python project orchestrated with Docker Compose.

## Layout

```
data/        local data (git-ignored; data/source is versioned with DVC)
samples/     fake sample data checked into the repo
secrets/     local credentials (git-ignored)
src/
  ingest/      validates and deduplicates generated email threads
  preprocess/  cleans threads into one record per message
  rag/         indexes messages into ChromaDB (one-shot job)
  api/         HTTP API: health check and search
  frontend/    web app: Google sign-in, dashboard, search page
```

Each service under `src/` is its own [uv](https://docs.astral.sh/uv/) project with a `pyproject.toml`, `uv.lock`, `Dockerfile`, and `main.py`.

## Getting started

1. Copy the settings template, then fill in `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY` (`.env.example` shows how):

   ```sh
   cp .env.example .env
   ```

2. Put the generated source data in `data/source/`: `users.json` and `generated_threads.jsonl` (data-v1, see `docs/data/corpus_notes.md`). It isn't in git. Until DVC is set up, get the two files from Will. Later this step becomes `dvc pull`.
3. Run the whole pipeline and app with one command. `GIT_COMMIT` is recorded in `data/processed/manifest.json`, so you can see which code produced the data:

   ```sh
   GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build
   ```

Startup order: `ingest` → `preprocess` → `rag` run once and exit, each waiting for the previous one to succeed. `rag` also waits for `chromadb` to be healthy. `api` starts after `rag` finishes, and `frontend` starts after `api` is healthy.

| Service  | Host URL               |
|----------|------------------------|
| frontend | http://localhost:8501  |
| api      | http://localhost:8000  |
| chromadb | http://localhost:8001  |

To work on a single service locally, run it from its folder (e.g. `src/rag`):

```sh
uv run main.py                                      # one-shot jobs
uv run uvicorn main:app --port 8000 --reload        # api
uv add <package>                                    # add a dependency
```

## Data contract

This is the source of truth for how the data side (Will) and the search side (Dylan) fit together. Don't change it without telling the other person, and update this section in the same PR as the change.

### Pipeline files

| File | Written by | Contents |
|------|------------|----------|
| `data/source/users.json` | data generation | The fake users: a JSON list of `{"user_id", "name", "email"}`. |
| `data/source/generated_threads.jsonl` | data generation | One JSON object per thread: `user_id`, `thread_id`, `subject`, `participants`, `messages` (each: `sender`, `recipients`, `timestamp`, `body`, `label`). `timestamp` is the email "Date" header format, e.g. `Tue, 13 Oct 2026 09:12:00 -0400`. Versioned with DVC, never git. |
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

Inside Docker, `rag` and `api` reach ChromaDB at `CHROMA_HOST=chromadb`, `CHROMA_PORT=8000`, and the frontend reaches the API at `API_URL=http://api:8000`.
