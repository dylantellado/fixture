"""Find, load, and validate the rag service's input files.

Everything here runs before ChromaDB is touched, so bad data stops the job
without changing the existing index.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Fields every message must have, and their types (README "messages.jsonl schema").
REQUIRED_FIELDS = {
    "message_id": str,
    "user_id": str,
    "thread_id": str,
    "source": str,
    "sender": str,
    "recipients": list,
    "timestamp": str,
    "subject": str,
    "body": str,
    "label": str,
}

ALLOWED_LABELS = {
    "new_request",
    "proposed_times",
    "acceptance",
    "reschedule",
    "assistant_handoff",
    "none",
}

# user_id becomes part of a collection name, so only these characters are allowed.
USER_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

# Stop listing problems after this many, so a broken file doesn't flood the log.
MAX_ERRORS_SHOWN = 20


class InputError(Exception):
    """The input files are missing or break the data contract."""


@dataclass
class InputFiles:
    """Which files this run reads."""

    messages_path: Path
    users_path: Path
    manifest_path: Path | None  # None when there is no manifest (e.g. sample data)
    used_sample: bool


def find_input_files(data_dir: Path, samples_dir: Path) -> InputFiles:
    """Use the pipeline's output if it exists, otherwise the committed samples."""
    messages_path = data_dir / "processed" / "messages.jsonl"
    if messages_path.exists():
        manifest_path = data_dir / "processed" / "manifest.json"
        return InputFiles(
            messages_path=messages_path,
            users_path=data_dir / "source" / "users.json",
            manifest_path=manifest_path if manifest_path.exists() else None,
            used_sample=False,
        )

    log.warning(
        "SAMPLE DATA USED: %s not found, so indexing %s and %s instead. "
        "Search results come from the committed samples, not generated data.",
        messages_path,
        samples_dir / "messages_sample.jsonl",
        samples_dir / "users.json",
    )
    return InputFiles(
        messages_path=samples_dir / "messages_sample.jsonl",
        users_path=samples_dir / "users.json",
        manifest_path=None,
        used_sample=True,
    )


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file, so we can record exactly which data was indexed."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_messages(path: Path) -> list[dict]:
    """Read a JSONL file: one JSON object per line, blank lines skipped."""
    if not path.exists():
        raise InputError(f"Messages file not found: {path}")
    messages = []
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise InputError(f"{path} line {line_number}: not valid JSON ({e.msg})")
            if not isinstance(record, dict):
                raise InputError(f"{path} line {line_number}: expected a JSON object")
            messages.append(record)
    return messages


def load_users(path: Path) -> list[dict]:
    """Read users.json: a JSON list of {"user_id", "name", ...} objects."""
    if not path.exists():
        raise InputError(f"Users file not found: {path}")
    try:
        users = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InputError(f"{path}: not valid JSON ({e.msg})")
    if not isinstance(users, list):
        raise InputError(f"{path}: expected a JSON list of users")
    return users


def load_manifest(path: Path | None) -> dict:
    """Read manifest.json if there is one; return {} otherwise."""
    if path is None:
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InputError(f"{path}: not valid JSON ({e.msg})")
    if not isinstance(manifest, dict):
        raise InputError(f"{path}: expected a JSON object")
    return manifest


def check_user_id(user_id: object) -> str | None:
    """Return a problem description if user_id can't be used, else None."""
    if not isinstance(user_id, str) or not USER_ID_PATTERN.match(user_id):
        return f"user_id {user_id!r} must match {USER_ID_PATTERN.pattern}"
    # Chroma collection names must end with a letter or digit, so
    # messages_<user_id> would be rejected if user_id ended with "_".
    if user_id.endswith("_"):
        return f"user_id {user_id!r} must not end with '_'"
    return None


def validate_users(users: list[dict]) -> list[str]:
    """Check users.json. Returns a list of problems (empty if all good)."""
    errors = []
    seen = set()
    for i, user in enumerate(users):
        where = f"users.json entry {i}"
        if not isinstance(user, dict):
            errors.append(f"{where}: expected an object")
            continue
        problem = check_user_id(user.get("user_id"))
        if problem:
            errors.append(f"{where}: {problem}")
        if not isinstance(user.get("name"), str):
            errors.append(f"{where}: 'name' must be a string")
        user_id = user.get("user_id")
        if isinstance(user_id, str):
            if user_id in seen:
                errors.append(f"{where}: duplicate user_id {user_id!r}")
            seen.add(user_id)
    if not users:
        errors.append("users.json has no users")
    return errors


def validate_messages(messages: list[dict], known_user_ids: set[str]) -> list[str]:
    """Check every message against the data contract.

    Returns a list of problems (empty if all good). Line numbers count
    non-blank lines, starting at 1.
    """
    errors = []
    seen_ids = set()
    for line, msg in enumerate(messages, start=1):
        where = f"message {line} (message_id {msg.get('message_id')!r})"

        # Every contract field is present with the right type (no nulls).
        bad_fields = False
        for field, field_type in REQUIRED_FIELDS.items():
            if field not in msg:
                errors.append(f"{where}: missing field '{field}'")
                bad_fields = True
            elif not isinstance(msg[field], field_type):
                errors.append(
                    f"{where}: '{field}' must be a {field_type.__name__}, "
                    f"got {type(msg[field]).__name__}"
                )
                bad_fields = True
        if bad_fields:
            continue  # the checks below assume the fields exist

        problem = check_user_id(msg["user_id"])
        if problem:
            errors.append(f"{where}: {problem}")
        elif msg["user_id"] not in known_user_ids:
            errors.append(f"{where}: user_id {msg['user_id']!r} is not in users.json")

        if msg["label"] not in ALLOWED_LABELS:
            errors.append(
                f"{where}: label {msg['label']!r} is not one of {sorted(ALLOWED_LABELS)}"
            )

        if msg["message_id"] == "":
            errors.append(f"{where}: message_id is empty")
        elif msg["message_id"] in seen_ids:
            errors.append(f"{where}: duplicate message_id {msg['message_id']!r}")
        seen_ids.add(msg["message_id"])

        # We turn the timestamp into epoch seconds, which needs a UTC offset.
        # "" is allowed by the contract and means unknown.
        if msg["timestamp"] != "":
            try:
                parsed = datetime.fromisoformat(msg["timestamp"])
            except ValueError:
                parsed = None
            if parsed is None or parsed.utcoffset() is None:
                errors.append(
                    f"{where}: timestamp {msg['timestamp']!r} must be ISO 8601 "
                    "with a UTC offset, e.g. 2026-10-13T09:12:00-04:00"
                )

    if not messages:
        errors.append("the messages file has no messages")
    return errors


def load_and_validate(files: InputFiles) -> tuple[list[dict], list[dict], dict]:
    """Load users, messages, and manifest; raise InputError listing any problems."""
    users = load_users(files.users_path)
    messages = load_messages(files.messages_path)
    manifest = load_manifest(files.manifest_path)

    errors = validate_users(users)
    known_user_ids = {
        u["user_id"] for u in users if isinstance(u, dict) and isinstance(u.get("user_id"), str)
    }
    errors += validate_messages(messages, known_user_ids)

    if errors:
        shown = errors[:MAX_ERRORS_SHOWN]
        more = len(errors) - len(shown)
        text = "\n  - ".join(shown)
        if more:
            text += f"\n  ... and {more} more"
        raise InputError(
            f"{len(errors)} problem(s) in {files.messages_path} / {files.users_path}:\n  - {text}"
        )
    return users, messages, manifest
