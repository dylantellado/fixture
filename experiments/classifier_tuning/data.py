"""Load the messages, their correct answers and the user splits.

Reads (Data contract paths; local or gs:// so a Vertex AI job can read them):
  data/processed/messages.jsonl    messages and their correct label
  data/source/annotations.jsonl    the correct needs_response for every message
  data/source/users.json           mailbox owner names (to mark messages the user sent)
  data/source/splits.json          which users are train and which are held-out eval
  data/source/thread_states.jsonl  for generated threads, what each message does (its act)

Tuning only ever reads the train split. The eval split is for a final report,
and data/eval/ (eval-v1) is never read here at all.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"
PATHS = {
    "messages": DATA / "processed" / "messages.jsonl",
    "annotations": DATA / "source" / "annotations.jsonl",
    "users": DATA / "source" / "users.json",
    "splits": DATA / "source" / "splits.json",
    "states": DATA / "source" / "thread_states.jsonl",
}


class DataError(Exception):
    pass


def read_text(path) -> str:
    path = str(path)
    if "/data/eval/" in path or path.startswith("data/eval/"):
        raise DataError(f"refusing {path}: eval-v1 is frozen and never read by tuning")
    if path.startswith("gs://"):
        from google.cloud import storage
        bucket, _, name = path[5:].partition("/")
        return storage.Client().bucket(bucket).blob(name).download_as_text()
    return Path(path).read_text(encoding="utf-8")


def md5(text: str) -> str:
    """Same hash DVC uses for a file, so a run can be matched to a data version in dvc.lock."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def message_id(user_id: str, thread_id: str, position: int) -> str:
    """Preprocess's id rule (Data contract)."""
    return hashlib.sha256(f"{user_id}|{thread_id}|{position}".encode()).hexdigest()[:16]


def load(split: str, paths: dict | None = None) -> tuple[dict[tuple[str, str], list[dict]], dict]:
    """Threads for one split, and the data versions read.

    Returns ({(user_id, thread_id): [message, ...] in thread order}, {"<name>_md5": ...}).
    Each message gets position, from_user, true_needs_response, true_label, act and source_set.
    """
    paths = {**PATHS, **(paths or {})}
    texts = {name: read_text(p) for name, p in paths.items() if name != "states" or _exists(p)}
    versions = {f"{name}_md5": md5(text) for name, text in texts.items()}

    splits = json.loads(texts["splits"])
    if split not in splits:
        raise DataError(f"unknown split {split!r}; splits.json has {sorted(splits)}")
    users = set(splits[split])
    owners = {u["user_id"]: u["name"] for u in json.loads(texts["users"])}
    answers = {}
    for line in texts["annotations"].splitlines():
        if line.strip():
            a = json.loads(line)
            answers[message_id(a["user_id"], a["thread_id"], a["position"])] = a
    acts = {}
    for line in texts.get("states", "").splitlines():
        if line.strip():
            record = json.loads(line)
            for s in record["states"]:
                acts[message_id(record["user_id"], record["thread_id"], s["position"])] = s["act"]

    threads: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in texts["messages"].splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        if m["user_id"] not in users:
            continue
        a = answers.get(m["message_id"])
        if a is None:
            raise DataError(f"no annotation for {m['message_id']} ({m['user_id']}/{m['thread_id']})")
        m.update(position=a["position"], true_needs_response=a["needs_response"], true_label=m["label"],
                 from_user=_display_name(m["sender"]) == owners.get(m["user_id"]),
                 act=acts.get(m["message_id"], ""), source_set="generated" if m["message_id"] in acts else "v1")
        threads[(m["user_id"], m["thread_id"])].append(m)
    for messages in threads.values():
        messages.sort(key=lambda m: m["position"])
    if not threads:
        raise DataError(f"no messages for split {split!r} (users {sorted(users)})")
    return dict(threads), versions


def _exists(path) -> bool:
    return str(path).startswith("gs://") or Path(path).exists()


def _display_name(address: str) -> str:
    return address.split("<")[0].strip().strip('"')
