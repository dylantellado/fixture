# Evidence

Proof that the pipeline runs end to end, with real inputs and outputs.

Milestone 3 (the classifier on Cloud Run, with monitoring) is in [`ms3/`](ms3/README.md).

## Milestone 3: Vertex AI embeddings and thread context

From a TF comment on Milestone 2 ("fix the 4 queries with no answer in the top 5 ... one chunk per message ranks short replies low, so try thread context"). `rag` now embeds with Vertex AI `gemini-embedding-001` and indexes message chunks with thread context plus one chunk per thread; search still returns messages.

| File | What it shows |
|------|---------------|
| [`rag_experiments.md`](rag_experiments.md) | Every scored setup, appended by `check_retrieval.py --record`: rows 1-4 (MiniLM baseline, MiniLM + thread context, Vertex, Vertex + thread context) on the dev and test splits, the dev-only ablations used to choose the thread weight and window size, and the final check after the pipeline rerun. |
| [`retrieval_check.md`](retrieval_check.md) | The final setup on all 47 queries: summary per split, the 15 original queries next to their Milestone 2 result, every query's ranks, and the experiment table. 0 results from another user's mailbox. |
| [`ms3_pipeline_run.log`](ms3_pipeline_run.log) | `ingest` → `preprocess` → `rag` rerun locally with uv on data-v1: hashes, per-user counts, 537 chunks and 96,947 tokens embedded in about 20 s, 0 chunks over the 2,048-token limit. |
| [`retrieval_example.md`](retrieval_example.md) | One query through `query.py --markdown` with the new chunk text (subject, sender, date, `Replying to` excerpt, body). |
| [`api_search_response.json`](api_search_response.json) | A real `POST /search` response from the api run locally against that index (user_01, "When and where do I meet my career advisor?", k=3): messages only, `chunk_type` and `token_count` in the metadata. |

Cost, measured on this run (gemini-embedding-001 at about $0.15 per million input tokens, the published Vertex AI rate as listed by pricing aggregators; check the Vertex AI pricing page before relying on it): a full re-index is 96,947 tokens, about $0.015; a search query averages 10.4 tokens, so 1,000 searches are about 10,400 tokens, about $0.002.

## Milestone 2

### Full pipeline run (one command)

From a clean state (`docker compose down -v`), at commit `0c1bbe3`, with data-v1 in `data/source/`:

```sh
GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build -d
```

All six services came up in order: `ingest` → `preprocess` → `rag` ran once and exited 0, `chromadb` was healthy, then `api` (healthy) and `frontend` started.

| File | What it shows |
|------|---------------|
| [`full_pipeline_run.log`](full_pipeline_run.log) | Logs from every service for that run: input and output sha256s, per-user counts, chunking, indexing into 4 collections, and the api and web app serving requests. One line was removed: rag's download progress bar for the embedding model, which is unreadable as text. |
| [`running_containers.png`](running_containers.png) | Docker Desktop during the fresh-clone test (a new `git clone`, set up only from the README): `ingest`, `preprocess` and `rag` have finished, and `chromadb` and `api` are running. `api` only starts after `rag` succeeds. `frontend` is still starting in this shot; `compose_ps.txt` shows all six services from the full run. |
| [`compose_ps.txt`](compose_ps.txt) | `docker compose ps -a` right after the run: the three jobs `Exited (0)`, and `chromadb`, `api` and `frontend` up. |
| [`../mockup/search_page.png`](../mockup/search_page.png) | The web app's "Search past threads" page with the same query, served by the `frontend` container and calling the `api` container. |

In the log, `172.21.0.4` requests are the `frontend` container calling the `api` (the app's UI-to-backend interaction). The `151.101.128.223` requests are the checks we sent from the laptop with `curl` and the browser. Docker Desktop reported them under that address instead of `127.0.0.1`.

### Data version

Every stage logs the sha256 of what it read and wrote, so each container's data version can be traced:

| Stage | Reads | Writes |
|-------|-------|--------|
| `ingest` | `users.json` `f112d23c…`, `generated_threads.jsonl` `eb2efe27…` | `data/raw/threads.jsonl` `798a15d5…` |
| `preprocess` | `threads.jsonl` `798a15d5…` | `data/processed/messages.jsonl` `3f9eb186…` and `manifest.json` (with `git_commit`) |
| `rag` | `messages.jsonl` `3f9eb186…` | `messages_user_01` … `messages_user_04` in ChromaDB; each collection's metadata stores `input_sha256` `3f9eb186…` and `indexed_at` |

Result: 4 users, 160 threads, 377 messages, 390 chunks.

### Other files

| File | What it shows |
|------|---------------|
| [`pipeline_run.log`](pipeline_run.log) | An earlier `ingest` + `preprocess` run on the same data (same output hash, `3f9eb186…`). |
| [`preprocess_examples.json`](preprocess_examples.json) | Example messages before and after `preprocess` (cleaning and anonymization). |
| `retrieval_example.md`, `retrieval_check.md`, `api_search_response.json` | Regenerated for Milestone 3 (see above). At Milestone 2 (MiniLM), all answering messages were in the top 5 for 7 of Will's 15 queries; the Milestone 2 result of each is kept in `retrieval_check.md` for comparison. |
