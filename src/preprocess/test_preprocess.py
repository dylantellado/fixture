"""End-to-end tests for preprocess (main.py) on small fake inputs, plus
checks on the real corpus when it's present (they skip in a fresh clone)."""

import json
from collections import Counter
from pathlib import Path

import pytest

from main import STRING_FIELDS, make_message_id, run, to_iso

USERS = [
    {"user_id": "user_01", "name": "Priya Shah", "email": "priya.shah@example.com"},
    {"user_id": "user_02", "name": "Marcus Bell", "email": "marcus.bell@example.com"},
]
DANA = "Dana Whitfield <dana.whitfield@careers.college.example>"


def thread(user_id, thread_id, student, bodies):
    """A raw thread (ingest's output shape) between Dana and a student."""
    messages = []
    for i, body in enumerate(bodies):
        sender, recipient = (student, DANA) if i % 2 == 0 else (DANA, student)
        messages.append(
            {
                "sender": sender,
                "recipients": [recipient],
                "timestamp": f"Thu, 03 Sep 2026 1{i}:00:00 -0400",
                "body": body,
                "label": "new_request" if i == 0 else "proposed_times",
            }
        )
    return {
        "user_id": user_id,
        "thread_id": thread_id,
        "subject": "Advising",
        "participants": [student, DANA],
        "messages": messages,
        "source": "generated",
    }


THREADS = [
    thread("user_01", "t001", "Priya Shah <priya.shah@example.com>", ["Could we meet?", "Tue 3:00?\n\nDana Whitfield\n(617) 555-0142"]),
    thread("user_02", "t001", "Marcus Bell <marcus.bell@example.com>", ["can we meet", "Fri 11 on Zoom? Call (617) 555-0142."]),
]


def setup_data(data_dir: Path, threads=THREADS):
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "source").mkdir()
    (data_dir / "raw" / "threads.jsonl").write_text("".join(json.dumps(t) + "\n" for t in threads))
    (data_dir / "source" / "users.json").write_text(json.dumps(USERS))


def read_messages(data_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (data_dir / "processed" / "messages.jsonl").read_text().splitlines()]


def test_message_id_follows_the_contract_rule():
    # Same rule as samples/messages_sample.jsonl from the contract PR.
    assert make_message_id("user_01", "t001", 0) == "1901c022a62edc40"


def test_timestamp_becomes_iso_with_the_senders_offset():
    assert to_iso("Tue, 13 Oct 2026 09:12:00 -0400") == "2026-10-13T09:12:00-04:00"
    assert to_iso("Thu, 08 Oct 2026 18:00:00 +0530") == "2026-10-08T18:00:00+05:30"


def test_output_matches_the_contract_schema(tmp_path):
    setup_data(tmp_path)
    assert run(tmp_path) == 0
    records = read_messages(tmp_path)
    assert len(records) == 4
    for record in records:
        assert list(record) == [
            "message_id", "user_id", "thread_id", "source", "sender",
            "recipients", "timestamp", "subject", "body", "label",
        ]
        assert all(isinstance(record[field], str) for field in STRING_FIELDS)
        assert isinstance(record["recipients"], list)
        assert record["user_id"] in {"user_01", "user_02"}


def test_same_address_gets_same_placeholder_across_users(tmp_path):
    setup_data(tmp_path)
    run(tmp_path)
    records = read_messages(tmp_path)
    dana = {r["sender"] for r in records if r["sender"].startswith("Dana")}
    assert len(dana) == 1  # one placeholder for Dana in both inboxes
    # Her phone number also gets one placeholder in both inboxes.
    phones = {word.strip(".") for r in records for word in r["body"].split() if word.startswith("PHONE_")}
    assert len(phones) == 1


def test_message_ids_unique_and_identical_across_runs(tmp_path):
    setup_data(tmp_path)
    run(tmp_path)
    first = (tmp_path / "processed" / "messages.jsonl").read_bytes()
    run(tmp_path)
    assert (tmp_path / "processed" / "messages.jsonl").read_bytes() == first
    ids = [r["message_id"] for r in read_messages(tmp_path)]
    assert len(ids) == len(set(ids))


def test_manifest_counts_add_up_and_hash_every_file(tmp_path):
    setup_data(tmp_path)
    run(tmp_path)
    manifest = json.loads((tmp_path / "processed" / "manifest.json").read_text())
    counts = manifest["counts"]
    assert counts["per_user"] == {"user_01": 2, "user_02": 2}
    assert sum(counts["per_user"].values()) == counts["total"] == 4
    assert sum(counts["per_label"].values()) == counts["total"]
    assert set(manifest["sha256"]) == {"data/raw/threads.jsonl", "data/source/users.json", "data/processed/messages.jsonl"}
    assert manifest["created_at"].endswith("Z") and manifest["git_commit"]


def test_missing_input_fails(tmp_path):
    assert run(tmp_path) == 1
    assert not (tmp_path / "processed").exists()


def test_bad_input_fails_and_keeps_previous_output(tmp_path):
    setup_data(tmp_path)
    assert run(tmp_path) == 0
    before = (tmp_path / "processed" / "messages.jsonl").read_bytes()
    (tmp_path / "raw" / "threads.jsonl").write_text('{"user_id": "user_01"}\n')  # missing fields
    assert run(tmp_path) == 1
    assert (tmp_path / "processed" / "messages.jsonl").read_bytes() == before
    assert [p.name for p in (tmp_path / "processed").iterdir() if p.name.endswith(".tmp")] == []


# --- Checks on the real corpus (skipped if it hasn't been generated / pulled) ---

REAL = Path(__file__).resolve().parents[2] / "data" / "processed" / "messages.jsonl"
needs_corpus = pytest.mark.skipif(not REAL.exists(), reason="run ingest and preprocess first (or dvc pull)")


@needs_corpus
def test_corpus_every_user_has_all_six_labels():
    labels = {}
    for record in map(json.loads, REAL.read_text().splitlines()):
        labels.setdefault(record["user_id"], set()).add(record["label"])
    assert all(len(found) == 6 for found in labels.values()), labels


@needs_corpus
def test_corpus_shared_contacts_appear_for_two_or_more_users():
    users_by_sender = {}
    for record in map(json.loads, REAL.read_text().splitlines()):
        users_by_sender.setdefault(record["sender"], set()).add(record["user_id"])
    shared = {sender for sender, users in users_by_sender.items() if len(users) >= 2}
    names = {sender.split(" <")[0] for sender in shared}
    for person in ["Dana Whitfield", "Nadia Brooks", "Jordan Lee", "Tess Navarro", "Elena Vasquez", "Rohan Mehta"]:
        assert person in names, f"{person} should write to 2+ users"
    # And each shared person has exactly one placeholder (same address everywhere).
    assert len(shared) == len(names)


@needs_corpus
def test_corpus_message_ids_unique():
    ids = Counter(json.loads(line)["message_id"] for line in REAL.read_text().splitlines())
    assert max(ids.values()) == 1
