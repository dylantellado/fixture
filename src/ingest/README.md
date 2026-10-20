# ingest

First step of the data pipeline. Collects email threads, checks that every one
matches the Data contract (see the repo README), removes duplicates, and writes
a clean copy for `preprocess`.

## Inputs and outputs

| | Path (inside `DATA_DIR`, `/data` in Docker) | |
|---|---|---|
| reads | `source/users.json` | the users (`user_id`, `name`, `email`) |
| reads | `source/generated_threads.jsonl` | one thread per line, source format |
| writes | `raw/threads.jsonl` | same shape, validated, deduplicated, sorted by `(user_id, thread_id)`, plus `source` and `provenance` (file, line, sha256 of the thread's content) |

The run log lists counts per user and the path and sha256 of every file read and written.

## What it does

1. **Collect.** A *collector* supplies users and threads. `FileCollector` reads the
   files above. `LLMCollector` is a placeholder for generating data with an LLM API
   later. Every collector returns the same shape, so the steps below don't change.
2. **Validate** each thread with `validation.py`: required fields, a known and
   well-formed `user_id`, no message claiming a different user, `Name <address>`
   senders and recipients, parseable timestamps in time order, allowed labels, and
   everyone in the thread listed in `participants`.
3. **Deduplicate.** An identical thread twice in one inbox is kept once. The same
   `thread_id` with different content is an error. The same email in two users'
   inboxes (a mailing list) is **kept for both**, since each user's data stays separate.
   Exact repeats of a message within a thread are dropped.
4. **Write** sorted output through a temp file and a rename, so the same input
   always gives a byte-identical file and a crash never leaves a half-written one.

**If any thread is invalid, ingest writes nothing and exits 1**, so `preprocess`
(which waits for ingest to succeed) never runs on bad data. For the generated corpus
a bad record means a generation bug. For real mail later, we may switch to
skipping bad records and reporting them.

If the source files are missing, it exits 1 and says to run `dvc pull`.

## Run it

```sh
# whole pipeline step, from the repo root
docker compose up --build ingest

# locally, from src/ingest (reads and writes the repo's data/ folder)
uv run python main.py

# check a thread file against the contract (and, with --generated, the fake-corpus rules)
uv run python validate.py ../../data/source/generated_threads.jsonl --users ../../data/source/users.json --generated

uv run pytest
```

## Files

- `main.py`: the ingest job (validate, deduplicate, provenance, safe write)
- `collectors.py`: `FileCollector` and the `LLMCollector` placeholder
- `validation.py`: the contract checks, shared by `main.py` and `validate.py`
- `validate.py`: command-line checker, used while writing the corpus
- `google_auth.py`, `list_events.py`: the earlier Google Calendar check (unchanged; `uv run python list_events.py`)
- `test_ingest.py`, `test_validation.py`: tests
