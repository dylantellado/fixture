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
| One end-to-end retrieval example | [`retrieval_example.md`](docs/evidence/retrieval_example.md) (query → retrieved context) and [`api_search_response.json`](docs/evidence/api_search_response.json) (the same through the API). [`retrieval_check.md`](docs/evidence/retrieval_check.md) scores 47 example queries (Will's 15 plus 32 added in Milestone 3) for quality and per-user isolation; [`rag_experiments.md`](docs/evidence/rag_experiments.md) logs every setup we scored. |
| Mock-up and app skeleton | [`docs/mockup/`](docs/mockup/README.md) (screens, Milestone 1 wireframe, what changed). Working skeleton: [`src/frontend`](src/frontend) (search and "How it works" pages) calling [`src/api`](src/api/README.md) (`GET /users`, `POST /search`). |
| Tests | `uv run pytest` in each service folder under `src/`. |

## MS3: deployment and monitoring

The `classifier` (labels one email with Gemini) runs on **Cloud Run**:
https://fixture-classifier-622192804476.us-east1.run.app (project `fixture-ac215-96dhbm`,
region `us-east1`). It requires authentication: a project owner grants a person
`roles/run.invoker`, and that person sends `Authorization: Bearer $(gcloud auth print-identity-token)`.
Details: [`src/classifier/README.md`](src/classifier/README.md#deployed-service-cloud-run).

| Requirement | Where |
|---|---|
| Serverless deployment, redeploy steps | `src/classifier/deploy.sh`: one command builds the image with Cloud Build and deploys it (first time: `cloud/setup.sh`). It runs as its own service account (Vertex AI user + log writer only), scales 0 to 2 instances, and the image has the exact `docs/data/labeling_rules.md` from the deployed commit inside. See [Deploy and redeploy](src/classifier/README.md#deploy-and-redeploy). |
| Monitoring | Structured JSON logs in Cloud Logging (one line per request: label, latency, tokens, errors; never email text), three log-based metrics, a dashboard (requests, error rate, p50/p95 latency, instances), an authenticated uptime check on `/health` and an error-rate email alert, all created by `src/classifier/cloud/monitoring.sh`. See [Monitoring](src/classifier/README.md#monitoring). |
| Documented, tested API with examples | [`src/classifier/README.md`](src/classifier/README.md#endpoints) (endpoints, JSON, local and deployed examples, auth), fake requests in [`src/classifier/examples/`](src/classifier/examples/), tests in `src/classifier/test_*.py`. |
| Deployed service answering curl | [`docs/evidence/ms3/cloud_run_curl.md`](docs/evidence/ms3/cloud_run_curl.md) (exact commands and responses), screenshots and cost in [`docs/evidence/ms3/`](docs/evidence/ms3/README.md). |

Cost: about $0.003 per classified email (Gemini is ~98% of it; $0.006 from 2027), about $3 a
month at low usage, $0 when idle.

### Use the deployed classifier

The dashboard uses the local classifier by default. To label emails with the one on Cloud Run:

1. Sign in once with a Google account that has `roles/run.invoker` on the service (project owners have it):
   ```sh
   gcloud auth application-default login
   ```
2. Add this line to `.env` at the repo root (see `.env.example`):
   ```sh
   CLASSIFIER_URL=https://fixture-classifier-622192804476.us-east1.run.app
   ```
3. Start the web app as usual: `uv run uvicorn main:app --port 8501 --reload` in `src/frontend`, or
   `docker compose up --build` (which mounts `~/.config/gcloud` read-only into the frontend).

For an `https` URL, `src/frontend/classifier_client.py` sends a Google ID token with every request.
It comes from your application-default credentials: refreshing your gcloud login returns one
(its audience is gcloud's client id, which Cloud Run accepts, as with `gcloud auth print-identity-token`);
a service account would instead get one for the service URL. The token is cached until 5 minutes
before it expires (they last an hour), then fetched again. `http` URLs (local, Docker's `classifier`) get none.
With no token (never signed in, expired login, offline) or a `403` from Cloud Run (no
`roles/run.invoker`), the dashboard shows keyword tags and its "isn't reachable" notice, and the
web app logs the error type only. Remove the line to go back to the local classifier.

## Layout

```
data/        data/source/ holds the data-v1 inputs (in DVC: `dvc pull`, see docs/data/versions.md);
             data/eval/v1/ is the held-out classifier test set (in git, never tune on it);
             everything else in data/ is local and git-ignored
dvc.yaml     the data pipeline (ingest -> preprocess) for `dvc repro`; dvc.lock pins every hash
docs/        data notes, evidence of pipeline runs, and the app mock-up
experiments/ one-off experiments, e.g. gemini_baseline/ (Gemini labeling the training data)
samples/     fake sample data checked into the repo
secrets/     local credentials (git-ignored)
src/
  ingest/      validates and deduplicates generated email threads
  preprocess/  cleans threads into one record per message
  rag/         embeds messages and threads with Vertex AI into ChromaDB (one-shot job)
  api/         HTTP API: health check and search (one user's messages, with thread context)
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

2. Get the data. It's versioned with DVC in our private bucket (setup and rules: [`docs/data/versions.md`](docs/data/versions.md)):

   ```sh
   uv tool install "dvc[gs]==3.67.1"
   gcloud auth application-default login
   dvc pull
   ```

3. Run the whole pipeline and app with one command. `GIT_COMMIT` is recorded in `data/processed/manifest.json`, so you can see which code produced the data. The input data (data-v1, see `docs/data/corpus_notes.md`) is now in `data/source/`:

   ```sh
   GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build
   ```

Startup order: `ingest` → `preprocess` → `rag` run once and exit, each waiting for the previous one to succeed. `rag` also waits for `chromadb` to be healthy. `api` starts after `rag` finishes, and `frontend` starts after `api` is healthy. `classifier` starts on its own; until it's up, the dashboard uses keyword tags.

`rag`, `api` and `classifier` need Google application-default credentials for Vertex AI. Run `gcloud auth application-default login` once; Docker mounts `~/.config/gcloud` read-only into those three services (no API keys, nothing in `.env`). Without credentials `rag` can't embed the messages and exits with an error, so `api` and `frontend` don't start; the classifier alone falls back gracefully (the dashboard uses keyword tags).

**Privacy:** indexing and search send email text to Vertex AI in our own GCP project (`rag` embeds every indexed message, today the fictional data-v1 corpus; `api` embeds each search query). Live classification sends the signed-in user's email text (the 20 most recent inbox emails and their threads, quoted replies and signatures removed) to Gemini in our own GCP project (`fixture-ac215-96dhbm`). Email text is never logged or saved; `data/fixture.db` keeps only a hash of the account's email and each message id's label, `needs_response`, reason, model, rules version and time, and signing out deletes that account's rows.

| Service  | Host URL               |
|----------|------------------------|
| frontend | http://localhost:8501  |
| api      | http://localhost:8000  |
| chromadb | http://localhost:8001  |
| classifier | http://localhost:8002 |

To work on a single service locally, run it from its folder (e.g. `src/rag`):

```sh
uv run main.py                                      # one-shot jobs (rag needs gcloud application-default credentials)
uv run uvicorn main:app --port 8000 --reload        # api (same credentials, for embedding queries)
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm \
  uv run uvicorn main:app --port 8002 --reload      # classifier (the web app finds it at CLASSIFIER_URL, default http://localhost:8002)
uv add <package>                                    # add a dependency
```

## Data contract

This is the source of truth for how the data side (Will) and the search side (Dylan) fit together. Don't change it without telling the other person, and update this section in the same PR as the change.

### Milestone 3 changes

What changed for the search side in Milestone 3 (Will: nothing changes in your files; the one new dependency on your output is the thread-order rule below):

- **Embeddings:** Vertex AI `gemini-embedding-001` (3,072 dimensions, 2,048-token limit, `RETRIEVAL_DOCUMENT` for stored chunks and `RETRIEVAL_QUERY` for searches) replaces the local all-MiniLM-L6-v2. Chroma's default ONNX embedder and the `model_cache` volume are gone. `rag` and `api` need gcloud application-default credentials.
- **Chunks:** each message chunk now starts with the thread subject, sender, date and a `Replying to` excerpt of the previous message, and each thread gets its own chunk. Metadata gains `chunk_type`, `token_count`, and for thread chunks `message_ids`.
- **Search:** still one user's collection only, still returns messages (never threads) in the same request/response shape. **`score` means something new:** `0.5 × the message's own similarity + 0.5 × its thread's` (definition under API below), no longer one chunk's cosine similarity. A collection built with another embedding model is refused (`503`, rerun rag).
- **New rule rag depends on:** `messages.jsonl` lists each thread's messages in thread order (it already does).
- **Data is in DVC (Will):** `data/source/` is no longer in git. Run `dvc pull` after cloning or checking out (needs gcloud application-default credentials). Paths, file shapes and ids don't change. `dvc repro` reruns `ingest` → `preprocess` and records every hash in `dvc.lock`; releases are git tags `data-vN` listed in [`docs/data/versions.md`](docs/data/versions.md).
- Measurements: [`docs/evidence/retrieval_check.md`](docs/evidence/retrieval_check.md) and [`docs/evidence/rag_experiments.md`](docs/evidence/rag_experiments.md).

### Pipeline files

| File | Written by | Contents |
|------|------------|----------|
| `data/source/users.json` | data generation | The fake users: a JSON list of `{"user_id", "name", "email"}`. |
| `data/source/generated_threads.jsonl` | data generation | One JSON object per thread: `user_id`, `thread_id`, `subject`, `participants`, `messages` (each: `sender`, `recipients`, `timestamp`, `body`, `label`). `timestamp` is the email "Date" header format, e.g. `Tue, 13 Oct 2026 09:12:00 -0400`. Versioned with DVC (data-v1, fictional, ~300 KB): `dvc pull` fetches it; releases are listed in [`docs/data/versions.md`](docs/data/versions.md). |
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
- **Thread order:** `messages.jsonl` lists each thread's messages together, in thread order (position 0 first), as `preprocess` writes them. rag takes each message's previous message from this order for its reply excerpt.
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
- Collection metadata also records how it was embedded: `embedding_model`, `embedding_dimension`, `embedding_task_document` (`RETRIEVAL_DOCUMENT`), `embedding_task_query` (`RETRIEVAL_QUERY`), `embedding_token_limit`, and `chunks_over_token_limit` (always 0). Collections have no Chroma embedding function: `rag` and `api` always pass vectors.
- Two kinds of chunks, told apart by `chunk_type` in the metadata:
  - **`message`**: one per message; a body too long for the model is split into overlapping pieces. Chunk id: `<message_id>-<chunk index>` (index starts at 0). Text: `Subject: <subject>\nFrom: <sender display name>\nDate: <timestamp>`, then on every message but a thread's first, `\nReplying to <previous sender's display name>: <first ~200 characters of the previous message>`, then `\n\n<body>`. These first lines repeat on every piece; names fall back to the raw sender when there is no display name.
  - **`thread`**: one per thread (a thread too long for the model is split into windows of whole messages that overlap by one message). Chunk id: `thread-<thread_id>-<window index>`. Text: `Thread: <subject>\nParticipants: <names>\n\n` then one line per message: `- <sender>, <timestamp>: <first ~300 characters of the body>`.
- Message chunk metadata (all strings or ints, never null): `chunk_type` (`"message"`), `message_id`, `user_id`, `thread_id`, `sender`, `sender_name` (`""` if the sender has no display name), `timestamp`, `timestamp_epoch` (int Unix seconds with the UTC offset applied, `0` if `timestamp` is `""`; use it to sort, never the string), `source`, `subject`, `label`, `chunk_index` (int), `token_count` (int, counted by Vertex AI).
- Thread chunk metadata: `chunk_type` (`"thread"`), `user_id`, `thread_id`, `subject`, `source`, `message_ids` (comma-separated, in thread order), `message_count`, `timestamp` and `timestamp_epoch` (of the window's first message), `chunk_index` (window), `token_count`. No `label`.
- Embeddings: Vertex AI `gemini-embedding-001` in `us-central1` (settings `EMBEDDING_MODEL`, `GOOGLE_CLOUD_PROJECT`, `EMBEDDING_LOCATION`), through google-genai with application-default credentials. Stored chunks use task type `RETRIEVAL_DOCUMENT`, searches `RETRIEVAL_QUERY`. Over-limit text is rejected, never truncated. Indexing and search must use the same model; the api refuses a collection whose `embedding_model` differs.
- `rag` requires timestamps to be ISO 8601 with a UTC offset (or `""`), every message's `user_id` to be in `users.json`, and `user_id`s not to end with `_` (Chroma collection names must end with a letter or digit). Otherwise it exits non-zero without touching the index. A failed embedding call also stops it before the index is touched.
- If `data/processed/messages.jsonl` is missing, `rag` indexes `samples/` instead and logs a warning (`used_sample_data` is then `true`).
- Details: `src/rag/README.md`.

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

  It only searches `messages_<user_id>`, never another user's collection. Each result is one message (its best message chunk's `text` and `metadata`), never a thread chunk, and no message appears twice. Results come best first. `score` (higher is better, rounded to 3 places) is `0.5 × own + 0.5 × thread`: `own` is the query's similarity (`1 - cosine distance`) to the message's best message chunk, and `thread` is its similarity to the best thread chunk that contains the message (`own` again if there is none). The weight is `THREAD_WEIGHT` in `message_search.py` (identical in rag and api), chosen on the dev queries (see `docs/evidence/rag_experiments.md`). So `score` ranks the results of one search; it is not a raw cosine similarity, can't be compared with Milestone 2 scores (MiniLM, own similarity only), and isn't a calibrated relevance threshold. `k` is 1–20, `query` can't be blank, and the optional `label` (one of the six labels) limits results to that label. A `user_id` that doesn't match `^[a-z0-9_]+$` or has no collection returns `400` `{"detail": "unknown user"}`. Other invalid input returns `422`. `/search` returns `503` if ChromaDB is unreachable (also `/users`), if the user's collection was built with a different embedding model (the detail says to rerun rag), or if Vertex AI can't embed the query.

  See `src/api/README.md` for examples.

### Classifier

Labels live Gmail emails for the web app; it doesn't read the pipeline's files. Details and examples: `src/classifier/README.md`.

- `GET /health` → `{"status": "ok", "model": "gemini-3.8-flash", "rules_version": "1.5"}`. `rules_version` comes from `docs/data/labeling_rules.md`.
- `POST /classify` with `{"thread": [{"from", "date", "subject", "body", "to"?, "from_user"?}], "target_index": int, "message_id"?: str}` returns `{"label", "needs_response", "reason", "model", "rules_version", "latency_ms"}`. `label` is one of the six labels above. Earlier messages are context; messages after `target_index` are ignored. Errors (`422`, `502`, `503`, `500`) never include a label.
- The web app caches answers in `data/fixture.db` (table `classifications`), keyed by account (sha256 of the signed-in email) and Gmail message id, classifies again when `rules_version` changes, and deletes the account's rows on sign-out.
- The prompt includes `docs/data/labeling_rules.md` except its "Not adopted" and "Change log" sections (`docs/data/training_conflicts.md` is never sent); the classifier won't start if one of those headings is missing, so moving a section means updating `EXCLUDED_SECTIONS` in `src/classifier/prompt.py`.

Inside Docker, `rag` and `api` reach ChromaDB at `CHROMA_HOST=chromadb`, `CHROMA_PORT=8000`, the frontend reaches the API at `API_URL=http://api:8000`, and the classifier at `CLASSIFIER_URL=http://classifier:8002`.
