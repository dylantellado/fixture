"""Checks that data/source/annotations.jsonl lines up with the source threads.

annotations.jsonl holds needs_response for every source message (see the README's
Data contract and docs/data/labeling_rules.md). Ingest doesn't read it, so these
tests make sure it stays complete when the threads change.
"""

import json
from email.utils import parseaddr
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "data" / "source"
THREADS = SOURCE / "generated_threads.jsonl"
ANNOTATIONS = SOURCE / "annotations.jsonl"

needs_source = pytest.mark.skipif(not ANNOTATIONS.exists(), reason="no data/source/annotations.jsonl")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@needs_source
def test_one_annotation_per_source_message():
    messages = {(t["user_id"], t["thread_id"], p) for t in read_jsonl(THREADS) for p in range(len(t["messages"]))}
    keys = [(a["user_id"], a["thread_id"], a["position"]) for a in read_jsonl(ANNOTATIONS)]
    assert len(keys) == len(set(keys)), "a message is annotated twice"
    assert set(keys) == messages


@needs_source
def test_annotation_fields():
    for annotation in read_jsonl(ANNOTATIONS):
        assert isinstance(annotation["needs_response"], bool)
        assert annotation["rule"].startswith("NR")
        assert annotation["rules_version"]


@needs_source
def test_messages_the_user_sent_never_need_a_response():
    # Rule NR1: the user can't owe a reply to their own message.
    emails = {u["user_id"]: u["email"] for u in json.loads((SOURCE / "users.json").read_text())}
    needs_response = {(a["user_id"], a["thread_id"], a["position"]): a["needs_response"] for a in read_jsonl(ANNOTATIONS)}
    for thread in read_jsonl(THREADS):
        for position, message in enumerate(thread["messages"]):
            if parseaddr(message["sender"])[1].lower() == emails[thread["user_id"]]:
                assert not needs_response[(thread["user_id"], thread["thread_id"], position)]
