"""rag job: index each user's messages into their own ChromaDB collection.

Steps (see README.md in this folder):
  1. Find the input: data/processed/messages.jsonl, or the samples if missing.
  2. Load and validate it against the data contract. Stop on any problem.
  3. Chunk: one chunk per message (with thread context, long bodies split)
     and one per thread (long threads split into windows).
  4. Embed every chunk with Vertex AI (RETRIEVAL_DOCUMENT). Stop on any problem.
  5. Connect to ChromaDB and rebuild every user's collection from scratch.

Steps 1-4 happen before ChromaDB is touched, so bad data or a failed
embedding call leaves the existing index as it was.

Exits 0 on success and 1 on failure, so docker compose stops the pipeline.
"""

import logging
import sys
import time
from datetime import datetime, timezone

import config
from chunking import chunk_message, chunk_thread, group_threads
from index import connect, rebuild_index
from inputs import InputError, find_input_files, load_and_validate, sha256_file

log = logging.getLogger("rag")


def build_chunks(messages: list[dict], thread_context: bool = True) -> dict[str, list[dict]]:
    """Chunk every thread (its messages and the thread itself), grouped by user_id.

    thread_context=False (experiments only) makes one plain chunk per message.
    """
    chunks_by_user: dict[str, list[dict]] = {}
    for (user_id, _thread_id), thread in group_threads(messages).items():
        if thread_context:
            chunks = chunk_thread(thread)
        else:
            chunks = [chunk for message in thread for chunk in chunk_message(message)]
        chunks_by_user.setdefault(user_id, []).extend(chunks)
    return chunks_by_user


def embed_chunks(chunks_by_user: dict[str, list[dict]], embedding_function) -> dict:
    """Embed every chunk, storing its vector and token count. Returns run facts.

    Raises (e.g. embeddings.EmbeddingError) if any chunk can't be embedded.
    """
    chunks = [chunk for user_chunks in chunks_by_user.values() for chunk in user_chunks]
    started = time.monotonic()
    vectors, token_counts = embedding_function.embed_documents([c["text"] for c in chunks])
    for chunk, vector, tokens in zip(chunks, vectors, token_counts):
        chunk["embedding"] = vector
        chunk["metadata"]["token_count"] = tokens
    dimension = len(vectors[0]) if vectors else 0
    log.info(
        "Embedded %d chunks with %s (dimension %d, %d tokens) in %.1f s",
        len(chunks), embedding_function.model, dimension, sum(token_counts), time.monotonic() - started,
    )
    return {"dimension": dimension, "tokens": sum(token_counts)}


def chunks_over_limit(chunks: list[dict], limit: int) -> int:
    """How many chunks are longer than the model's token limit (should be 0)."""
    return sum(chunk["metadata"]["token_count"] > limit for chunk in chunks)


def run(client_factory, embedding_function, data_dir=config.DATA_DIR, samples_dir=config.SAMPLES_DIR,
        thread_context: bool = config.THREAD_CONTEXT) -> dict[str, int]:
    """Do one full indexing run and return {collection name: chunk count}.

    client_factory is called only after the input passes validation and every
    chunk is embedded, so bad data or a failed embedding call never touches
    ChromaDB. Tests pass an in-memory client and a fake embedding function.
    """
    started = time.monotonic()

    # 1. Find the input files.
    files = find_input_files(data_dir, samples_dir)
    input_sha256 = sha256_file(files.messages_path) if files.messages_path.exists() else ""
    log.info("Input messages: %s (sha256 %s)", files.messages_path, input_sha256)
    log.info("Input users:    %s", files.users_path)

    # 2. Load and validate (raises InputError on any problem).
    users, messages, manifest = load_and_validate(files)
    log.info("Validated %d messages for %d users", len(messages), len(users))
    if manifest:
        log.info("Manifest: git_commit=%s created_at=%s", manifest.get("git_commit", ""), manifest.get("created_at", ""))

    # 3. Chunk.
    chunks_by_user = build_chunks(messages, thread_context)
    for user in users:
        user_id = user["user_id"]
        message_count = sum(1 for m in messages if m["user_id"] == user_id)
        chunk_count = len(chunks_by_user.get(user_id, []))
        if message_count == 0:
            log.warning("User %s has no messages; their collection will be empty", user_id)
        log.info("User %s: %d messages -> %d chunks", user_id, message_count, chunk_count)

    # 4. Embed (raises on any failure, before ChromaDB is touched).
    facts = embed_chunks(chunks_by_user, embedding_function)
    limit = embedding_function.token_limit
    over = {user["user_id"]: chunks_over_limit(chunks_by_user.get(user["user_id"], []), limit) for user in users}
    log.info("Chunks over the %d-token limit: %d", limit, sum(over.values()))
    user_metadata = {user_id: {"chunks_over_token_limit": count} for user_id, count in over.items()}

    # Stored on every collection, so we can tell which data version it came from.
    # Chroma metadata can't hold None, so missing values become "".
    shared_metadata = {
        "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_path": str(files.messages_path),
        "input_sha256": input_sha256,
        "used_sample_data": files.used_sample,
        "manifest_git_commit": str(manifest.get("git_commit", "")),
        "manifest_created_at": str(manifest.get("created_at", "")),
        "chunking": "message+thread" if thread_context else "message",
        # Model, dimension, task types and token limit; the api refuses a collection built with another model.
        **embedding_function.collection_metadata(facts["dimension"]),
    }

    # 5. Rebuild the index.
    client = client_factory()
    sizes = rebuild_index(client, users, chunks_by_user, shared_metadata, user_metadata)
    for name, size in sizes.items():
        log.info("Collection %s: %d chunks", name, size)
    log.info("Indexing finished in %.1f s", time.monotonic() - started)
    return sizes


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    # The Chroma client logs every HTTP request at INFO; keep only our own lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        run(connect, config.get_embedding_function())
    except InputError as e:
        log.error("Input is invalid, nothing was indexed.\n%s", e)
        sys.exit(1)
    except Exception:
        log.exception("Indexing failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
