"""Preprocess: turn data/raw/threads.jsonl into one clean record per message.

Reads (see "Data contract" in the README):
  data/raw/threads.jsonl     validated threads from ingest
  data/source/users.json     the users, so counts include every user
Writes:
  data/processed/messages.jsonl   one message per line, contract schema
  data/processed/manifest.json    counts, sha256 of inputs and outputs, provenance

For each message: clean the body (cleaning.py), replace addresses and phone
numbers with placeholders (anonymize.py), convert the timestamp to ISO 8601,
and give it a deterministic message_id. No message is dropped, so a
message's position in its thread (and its id) never changes.

Any failure exits with code 1, so rag (which waits for preprocess to
succeed) never indexes bad data. Outputs are written to a temp file and
renamed into place, so they are never half-written.

Run locally from src/preprocess:  uv run python main.py
In Docker, compose sets DATA_DIR=/data and passes GIT_COMMIT.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from anonymize import EMAIL, PHONE, Anonymizer, normalize_phone
from cleaning import clean_body

log = logging.getLogger("preprocess")

# Fields that become Chroma metadata, so they must always be strings.
STRING_FIELDS = ["message_id", "user_id", "thread_id", "sender", "timestamp", "source", "subject", "label"]


def make_message_id(user_id: str, thread_id: str, position: int) -> str:
    """First 16 hex characters of sha256("<user_id>|<thread_id>|<position>") (contract rule)."""
    return hashlib.sha256(f"{user_id}|{thread_id}|{position}".encode("utf-8")).hexdigest()[:16]


def to_iso(timestamp: str) -> str:
    """'Tue, 13 Oct 2026 09:12:00 -0400' -> '2026-10-13T09:12:00-04:00' (sender's offset kept)."""
    return parsedate_to_datetime(timestamp).isoformat()


def build_messages(threads: list[dict]) -> list[dict]:
    """Flatten, clean and anonymize every message of every thread."""
    # Clean first, so the placeholder map only covers text that is kept.
    cleaned = []  # (thread, position, message, clean body)
    for thread in threads:
        for position, message in enumerate(thread["messages"]):
            sender_name = parseaddr(message["sender"])[0]
            cleaned.append((thread, position, message, clean_body(message["body"], sender_name)))

    # Pass 1: collect every address and number across ALL users, then number them.
    anonymizer = Anonymizer()
    for thread, _position, message, body in cleaned:
        for text in [message["sender"], *message["recipients"], thread["subject"], body]:
            anonymizer.collect(text)
    anonymizer.finalize()

    # Pass 2: build the output records.
    records = []
    for thread, position, message, body in cleaned:
        records.append(
            {
                "message_id": make_message_id(thread["user_id"], thread["thread_id"], position),
                "user_id": thread["user_id"],
                "thread_id": thread["thread_id"],
                "source": thread.get("source") or "",
                "sender": anonymizer.person(message["sender"]),
                "recipients": [anonymizer.person(r) for r in message["recipients"]],
                "timestamp": to_iso(message["timestamp"]),
                "subject": anonymizer.replace(thread["subject"] or ""),
                "body": anonymizer.replace(body),
                "label": message["label"],
            }
        )
    return records


def check_records(records: list[dict]) -> list[str]:
    """Final safety checks before anything is written. Returns problems found."""
    problems = []
    ids = Counter(r["message_id"] for r in records)
    problems += [f"duplicate message_id {i}" for i, n in ids.items() if n > 1]
    for r in records:
        where = f"{r['user_id']}/{r['thread_id']} {r['message_id']}"
        problems += [f"{where}: {f} is not a string" for f in STRING_FIELDS if not isinstance(r[f], str)]
        if not isinstance(r["recipients"], list):
            problems.append(f"{where}: recipients is not a list")
        # Nothing that looks like an address or phone number may survive anonymization.
        text = " ".join([r["sender"], *r["recipients"], r["subject"], r["body"]])
        if EMAIL.search(text):
            problems.append(f"{where}: an email address was not anonymized")
        if any(len(re.sub(r"\D", "", p)) >= 10 and not normalize_phone(p) for p in PHONE.findall(text)):
            problems.append(f"{where}: a long number could not be anonymized")
    return problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomically(path: Path, text: str) -> None:
    """Write text to a temp file in the same folder, then rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def git_commit() -> str:
    """The code version: GIT_COMMIT from the environment (Docker), else ask git, else 'unknown'."""
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=Path(__file__).parent
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_manifest(records, users, inputs: dict[str, Path], outputs: dict[str, Path]) -> dict:
    """Counts and fingerprints that tie this run's outputs to its inputs."""
    per_user = Counter(r["user_id"] for r in records)
    return {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(),
        "counts": {
            "total": len(records),
            "per_user": {u["user_id"]: per_user[u["user_id"]] for u in users},
            "threads": len({(r["user_id"], r["thread_id"]) for r in records}),
            "per_label": dict(sorted(Counter(r["label"] for r in records).items())),
        },
        "sha256": {name: sha256_file(path) for name, path in {**inputs, **outputs}.items()},
    }


def default_data_dir() -> Path:
    """DATA_DIR from the environment (Docker), else the repo's data/ folder."""
    if "DATA_DIR" in os.environ:
        return Path(os.environ["DATA_DIR"])
    return Path(__file__).resolve().parents[2] / "data"


def run(data_dir: Path) -> int:
    """Run preprocess end to end. Returns the process exit code (0 = success)."""
    threads_path = data_dir / "raw" / "threads.jsonl"
    users_path = data_dir / "source" / "users.json"
    messages_path = data_dir / "processed" / "messages.jsonl"
    manifest_path = data_dir / "processed" / "manifest.json"

    missing = [p for p in (threads_path, users_path) if not p.exists()]
    if missing:
        log.error("missing input: %s (run ingest first)", ", ".join(map(str, missing)))
        return 1

    try:
        for path in (threads_path, users_path):
            log.info("read %s sha256=%s", path, sha256_file(path))
        threads = [json.loads(line) for line in threads_path.read_text().splitlines() if line.strip()]
        users = json.loads(users_path.read_text())
        records = build_messages(threads)
    except Exception as error:  # any bad input should stop the pipeline, loudly
        log.error("could not process %s: %s: %s", threads_path, type(error).__name__, error)
        return 1

    problems = check_records(records)
    if problems:
        for problem in problems:
            log.error("check failed: %s", problem)
        log.error("%d problems; nothing written.", len(problems))
        return 1

    # Messages first, manifest last: if a manifest exists, it describes a complete messages file.
    write_atomically(messages_path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    manifest = build_manifest(
        records,
        users,
        inputs={"data/raw/threads.jsonl": threads_path, "data/source/users.json": users_path},
        outputs={"data/processed/messages.jsonl": messages_path},
    )
    write_atomically(manifest_path, json.dumps(manifest, indent=2) + "\n")

    for user_id, count in manifest["counts"]["per_user"].items():
        log.info("  %s: %d messages", user_id, count)
    log.info("total: %d messages in %d threads", manifest["counts"]["total"], manifest["counts"]["threads"])
    log.info("labels: %s", manifest["counts"]["per_label"])
    log.info("wrote %s sha256=%s", messages_path, manifest["sha256"]["data/processed/messages.jsonl"])
    log.info("wrote %s (git_commit=%s)", manifest_path, manifest["git_commit"])
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s preprocess: %(message)s", stream=sys.stdout
    )
    sys.exit(run(default_data_dir()))


if __name__ == "__main__":
    main()
