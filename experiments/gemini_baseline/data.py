"""Load the training messages and their correct answers, and refuse eval data.

Reads (repo paths, see "Data contract" in the repo README):
  data/processed/messages.jsonl   the messages and their correct `label`
  data/source/annotations.jsonl   the correct `needs_response` for every message
  data/source/users.json          names of the mailbox owners

eval-v1 (data/eval/, users eval_01 to eval_04) is frozen and must never be run
or used for tuning, so every path and user_id is checked before anything is read.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MESSAGES_PATH = REPO_ROOT / "data" / "processed" / "messages.jsonl"
ANNOTATIONS_PATH = REPO_ROOT / "data" / "source" / "annotations.jsonl"
USERS_PATH = REPO_ROOT / "data" / "source" / "users.json"
EVAL_DIR = REPO_ROOT / "data" / "eval"

TRAINING_USERS = ["user_01", "user_02", "user_03", "user_04"]

# Counts for the full training set under labeling rules v1.5 (PR #15). If the
# refreshed data doesn't match, the data is stale or changed: stop, don't score.
EXPECTED_TOTAL = 377
EXPECTED_LABEL_COUNTS = {
    "acceptance": 105,
    "none": 92,
    "proposed_times": 78,
    "new_request": 51,
    "reschedule": 41,
    "assistant_handoff": 10,
}
EXPECTED_NEEDS_RESPONSE = {True: 109, False: 268}


class DataError(Exception):
    """The input is wrong (stale counts, missing answers, eval data, ...)."""


def refuse_eval_path(path: Path) -> None:
    """Raise if `path` points into an eval set (data/eval/ in this repo or any copy of it)."""
    resolved = Path(path).resolve()
    parts = resolved.parts
    inside_any_data_eval = any(parts[i : i + 2] == ("data", "eval") for i in range(len(parts) - 1))
    if resolved.is_relative_to(EVAL_DIR) or inside_any_data_eval:
        raise DataError(f"refusing eval data: {path} (eval-v1 is frozen and must not be run)")


def refuse_eval_user(user_id: str) -> None:
    """Raise if `user_id` is an eval user (eval_01, ...)."""
    if user_id.startswith("eval_"):
        raise DataError(f"refusing eval user {user_id!r} (eval-v1 is frozen and must not be run)")


def message_id(user_id: str, thread_id: str, position: int) -> str:
    """Same id rule as preprocess: first 16 hex characters of sha256("<user_id>|<thread_id>|<position>")."""
    return hashlib.sha256(f"{user_id}|{thread_id}|{position}".encode("utf-8")).hexdigest()[:16]


def read_jsonl(path: Path) -> list[dict]:
    refuse_eval_path(path)
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_counts(messages: list[dict]) -> None:
    """Raise unless the full training set has exactly the documented counts."""
    labels = Counter(m["label"] for m in messages)
    needs_response = Counter(m["true_needs_response"] for m in messages)
    problems = []
    if len(messages) != EXPECTED_TOTAL:
        problems.append(f"total {len(messages)} != {EXPECTED_TOTAL}")
    if dict(labels) != EXPECTED_LABEL_COUNTS:
        problems.append(f"labels {dict(sorted(labels.items()))} != {dict(sorted(EXPECTED_LABEL_COUNTS.items()))}")
    if dict(needs_response) != EXPECTED_NEEDS_RESPONSE:
        problems.append(f"needs_response {dict(needs_response)} != {EXPECTED_NEEDS_RESPONSE}")
    if problems:
        raise DataError(
            "training data doesn't match the documented counts (rerun ingest and preprocess on main?): "
            + "; ".join(problems)
        )


def load_training(
    messages_path: Path = MESSAGES_PATH,
    annotations_path: Path = ANNOTATIONS_PATH,
    users_path: Path = USERS_PATH,
) -> tuple[list[dict], dict[str, str]]:
    """Return (messages, owner names by user_id).

    Each message is the messages.jsonl record plus `position` (index in its
    thread) and `true_needs_response` from the annotations. Messages are sorted
    by (user_id, thread_id, position). Raises DataError on eval data, a non-training
    user, a message without an answer, or counts that don't match the docs.
    """
    for path in (messages_path, annotations_path, users_path):
        refuse_eval_path(path)

    messages = read_jsonl(messages_path)
    annotations = read_jsonl(annotations_path)
    with open(users_path, encoding="utf-8") as f:
        owners = {u["user_id"]: u["name"] for u in json.load(f)}

    # Check every user_id before using anything.
    for record in [*messages, *annotations]:
        refuse_eval_user(record["user_id"])
        if record["user_id"] not in TRAINING_USERS:
            raise DataError(f"unexpected user {record['user_id']!r}: only {TRAINING_USERS} are training users")

    # Annotations are keyed by (user_id, thread_id, position); messages by message_id.
    by_id = {}
    for a in annotations:
        by_id[message_id(a["user_id"], a["thread_id"], a["position"])] = a
    for m in messages:
        a = by_id.get(m["message_id"])
        if a is None:
            raise DataError(f"no annotation for message {m['message_id']} ({m['user_id']}/{m['thread_id']})")
        m["position"] = a["position"]
        m["true_needs_response"] = a["needs_response"]
        m["annotation_rules_version"] = a["rules_version"]
        m["hard_negative"] = a.get("hard_negative")  # not in the v1.2 annotations; scored if added
    if len(by_id) != len(messages):
        raise DataError(f"{len(by_id)} annotations but {len(messages)} messages")

    messages.sort(key=lambda m: (m["user_id"], m["thread_id"], m["position"]))
    check_counts(messages)
    return messages, owners


def group_threads(messages: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Messages by (user_id, thread_id), each list in thread order (oldest first)."""
    threads: dict[tuple[str, str], list[dict]] = {}
    for m in sorted(messages, key=lambda m: m["position"]):
        threads.setdefault((m["user_id"], m["thread_id"]), []).append(m)
    return threads
