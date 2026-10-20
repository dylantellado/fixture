# rag

A one-shot job that makes each user's email searchable. It reads the processed
messages, turns each message into one or more chunks, embeds them, and loads
each user's chunks into their own ChromaDB collection. Then it exits: 0 on
success, 1 on any problem (so `docker compose` stops the pipeline).

The `api` service searches these collections; it doesn't import this code.
The repo README's "Data contract" is the source of truth for the input and
output formats.

## What it does, step by step

1. **Find the input.** `DATA_DIR/processed/messages.jsonl` and
   `DATA_DIR/source/users.json` (plus `DATA_DIR/processed/manifest.json` if
   it exists). If `messages.jsonl` is missing, it falls back to
   `SAMPLES_DIR/messages_sample.jsonl` and `SAMPLES_DIR/users.json` and logs a
   `SAMPLE DATA USED` warning.
2. **Validate before touching ChromaDB.** Every message has all contract
   fields with the right types (no nulls), `user_id` matches `^[a-z0-9_]+$`
   and is in `users.json`, `label` is one of the six labels, `message_id`s are
   unique, and timestamps are ISO 8601 with a UTC offset (or `""`). Any
   problem stops the run with a list of what's wrong, and the existing index
   is left alone.
3. **Chunk** every message (see below).
4. **Rebuild the index.** For every user in `users.json`, delete their
   collection, create it again, and upsert their chunks in batches of 100.
   Then delete any `messages_*` collection whose user is gone from
   `users.json`. Collections with other names are never touched.

It logs (with timestamps) which input was used and its sha256, messages and
chunks per user, final collection sizes, and the time taken.

## Design choices, and why

| Choice | Why |
|---|---|
| **One chunk per message** | A scheduling email is short and about one thing, so a whole message is the natural unit to retrieve. Search results map 1:1 to emails the user recognizes. |
| **Header in the chunk text** (`From:`, `Subject:`, `Date:` before the body) | Bodies often don't repeat who sent them or what they're about. With the header, "what did Jordan Lee say?" or "Northbridge interview" matches the right emails. |
| **Long bodies split** at ~1,000 characters with ~150 characters of overlap, header repeated on each piece | MiniLM reads at most 256 tokens (about 1,000 characters) and silently ignores the rest. The overlap keeps a sentence that straddles a cut whole in one piece, and the repeated header keeps every piece findable by sender and subject. Cuts happen at spaces so words stay whole. |
| **all-MiniLM-L6-v2** via Chroma's built-in default embedding function | Small, fast, runs locally with ONNX: no API key, no cost, works offline once downloaded (~80 MB, cached in the `model_cache` volume). Good enough for short emails; easy to swap later in `config.py`. |
| **Cosine distance** | Compares the direction of two embeddings, which is the standard way to compare sentence embeddings. Chroma's default is l2, so we set it explicitly. Score shown to users = `1 - distance` (higher is closer). |
| **One collection per user** (`messages_<user_id>`) | Privacy by construction: a search for one user physically can't return another user's emails, even if they share a contact (tested). No risk of a forgotten filter. |
| **Rebuild from scratch every run** | Simple and always correct: if the data is regenerated, a message is removed, or placeholders are renumbered, nothing stale lingers. Our data is small, so a full rebuild takes seconds. |
| **Stable chunk ids** (`<message_id>-<chunk index>`) | `message_id` is deterministic (data contract), so the same data always gives the same ids. Useful for tests and for linking a result back to its message. |
| **`timestamp_epoch` in metadata** | Timestamps carry different UTC offsets, so sorting the strings gives the wrong order. Integer Unix seconds sort and filter correctly. |

## Outputs

One ChromaDB collection per user, named `messages_<user_id>`, using cosine distance.

**Collection metadata** (records which data each collection was built from):

| Key | Example | Notes |
|---|---|---|
| `user_id` | `user_01` | |
| `user_name` | `Priya Shah` | From `users.json`; the api's user picker shows this. |
| `indexed_at` | `2026-10-20T01:20:48+00:00` | UTC time of the run. |
| `input_path` | `/samples/messages_sample.jsonl` | The messages file that was indexed. |
| `input_sha256` | `9d2e18...` | sha256 of that file. |
| `used_sample_data` | `true` | `true` when the job fell back to `samples/`. |
| `manifest_git_commit` | `eed41cd...` | From `manifest.json`; `""` if there is none. |
| `manifest_created_at` | `2026-10-19T14:00:00Z` | From `manifest.json`; `""` if there is none. |
| `embedding_model` | `all-MiniLM-L6-v2` | |

**Chunk metadata** (all strings or ints, never `None`):

| Key | Type | Notes |
|---|---|---|
| `message_id` | str | |
| `user_id` | str | |
| `thread_id` | str | |
| `sender` | str | As in the message, e.g. `Jordan Lee <EMAIL_003>`. |
| `sender_name` | str | Display name only, e.g. `Jordan Lee`; `""` if the sender has none (`<EMAIL_005>`). |
| `timestamp` | str | ISO 8601 as in the message. |
| `timestamp_epoch` | int | Unix seconds with the UTC offset applied; `0` if the timestamp is `""`. Use this to sort or filter by date. |
| `source` | str | |
| `subject` | str | |
| `label` | str | One of the six labels. |
| `chunk_index` | int | 0 for the first (usually only) chunk of a message. |

**Chunk text:**

```text
From: Jordan Lee
Subject: Re: Northbridge Capital first-round interview
Date: 2026-10-13T15:05:00-04:00

Great, let's do Tuesday, October 20 at 2:30 pm Eastern. ...
```

`From:` shows the display name, or the raw sender (e.g. `<EMAIL_005>`) if
there is none. `EMAIL_###`/`PHONE_###` placeholders are treated as opaque
text and never parsed.

## For the api: how to search these collections

- Open the collection with the **same embedding function**:
  `chromadb.utils.embedding_functions.DefaultEmbeddingFunction()` from
  `chromadb==1.5.9` (all-MiniLM-L6-v2). For example
  `client.get_collection("messages_user_01", embedding_function=DefaultEmbeddingFunction())`.
  A different model would produce vectors that don't match the stored ones.
- Score = `1 - distance` from `collection.query(...)`.
- An unknown user has no collection: `get_collection` raises
  `chromadb.errors.NotFoundError`, which the api turns into a `400`.
- The user picker can read `user_name` from each `messages_*` collection's metadata.
- If you ever create a collection, pass a fresh `configuration` dict each
  time: Chroma writes the embedding function into the dict it's given.

## Environment variables

| Variable | Default (laptop) | In Docker |
|---|---|---|
| `DATA_DIR` | `<repo>/data` | `/data` |
| `SAMPLES_DIR` | `<repo>/samples` | `/samples` |
| `CHROMA_HOST` | `localhost` | `chromadb` |
| `CHROMA_PORT` | `8001` (host port) | `8000` |

Other settings (chunk size, overlap, batch size, model, retry) are constants in `config.py`.

## Files

| File | What it does |
|---|---|
| `main.py` | The job: runs the four steps above and logs them. |
| `config.py` | Settings and the embedding function. |
| `inputs.py` | Finds, loads, and validates the input files. |
| `chunking.py` | Builds each chunk's text, id, and metadata. |
| `index.py` | Connects to ChromaDB (with retry), rebuilds collections, searches. |
| `query.py` | Command-line search tool. |
| `check_retrieval.py` | Checks retrieval quality and isolation on the example queries in `retrieval_cases.json`. |
| `tests/` | Tests (see below). |

## How to run

With Docker, from the repo root:

```sh
docker compose up -d --build chromadb   # vector database, keeps running
docker compose up --build rag           # runs ingest -> preprocess -> rag, then exits
```

On a laptop, from `src/rag` (ChromaDB must be running, e.g. the command above):

```sh
uv run main.py
```

## How to query

From `src/rag`, after the job has run:

```sh
uv run python query.py --user user_01 "When is my Northbridge interview?" --k 5
uv run python query.py --user user_02 "Did my interview get moved?" --label reschedule
uv run python query.py --user user_01 "When is my Northbridge interview?" --markdown > ../../docs/evidence/retrieval_example.md
```

`--label` limits the search to one label. `--markdown` prints the query, the
user, which data was indexed, and each result (score, sender, date, subject,
label, text) for evidence files. A user without a collection gets a clear
message and exit code 1.

## How to check retrieval

`check_retrieval.py` runs the 15 example queries from `docs/data/corpus_notes.md`
(copied into `retrieval_cases.json`) against the data-v1 index. For each one it
reports where the messages that answer it rank in the user's top 5, and how
many results came from another user's mailbox. That must always be 0, and the
script exits non-zero if it isn't.

```sh
uv run python check_retrieval.py
uv run python check_retrieval.py --markdown > ../../docs/evidence/retrieval_check.md
```

## Tests

```sh
uv run pytest
```

- `test_chunking.py`: short and long bodies, overlap, header on every piece, stable ids.
- `test_metadata.py`: every field present and never `None`, `timestamp_epoch` across offsets, empty `sender_name`.
- `test_inputs.py`: sample fallback and each validation failure.
- `test_index.py`: indexing into an in-memory ChromaDB with a tiny fake embedding function (fast, offline): one collection per user, reruns don't duplicate, removed messages and users disappear, bad input leaves the index alone, and the isolation test (searching user_01 for the contact shared with user_02 returns only user_01's emails).
- `test_query.py`: the query tool's output and argument checks.
- `test_check_retrieval.py`: the retrieval check's ranking, isolation count, summary, and the committed example queries.
- `test_real_model.py`: one search with the real MiniLM model; skipped if the model can't be downloaded.
