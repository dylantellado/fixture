"""Ingest: collect email threads, check them, and write data/raw/threads.jsonl.

Steps (see "Data contract" in the README):
  1. Load users and threads through a collector (FileCollector for now).
  2. Validate every thread against the contract (validation.py).
  3. Drop duplicates: repeated threads within one user's inbox, and repeated
     messages within a thread. The same email in two users' inboxes is kept
     in both, because each user's data stays separate.
  4. Add provenance: the collector name, the file and line each thread came
     from, and a sha256 fingerprint of its content.
  5. Write the threads sorted by (user_id, thread_id), so the same input
     always gives a byte-identical file, through a temp file and a rename,
     so a crash never leaves a half-written output.

If any thread is invalid, nothing is written and ingest exits with code 1,
so preprocess (which waits for ingest to succeed) never runs on bad data.

Run locally from src/ingest:  uv run python main.py
In Docker, compose sets DATA_DIR=/data.
"""

import hashlib
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from collectors import Collector, FileCollector, SourceMissingError
from validation import validate_thread

log = logging.getLogger("ingest")


@dataclass
class IngestResult:
    threads: list[dict] = field(default_factory=list)  # clean threads, sorted
    errors: list[str] = field(default_factory=list)
    duplicate_threads: int = 0
    duplicate_messages: int = 0


def content_hash(thread: dict) -> str:
    """sha256 of a thread's content, independent of key order."""
    canonical = json.dumps(thread, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def drop_repeated_messages(messages: list[dict]) -> tuple[list[dict], int]:
    """Remove exact repeats of a message (same sender, time and body) in one thread."""
    seen = set()
    kept = []
    for message in messages:
        key = (message["sender"], message["timestamp"], message["body"])
        if key not in seen:
            seen.add(key)
            kept.append(message)
    return kept, len(messages) - len(kept)


def ingest_threads(records, known_user_ids: set[str], source_name: str) -> IngestResult:
    """Validate, deduplicate and annotate threads. Doesn't touch any files.

    `records` is an iterable of (thread, origin) pairs from a collector.
    """
    result = IngestResult()
    by_key = {}  # (user_id, thread_id) -> (content hash, clean thread)

    for thread, origin in records:
        errors = validate_thread(thread, known_user_ids)
        if errors:
            result.errors.extend(f"{origin['file']} line {origin['line']}: {e}" for e in errors)
            continue

        fingerprint = content_hash(thread)
        key = (thread["user_id"], thread["thread_id"])

        if key in by_key:
            if by_key[key][0] == fingerprint:
                # Exactly the same thread again in the same inbox: keep one copy.
                result.duplicate_threads += 1
            else:
                # Same id but different content: one of them is wrong, so stop.
                result.errors.append(
                    f"{origin['file']} line {origin['line']}: {key[0]}/{key[1]} appears twice with different content"
                )
            continue

        messages, repeats = drop_repeated_messages(thread["messages"])
        result.duplicate_messages += repeats

        clean = {
            **thread,
            "messages": messages,
            "source": source_name,
            "provenance": {**origin, "sha256": fingerprint},
        }
        by_key[key] = (fingerprint, clean)

    # Sort so the output doesn't depend on input order.
    result.threads = [by_key[key][1] for key in sorted(by_key)]
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl_atomically(path: Path, records: list[dict]) -> None:
    """Write one JSON object per line, via a temp file renamed into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temp file sits in the same folder, so the rename is atomic.
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def default_data_dir() -> Path:
    """DATA_DIR from the environment (Docker), else the repo's data/ folder."""
    if "DATA_DIR" in os.environ:
        return Path(os.environ["DATA_DIR"])
    return Path(__file__).resolve().parents[2] / "data"


def run(data_dir: Path, collector: Collector | None = None) -> int:
    """Run ingest end to end. Returns the process exit code (0 = success)."""
    collector = collector or FileCollector(data_dir / "source")
    output_path = data_dir / "raw" / "threads.jsonl"

    try:
        if isinstance(collector, FileCollector):
            collector.check_files_exist()
            for path in (collector.users_path, collector.threads_path):
                log.info("read %s sha256=%s", path, sha256_file(path))
        users = collector.users()
        result = ingest_threads(collector.threads(), {u["user_id"] for u in users}, collector.name)
    except (SourceMissingError, ValueError) as error:
        log.error("%s", error)
        return 1

    if result.errors:
        for error in result.errors:
            log.error("invalid: %s", error)
        log.error("%d problems found; nothing written. Fix the source data and rerun.", len(result.errors))
        return 1

    write_jsonl_atomically(output_path, result.threads)

    # Counts, total and per user, so a run can be checked at a glance.
    threads_per_user = Counter(t["user_id"] for t in result.threads)
    messages_per_user = Counter()
    for thread in result.threads:
        messages_per_user[thread["user_id"]] += len(thread["messages"])

    log.info("users: %d", len(users))
    for user in users:
        user_id = user["user_id"]
        log.info("  %s: %d threads, %d messages", user_id, threads_per_user[user_id], messages_per_user[user_id])
    log.info(
        "total: %d threads, %d messages (dropped %d duplicate threads, %d duplicate messages)",
        len(result.threads),
        sum(messages_per_user.values()),
        result.duplicate_threads,
        result.duplicate_messages,
    )
    log.info("wrote %s sha256=%s", output_path, sha256_file(output_path))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s ingest: %(message)s", stream=sys.stdout)
    sys.exit(run(default_data_dir()))


if __name__ == "__main__":
    main()
