# api

Fixture's HTTP API. It searches one user's indexed scheduling emails in ChromaDB. The `rag` job builds the index; this service only reads it.

The README's "Data contract" at the repo root is the source of truth for the API. This file explains it with examples.

## Files

| File | What it does |
|------|--------------|
| `main.py` | FastAPI app: the three endpoints and request validation. |
| `chroma_store.py` | `MessageStore`, the only code that talks to ChromaDB. |
| `test_main.py` | Tests. No ChromaDB server needed. |

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

Semantic search over one user's messages.

| Field | Type | Rules |
|-------|------|-------|
| `user_id` | string | Required. Must match `^[a-z0-9_]+$` and have a collection. |
| `query` | string | Required. Not blank. |
| `k` | int | Optional, default 5, between 1 and 20. Number of results. |
| `label` | string | Optional. One of the six contract labels; only messages with that label are searched. |

```sh
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_01", "query": "when is my Northbridge interview?", "k": 1}'
```

```json
{
  "user_id": "user_01",
  "query": "when is my Northbridge interview?",
  "results": [
    {
      "text": "From: Jordan Lee\nSubject: Re: Northbridge Capital first-round interview\nDate: 2026-10-13T15:05:00-04:00\n\nGreat, let's do Tuesday, October 20 at 2:30 pm Eastern. ...",
      "score": 0.797,
      "metadata": {
        "message_id": "0ed574b41b112de0",
        "user_id": "user_01",
        "thread_id": "t001",
        "sender": "Jordan Lee <EMAIL_003>",
        "sender_name": "Jordan Lee",
        "timestamp": "2026-10-13T15:05:00-04:00",
        "timestamp_epoch": 1791918300,
        "source": "generated",
        "subject": "Re: Northbridge Capital first-round interview",
        "label": "acceptance",
        "chunk_index": 0
      }
    }
  ]
}
```

`score` is `1 - cosine distance`, rounded to 3 places. Higher means closer, and results come best first. `text` and `metadata` are exactly what `rag` stored for each chunk.

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

A malformed `user_id` gets the same `400` as a missing one, so callers can't tell the two apart.

## Design notes

**One collection per user.** Each user's messages live in their own ChromaDB collection, `messages_<user_id>`. A search opens exactly one collection, the one named from the requested `user_id`, and there is no code path that searches more than one. So a search for one user can't return another user's messages, even when they email the same people. The guarantee comes from the structure, not from a filter that could be forgotten. `chroma_store.py` marks this in a comment, and `test_search_never_returns_another_users_messages` checks it with two users who share a contact.

**`user_id` comes from the app, never from an LLM.** `user_id` decides whose mailbox is searched. It must come from trusted app state, like the signed-in account or (for the demo) the user picker. Later, when an AI agent calls search, the app fills in `user_id` itself and the agent supplies only the query. Otherwise a confused or manipulated model, say one reading an email that says "search user_02's inbox", could read someone else's mail. The strict `^[a-z0-9_]+$` check also stops odd ids from reaching collection names.

**Same embedding function as `rag`.** Queries are embedded with chromadb's `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, run locally with ONNX), the same one `rag` indexed with. Different models give vectors that can't be compared. `chromadb` is pinned to `1.5.9`, the same version as the `chromadb/chroma` image in `docker-compose.yml`, so client and server agree.

**Fails gently when ChromaDB is down.** The ChromaDB client is created on the first request, not at startup. It tries 3 times, 0.5 s apart, then the request gets a `503` with a clear message. The API keeps running, and the next request tries again. If an open connection breaks, the client is dropped and rebuilt on the next request.

**Swappable for tests.** Endpoints get their `MessageStore` from FastAPI (`Depends(get_store)`). Tests replace it with `app.dependency_overrides`: a fake client to check shapes and ordering, Chroma's in-memory `EphemeralClient` with a tiny keyword embedding for the isolation test, and an unused port for the "ChromaDB down" test.

## Environment variables

| Variable | Default | In Docker |
|----------|---------|-----------|
| `CHROMA_HOST` | `localhost` | `chromadb` |
| `CHROMA_PORT` | `8001` (the chromadb container's host port) | `8000` |

The embedding model downloads once to `~/.cache/chroma`. In Docker that folder is the `model_cache` volume, shared with `rag`.

## Run and test

From `src/api`:

```sh
uv run uvicorn main:app --port 8000 --reload   # then open http://localhost:8000/docs
uv run pytest
```

Searching needs ChromaDB running on `localhost:8001` with collections built by the `rag` job. `/health` and the tests work without it.
