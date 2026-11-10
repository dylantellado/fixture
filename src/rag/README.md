# rag

A one-shot job that makes each user's email searchable. It reads the processed
messages, turns each thread into chunks (one per message, with thread context,
plus one for the thread as a whole), embeds them with Vertex AI, and loads each
user's chunks into their own ChromaDB collection. Then it exits: 0 on success,
1 on any problem (so `docker compose` stops the pipeline).

The `api` service searches these collections; it doesn't import this code, but
it has identical copies of `embeddings.py` and `message_search.py` (tests in
both services fail if the copies differ). The repo README's "Data contract" is
the source of truth for the input and output formats.

**Privacy:** indexing sends the indexed email text (today, the fictional data-v1
corpus) to Vertex AI in our own GCP project (`fixture-ac215-96dhbm`). Email
text is never logged; logs hold counts, timings, model ids and message ids.

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
3. **Chunk** every thread (see below).
4. **Embed** every chunk with Vertex AI (`RETRIEVAL_DOCUMENT`), in batches, with
   retries on rate limits. Any failure stops the run before ChromaDB is touched,
   so the existing index is left alone.
5. **Rebuild the index.** For every user in `users.json`, delete their
   collection, create it again, and upsert their chunks with their vectors in
   batches of 100. Then delete any `messages_*` collection whose user is gone
   from `users.json`. Collections with other names are never touched.

It logs (with timestamps) which input was used and its sha256, messages and
chunks per user, how many chunks and tokens were embedded and how long it took,
chunks over the token limit (always 0), and final collection sizes.

## Chunks

Each collection holds two kinds of chunks (metadata `chunk_type`).

**Message chunks**, one per message (a body too long for one chunk is split
into overlapping pieces, each with the same first lines):

```text
Subject: Larkmoor Capital: Superday invitation
From: Priya Shah
Date: 2026-10-08T18:30:00-04:00
Replying to Tess Navarro: Hi Priya, Congratulations! Please choose one of the following Superday start times (Eastern): 1. Thursday, October 15, 9:00 am 2. Friday, October 16, 9:00 am 3. Friday, October 16, 1:00 pm Each is a…

Hi Tess,

Thank you. I'd like Friday, October 16 at 9:00 am.

Best,
Priya
```

The `Replying to` line quotes the first ~200 characters of the previous message
in the thread (none on the first message). It is what lets "When is my Larkmoor
superday?" find a reply that says only "Friday, October 16 at 9:00 am".

**Thread chunks**, one per thread:

```text
Thread: Larkmoor Capital: Superday invitation
Participants: Jordan Lee, Priya Shah, Tess Navarro

- Jordan Lee, 2026-10-08T17:20:00-04:00: Hi Priya, Thank you for your time this morning. I'm delighted to let you know that the team would like you to join our Superday in New York, which we're holding on Thursday, October 15 and Friday, October 16. It's a half day of in-person interviews at our office. I'm copying Tess Navarro, who will…
- Tess Navarro, 2026-10-08T17:52:00-04:00: Hi Priya, Congratulations! Please choose one of the following Superday start times (Eastern): 1. Thursday, October 15, 9:00 am 2. Friday, October 16, 9:00 am 3. Friday, October 16, 1:00 pm Each is a half day at our New York office, and we'll reimburse train travel from Boston. Kindly let me know…
- Priya Shah, 2026-10-08T18:30:00-04:00: Hi Tess, Thank you. I'd like Friday, October 16 at 9:00 am. Best, Priya
```

Each line shows a message's first ~300 characters. A thread too long for one
chunk is split into windows of whole messages that overlap by one message, each
repeating the subject and participants. With today's limit every data-v1 thread
fits in one chunk (the longest is about 1,550 characters, 525 tokens).

`From:` and `Replying to` show the display name, or the raw sender (e.g.
`<EMAIL_005>`) if there is none. `EMAIL_###`/`PHONE_###` placeholders are opaque
text and never parsed. A thread's messages are taken in file order, which is
thread order (preprocess writes them by position).

## Search (`message_search.py`)

Searches return **messages, never threads**:

1. **Direct hits:** the 3 × k message chunks closest to the query.
2. **Thread hits:** the 3 thread chunks closest to the query. Every message in
   those threads becomes a candidate too.
3. Each candidate gets its own similarity (its best message chunk) and its
   thread's (the best thread chunk containing it), both `1 - cosine distance`.
4. **Score = the average of the two.** Within a thread, messages keep the order
   of their own similarity; a message in a thread that matches the question
   moves up.
5. One result per message (its best chunk), best first, top k. The optional
   label filter applies to every candidate.

Why the thread similarity counts in the score: if only each message's own
similarity counted, messages pulled in through a thread could never rank above
the direct hits (those are, by definition, the most similar messages), so thread
chunks would change nothing. The dev queries confirmed a small gain from the
average over own similarity alone (see `docs/evidence/rag_experiments.md`).

## Design choices, and why

| Choice | Why |
|---|---|
| **Vertex AI `gemini-embedding-001`** in `us-central1` | Much better retrieval than the local all-MiniLM-L6-v2 (dev recall@5 0.65 → 0.80 with the same chunks) and 2,048 tokens of input instead of 256. It supports separate document and query task types and many texts per request. `gemini-embedding-2` was also tested: it only answers in the `global` location, ignores `task_type`, and takes one text per request. |
| **`RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY` task types** | The model embeds stored text and questions differently so that they match each other. |
| **No silent truncation, no fallback** | Requests send `auto_truncate=False`, so an over-limit text is an error instead of being cut. Any embedding failure stops the run with a clear message; vectors from another model can't be mixed in. |
| **Chunks sized at 2 characters per token** (at most 4,096 characters) | Measured on data-v1: 3.1 characters per token on average, 2.1 for the densest chunks (dates, times, names, placeholders). |
| **Thread context** (reply excerpt + thread chunks) | One chunk per message ranks short replies low ("Friday works" says nothing on its own). Measured on the dev queries: recall@5 0.80 → 0.88 with Vertex. |
| **rag computes vectors itself and gives them to Chroma** | Collections have no Chroma embedding function, so Chroma never embeds anything (no hidden default model), and batching, retries and token counts are under our control. |
| **Model recorded in collection metadata** | The api (and `query.py`, `check_retrieval.py`) refuses a collection built with a different model and says to rerun rag. |
| **Cosine distance** | Compares the direction of two embeddings, the standard way to compare text embeddings. Chroma's default is l2, so we set it explicitly. |
| **One collection per user** (`messages_<user_id>`) | Privacy by construction: a search for one user physically can't return another user's emails, even if they share a contact (tested). No risk of a forgotten filter. |
| **Rebuild from scratch every run** | Simple and always correct: if the data is regenerated, a message is removed, or placeholders are renumbered, nothing stale lingers. A full rebuild of data-v1 takes about 20 seconds. |
| **Stable chunk ids** | `<message_id>-<chunk index>` and `thread-<thread_id>-<window>`: the same data always gives the same ids. |
| **`timestamp_epoch` in metadata** | Timestamps carry different UTC offsets, so sorting the strings gives the wrong order. Integer Unix seconds sort and filter correctly. |

## Outputs

One ChromaDB collection per user, named `messages_<user_id>`, using cosine
distance and no Chroma embedding function.

**Collection metadata** (which data and which model each collection was built from):

| Key | Example | Notes |
|---|---|---|
| `user_id` | `user_01` | |
| `user_name` | `Priya Shah` | From `users.json`; the api's user picker shows this. |
| `indexed_at` | `2026-11-09T20:09:48+00:00` | UTC time of the run. |
| `input_path` | `/data/processed/messages.jsonl` | The messages file that was indexed. |
| `input_sha256` | `542030...` | sha256 of that file. |
| `used_sample_data` | `false` | `true` when the job fell back to `samples/`. |
| `manifest_git_commit` | `4379eb1...` | From `manifest.json`; `""` if there is none. |
| `manifest_created_at` | `2026-11-09T20:09:27Z` | From `manifest.json`; `""` if there is none. |
| `embedding_model` | `gemini-embedding-001` | The api refuses the collection if it uses another model. |
| `embedding_dimension` | `3072` | Length of each vector. |
| `embedding_task_document` | `RETRIEVAL_DOCUMENT` | Task type used for the stored chunks. |
| `embedding_task_query` | `RETRIEVAL_QUERY` | Task type searches must use. |
| `embedding_token_limit` | `2048` | The model's input limit. |
| `chunks_over_token_limit` | `0` | This user's chunks over the limit (Vertex AI would have rejected them). |

**Message chunk metadata** (all strings or ints, never `None`):

| Key | Type | Notes |
|---|---|---|
| `chunk_type` | str | `"message"` |
| `message_id` | str | |
| `user_id` | str | |
| `thread_id` | str | |
| `sender` | str | As in the message, e.g. `Jordan Lee <EMAIL_003>`. |
| `sender_name` | str | Display name only, e.g. `Jordan Lee`; `""` if the sender has none (`<EMAIL_005>`). |
| `timestamp` | str | ISO 8601 as in the message. |
| `timestamp_epoch` | int | Unix seconds with the UTC offset applied; `0` if the timestamp is `""`. |
| `source` | str | |
| `subject` | str | |
| `label` | str | One of the six labels. |
| `chunk_index` | int | 0 for the first (usually only) chunk of a message. |
| `token_count` | int | Tokens Vertex AI counted for this chunk. |

**Thread chunk metadata:** `chunk_type` (`"thread"`), `user_id`, `thread_id`,
`subject`, `source`, `message_ids` (the window's message ids, comma-separated,
since Chroma metadata can't hold lists), `message_count`, `timestamp` and
`timestamp_epoch` (of the window's first message), `chunk_index` (window number),
`token_count`. Thread chunks have no `label` or `sender`.

## Environment variables

| Variable | Default (laptop) | In Docker |
|---|---|---|
| `DATA_DIR` | `<repo>/data` | `/data` |
| `SAMPLES_DIR` | `<repo>/samples` | `/samples` |
| `CHROMA_HOST` | `localhost` | `chromadb` |
| `CHROMA_PORT` | `8001` (host port) | `8000` |
| `GOOGLE_CLOUD_PROJECT` | `fixture-ac215-96dhbm` | same |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | same (must match the api) |
| `EMBEDDING_LOCATION` | `us-central1` | same |

Credentials are Google application-default credentials, never an API key or a
`.env` value. Other settings (chunk sizes, reply excerpt length, batch sizes,
retries) are constants in `config.py` and `embeddings.py`.

## Files

| File | What it does |
|---|---|
| `main.py` | The job: runs the five steps above and logs them. |
| `config.py` | Settings: paths, ChromaDB, embedding settings, chunk sizes. |
| `inputs.py` | Finds, loads, and validates the input files. |
| `chunking.py` | Builds message and thread chunks: text, id, and metadata. |
| `embeddings.py` | Vertex AI embeddings: batching, retries, task types, model check. **Identical copy in `src/api`.** |
| `message_search.py` | The search that returns messages using thread context. **Identical copy in `src/api`.** |
| `index.py` | Connects to ChromaDB (with retry), rebuilds collections, opens one (checking the model), searches. |
| `query.py` | Command-line search tool. |
| `check_retrieval.py` | Scores retrieval on `retrieval_cases.json` and logs experiments. |
| `retrieval_cases.json` | 47 example queries with the messages that answer them, split into dev and test. |
| `tests/` | Tests (see below). |

## How to run

You need Google application-default credentials once per machine:

```sh
gcloud auth application-default login
```

With Docker, from the repo root (Docker mounts `~/.config/gcloud` read-only):

```sh
docker compose up -d --build chromadb   # vector database, keeps running
docker compose up --build rag           # runs ingest -> preprocess -> rag, then exits
```

On a laptop without Docker, from `src/rag` (ChromaDB must be running, e.g. the
`chromadb` service above, or `uv run chroma run --path /tmp/chroma --port 8001`):

```sh
uv run main.py
```

## How to query

From `src/rag`, after the job has run:

```sh
uv run python query.py --user user_01 "When is my Larkmoor superday?" --k 5
uv run python query.py --user user_02 "Did my interview get moved?" --label reschedule
uv run python query.py --user user_01 "When and where do I meet my career advisor?" --markdown > ../../docs/evidence/retrieval_example.md
```

`--label` limits the search to one label. `--markdown` prints the query, the
user, which data and model were indexed, and each result (score, sender, date,
subject, label, text) for evidence files. A user without a collection, or a
collection built with another model, gets a clear message and exit code 1.

## How to check retrieval

`retrieval_cases.json` holds 47 queries over `user_01`–`user_04`: Will's 15 from
`docs/data/corpus_notes.md` plus 32 added in Milestone 3 (names, dates, moved
meetings, preferences, locations, time zones, assistants, short replies), each
with the `message_id`s that answer it, checked by reading data-v1.

Each case is `dev` (32) or `test` (15). The test cases were drawn with
`random.Random(215)` over the sorted case names before any experiment ran, and a
test checks that the committed split still matches. Build and tune on dev only;
test is reported, never tuned on. The console shows per-query lines for dev only.

For each split it reports recall@5 (share of expected messages in the top 5),
MRR (1 / rank of the first expected message, 0 if none in the top 5),
full / partial / miss counts, and results from another user's mailbox, which
must always be 0 (the script exits non-zero otherwise).

```sh
uv run python check_retrieval.py                                  # dev, per query
uv run python check_retrieval.py --split all --record "my change" # also log a row per split
uv run python check_retrieval.py --split all --markdown > ../../docs/evidence/retrieval_check.md
```

`--record` appends one row per split to `docs/evidence/rag_experiments.md`
(variant, model, split, metrics, chunk count, chunks over the token limit, git
commit, date). Rows are never edited; they are the history of what each setup
scored.

## Tests

```sh
uv run pytest
```

No test calls Vertex AI or needs a network: the embedding call is mocked or
replaced by a tiny bag-of-words embedding.

- `test_chunking.py`: reply excerpt and header, long bodies split within the limit, thread chunks, windows that overlap and always move forward, thread grouping in file order.
- `test_metadata.py`: every field present and never `None`, `timestamp_epoch` across offsets, empty `sender_name`.
- `test_inputs.py`: sample fallback and each validation failure.
- `test_embeddings.py`: settings from the environment, task types, batching, retries with backoff, permanent errors, no email text in errors, missing credentials, merged answers rejected, model mismatch refused, the api copy is identical, and no code uses Chroma's default ONNX embedder.
- `test_message_search.py`: thread-to-message expansion, the score formula, dedupe by message id, never a thread chunk in the results, label filter, the api copy is identical.
- `test_index.py`: indexing into an in-memory ChromaDB: one collection per user, metadata, reruns don't duplicate, removed messages and users disappear, bad input or a failed embedding leaves the index alone, token counts, the model check, and the isolation test (searching user_01 for the contact shared with user_02 returns only user_01's emails).
- `test_query.py`: the query tool's output and argument checks.
- `test_check_retrieval.py`: scoring (recall, MRR, statuses), the seeded split, the experiment log, the evidence file, and the committed cases.
