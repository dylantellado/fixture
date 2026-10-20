# Evidence

Proof that the Milestone 2 pipeline runs end to end, with real inputs and outputs.

## Full pipeline run (one command)

From a clean state (`docker compose down -v`), at commit `0c1bbe3`, with data-v1 in `data/source/`:

```sh
GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build -d
```

All six services came up in order: `ingest` → `preprocess` → `rag` ran once and exited 0, `chromadb` was healthy, then `api` (healthy) and `frontend` started.

| File | What it shows |
|------|---------------|
| [`full_pipeline_run.log`](full_pipeline_run.log) | Logs from every service for that run: input and output sha256s, per-user counts, chunking, indexing into 4 collections, and the api and web app serving requests. One line was removed: rag's download progress bar for the embedding model, which is unreadable as text. |
| [`compose_ps.txt`](compose_ps.txt) | `docker compose ps -a` right after the run: the three jobs `Exited (0)`, and `chromadb`, `api` and `frontend` up. |
| [`api_search_response.json`](api_search_response.json) | A real `POST /search` response from the running api, for `user_01`: "When and where do I meet my career advisor?" (k=3). |
| [`../mockup/search_page.png`](../mockup/search_page.png) | The web app's "Search past threads" page with the same query, served by the `frontend` container and calling the `api` container. |

In the log, `172.21.0.4` requests are the `frontend` container calling the `api` (the app's UI-to-backend interaction). The `151.101.128.223` requests are the checks we sent from the laptop with `curl` and the browser. Docker Desktop reported them under that address instead of `127.0.0.1`.

## Data version

Every stage logs the sha256 of what it read and wrote, so each container's data version can be traced:

| Stage | Reads | Writes |
|-------|-------|--------|
| `ingest` | `users.json` `f112d23c…`, `generated_threads.jsonl` `eb2efe27…` | `data/raw/threads.jsonl` `798a15d5…` |
| `preprocess` | `threads.jsonl` `798a15d5…` | `data/processed/messages.jsonl` `3f9eb186…` and `manifest.json` (with `git_commit`) |
| `rag` | `messages.jsonl` `3f9eb186…` | `messages_user_01` … `messages_user_04` in ChromaDB; each collection's metadata stores `input_sha256` `3f9eb186…` and `indexed_at` |

Result: 4 users, 160 threads, 377 messages, 390 chunks.

## Other files

| File | What it shows |
|------|---------------|
| [`pipeline_run.log`](pipeline_run.log) | An earlier `ingest` + `preprocess` run on the same data (same output hash, `3f9eb186…`). |
| [`preprocess_examples.json`](preprocess_examples.json) | Example messages before and after `preprocess` (cleaning and anonymization). |
| [`retrieval_example.md`](retrieval_example.md) | One retrieval from query to retrieved context, generated with rag's `query.py --markdown` against the full 4-user index. |
| [`retrieval_check.md`](retrieval_check.md) | Will's 15 example queries, each searched in its user's collection: where the answering messages rank (all of them in the top 5 for 7 of 15), and 0 results from another user's mailbox. Generated with rag's `check_retrieval.py --markdown`. |
