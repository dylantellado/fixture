"""rag job: index each user's messages into their own ChromaDB collection.

Steps (see README.md in this folder):
  1. Find the input: data/processed/messages.jsonl, or the samples if missing.
  2. Load and validate it against the data contract. Stop on any problem.
  3. Chunk every message (one chunk per message, long bodies split).
  4. Connect to ChromaDB and rebuild every user's collection from scratch.

Exits 0 on success and 1 on failure, so docker compose stops the pipeline.
"""

import logging
import sys
import time
from datetime import datetime, timezone

import config
from chunking import chunk_message
from index import connect, rebuild_index
from inputs import InputError, find_input_files, load_and_validate, sha256_file

log = logging.getLogger("rag")


def build_chunks(messages: list[dict]) -> dict[str, list[dict]]:
    """Chunk every message, grouped by user_id."""
    chunks_by_user: dict[str, list[dict]] = {}
    for message in messages:
        chunks_by_user.setdefault(message["user_id"], []).extend(chunk_message(message))
    return chunks_by_user


def run(client_factory, embedding_function, data_dir=config.DATA_DIR, samples_dir=config.SAMPLES_DIR) -> dict[str, int]:
    """Do one full indexing run and return {collection name: chunk count}.

    client_factory is called only after the input passes validation, so bad
    data never touches ChromaDB. Tests pass an in-memory client here.
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
    chunks_by_user = build_chunks(messages)
    for user in users:
        user_id = user["user_id"]
        message_count = sum(1 for m in messages if m["user_id"] == user_id)
        chunk_count = len(chunks_by_user.get(user_id, []))
        if message_count == 0:
            log.warning("User %s has no messages; their collection will be empty", user_id)
        log.info("User %s: %d messages -> %d chunks", user_id, message_count, chunk_count)

    # Stored on every collection, so we can tell which data version it came from.
    # Chroma metadata can't hold None, so missing values become "".
    shared_metadata = {
        "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_path": str(files.messages_path),
        "input_sha256": input_sha256,
        "used_sample_data": files.used_sample,
        "manifest_git_commit": str(manifest.get("git_commit", "")),
        "manifest_created_at": str(manifest.get("created_at", "")),
        "embedding_model": config.EMBEDDING_MODEL,
    }

    # 4. Rebuild the index.
    client = client_factory()
    sizes = rebuild_index(client, embedding_function, users, chunks_by_user, shared_metadata)
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
