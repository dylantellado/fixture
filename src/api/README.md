# api

Fixture's HTTP API. It searches one user's indexed scheduling emails in ChromaDB. The `rag` job builds the index; this service only reads it. Each search query is embedded with Vertex AI (`gemini-embedding-001`) in our own GCP project; queries and results are never logged.

The README's "Data contract" at the repo root is the source of truth for the API. This file explains it with examples.

## Files

| File | What it does |
|------|--------------|
| `main.py` | FastAPI app: the three endpoints and request validation. |
| `chroma_store.py` | `MessageStore`, the only code that talks to ChromaDB. |
| `embeddings.py` | Vertex AI embeddings and the model check. **Identical copy of `src/rag/embeddings.py`.** |
| `message_search.py` | The search that returns messages using thread context. **Identical copy of `src/rag/message_search.py`.** |
| `test_main.py` | Tests. No ChromaDB server and no network needed (Vertex AI is replaced by a tiny keyword embedding). |

## Endpoints

### `GET /health`

Is the API up? It doesn't check ChromaDB, so Docker's healthcheck passes even while the database is starting.

```sh
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

### `GET /users`

Users that have an indexed collection (`messages_<user_id>`), read from each collection's metadata. The web app uses this to fill its user picker. It reads only collection names and metadata, never messages.

```sh
curl http://localhost:8000/users
```

```json
[
  {"user_id": "user_01", "name": "Priya Shah", "indexed_at": "2026-10-20T01:20:48+00:00"},
  {"user_id": "user_02", "name": "Marcus Bell", "indexed_at": "2026-10-20T01:20:48+00:00"}
]
```

### `POST /search`

Semantic search over one user's messages. Results are always messages (one per message), never whole threads.

| Field | Type | Rules |
|-------|------|-------|
| `user_id` | string | Required. Must match `^[a-z0-9_]+$` and have a collection. |
| `query` | string | Required. Not blank. |
| `k` | int | Optional, default 5, between 1 and 20. Number of results. |
| `label` | string | Optional. One of the six contract labels; only messages with that label are returned. |

```sh
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_01", "query": "When and where do I meet my career advisor?", "k": 1}'
```

```json
{
  "user_id": "user_01",
  "query": "When and where do I meet my career advisor?",
  "results": [
    {
      "text": "Subject: Advising appointment\nFrom: Dana Whitfield\nDate: 2026-09-03T14:02:00-04:00\nReplying to Priya Shah: Hi Dana, I'm an economics junior recruiting for investment banking summer analyst roles this fall. ...\n\nHi Priya,\n\nLovely to hear from you, and welcome back. I'd be glad to meet. I have two openings next Tuesday, September 8: 3:00 or 3:30 pm Eastern. ...",
      "score": 0.688,
      "metadata": {
        "chunk_type": "message",
        "message_id": "1a61982811036a4a",
        "user_id": "user_01",
        "thread_id": "t002",
        "sender": "Dana Whitfield <EMAIL_023>",
        "sender_name": "Dana Whitfield",
        "timestamp": "2026-09-03T14:02:00-04:00",
        "timestamp_epoch": 1788458520,
        "source": "generated",
        "subject": "Advising appointment",
        "label": "proposed_times",
        "chunk_index": 0,
        "token_count": 203
      }
    }
  ]
}
```

(`text` is shortened here; the full response is in `docs/evidence/api_search_response.json`.)

`score` is `0.5 × own + 0.5 × thread`, rounded to 3 places: `own` is the query's similarity (`1 - cosine distance`) to the message's best message chunk, `thread` its similarity to the best thread chunk containing the message (`own` if there is none); the weight is `THREAD_WEIGHT` in `message_search.py`. Higher means closer, and results come best first. It ranks one search's results; it isn't a raw cosine similarity or a calibrated threshold (the Data contract in the root README has the full definition). `text` and `metadata` are exactly what `rag` stored for the message's best chunk: the first lines are the thread subject, sender and date, and on a reply, `Replying to <sender>:` with the start of the previous email (context for search; the web app hides it).

With a label filter:

```sh
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_02", "query": "move the meeting", "label": "reschedule"}'
```

### Errors

| Status | When | Body |
|--------|------|------|
| `400` | `user_id` is malformed or has no collection | `{"detail": "unknown user"}` |
| `422` | Blank or missing `query`, `k` outside 1–20, or an unknown `label` | FastAPI's validation details |
| `503` | ChromaDB can't be reached | `{"detail": "The search database (ChromaDB at localhost:8001) is not reachable. ..."}` |
| `503` | The user's collection was built with a different embedding model | `{"detail": "Collection messages_user_01 was built with embedding model 'all-MiniLM-L6-v2', but this service uses 'gemini-embedding-001'. Rerun rag to rebuild the index with the current model."}` |
| `503` | Vertex AI couldn't embed the query (no credentials, rate limited after retries, ...) | `{"detail": "Couldn't embed 1 text(s) with gemini-embedding-001: Vertex AI returned 429 RESOURCE_EXHAUSTED (rate limited, and still limited after retrying)"}` |

A malformed `user_id` gets the same `400` as a missing one, so callers can't tell the two apart.

## Design notes

**One collection per user.** Each user's messages live in their own ChromaDB collection, `messages_<user_id>`. A search opens exactly one collection, the one named from the requested `user_id`, and there is no code path that searches more than one. So a search for one user can't return another user's messages, even when they email the same people. The guarantee comes from the structure, not from a filter that could be forgotten. `chroma_store.py` marks this in a comment, and `test_search_never_returns_another_users_messages` checks it with two users who share a contact.

**`user_id` comes from the app, never from an LLM.** `user_id` decides whose mailbox is searched. It must come from trusted app state, like the signed-in account or (for the demo) the user picker. Later, when an AI agent calls search, the app fills in `user_id` itself and the agent supplies only the query. Otherwise a confused or manipulated model, say one reading an email that says "search user_02's inbox", could read someone else's mail. The strict `^[a-z0-9_]+$` check also stops odd ids from reaching collection names.

**Same embedding model as `rag`, checked on every search.** Queries are embedded with Vertex AI through `embeddings.py`, an identical copy of rag's (a test fails if the copies differ), using the `RETRIEVAL_QUERY` task type (rag stores chunks with `RETRIEVAL_DOCUMENT`). Before embedding, the api compares the collection's `embedding_model` metadata with its own `EMBEDDING_MODEL` and refuses a mismatch with a `503` saying to rerun rag, because vectors from different models can't be compared. The api gives Chroma the query vector itself; collections have no Chroma embedding function, so nothing runs Chroma's default local model. `chromadb` is pinned to `1.5.9`, the same version as the `chromadb/chroma` image in `docker-compose.yml`, so client and server agree.

**Messages, with thread context.** `message_search.py` (identical in rag) looks at the message chunks closest to the query and at the best-matching thread chunks, whose messages become candidates too. Each message's score averages its own similarity and its thread's, so a short reply in the thread that matches the question can rank high. Results are deduplicated by `message_id` and are never thread chunks. See `src/rag/README.md` for the details and `docs/evidence/rag_experiments.md` for the measurements.

**Vertex AI is called lazily.** The client is created on the first search, so the api starts and `/health` works without credentials. An unknown user or a mismatched index is rejected before anything is sent to Vertex AI.

**Fails gently when ChromaDB is down.** The ChromaDB client is created on the first request, not at startup. It tries 3 times, 0.5 s apart, then the request gets a `503` with a clear message. The API keeps running, and the next request tries again. If an open connection breaks, the client is dropped and rebuilt on the next request.

**Swappable for tests.** Endpoints get their `MessageStore` from FastAPI (`Depends(get_store)`). Tests replace it with `app.dependency_overrides`: a fake client to check which collections are opened, Chroma's in-memory `EphemeralClient` with a tiny keyword embedding (standing in for Vertex AI) for search results and the isolation test, and an unused port for the "ChromaDB down" test.

## Environment variables

| Variable | Default | In Docker |
|----------|---------|-----------|
| `CHROMA_HOST` | `localhost` | `chromadb` |
| `CHROMA_PORT` | `8001` (the chromadb container's host port) | `8000` |
| `GOOGLE_CLOUD_PROJECT` | `fixture-ac215-96dhbm` | same |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | same (must match the model rag indexed with) |
| `EMBEDDING_LOCATION` | `us-central1` | same |

Credentials are Google application-default credentials (`gcloud auth application-default login`); Docker mounts `~/.config/gcloud` read-only. No API keys and nothing in `.env`.

## Run and test

From `src/api`, after `gcloud auth application-default login` once:

```sh
uv run uvicorn main:app --port 8000 --reload   # then open http://localhost:8000/docs
uv run pytest
```

Searching needs ChromaDB running on `localhost:8001` with collections built by the `rag` job (with the same embedding model), and credentials for Vertex AI. `/health`, `/users` and the tests work without credentials.
