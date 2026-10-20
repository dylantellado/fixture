"""Builders for test data, shared by several test files."""

import json

import config

# The committed fake data at the repo root.
SAMPLES_DIR = config.REPO_ROOT / "samples"


def make_message(body="Can we meet Tuesday at 2pm?", **overrides):
    message = {
        "message_id": "abc123def4567890",
        "user_id": "user_01",
        "thread_id": "t001",
        "source": "generated",
        "sender": "Jordan Lee <EMAIL_003>",
        "recipients": ["Priya Shah <EMAIL_001>"],
        "timestamp": "2026-10-13T09:12:00-04:00",
        "subject": "Interview",
        "body": body,
        "label": "new_request",
    }
    message.update(overrides)
    return message


def long_body(words=400):
    """A body well over CHUNK_SIZE, with numbered words so pieces are easy to check."""
    return " ".join(f"word{i}" for i in range(words))


def write_pipeline_data(data_dir, messages, users, manifest=None):
    """Write files where preprocess would, so tests can run on custom data."""
    (data_dir / "processed").mkdir(parents=True, exist_ok=True)
    (data_dir / "source").mkdir(parents=True, exist_ok=True)
    with open(data_dir / "processed" / "messages.jsonl", "w", encoding="utf-8") as f:
        for message in messages:
            f.write(json.dumps(message) + "\n")
    (data_dir / "source" / "users.json").write_text(json.dumps(users), encoding="utf-8")
    if manifest is not None:
        (data_dir / "processed" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
