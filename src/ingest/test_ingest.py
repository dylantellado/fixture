"""Tests for ingest (main.py and collectors.py), using small fake files."""

import copy
import json

import pytest

from collectors import FileCollector, LLMCollector
from main import ingest_threads, run

USERS = [
    {"user_id": "user_01", "name": "Priya Shah", "email": "priya.shah@example.com"},
    {"user_id": "user_02", "name": "Marcus Bell", "email": "marcus.bell@example.com"},
]
KNOWN = {u["user_id"] for u in USERS}


def make_thread(user_id="user_01", thread_id="t001", body="Could we meet Tuesday?"):
    """A small valid thread. Change the arguments to make variations."""
    return {
        "user_id": user_id,
        "thread_id": thread_id,
        "subject": "Coffee chat",
        "participants": ["Dana Whitfield <dana.whitfield@careers.college.example>", "Student <student@example.com>"],
        "messages": [
            {
                "sender": "Student <student@example.com>",
                "recipients": ["Dana Whitfield <dana.whitfield@careers.college.example>"],
                "timestamp": "Thu, 03 Sep 2026 10:02:00 -0400",
                "body": body,
                "label": "new_request",
            }
        ],
    }


def records(*threads):
    """Pair threads with a fake origin, like a collector does."""
    return [(t, {"file": "source/test.jsonl", "line": i}) for i, t in enumerate(threads, start=1)]


def write_source(data_dir, threads, users=USERS):
    source = data_dir / "source"
    source.mkdir(parents=True)
    (source / "users.json").write_text(json.dumps(users))
    (source / "generated_threads.jsonl").write_text("".join(json.dumps(t) + "\n" for t in threads))


# --- ingest_threads: validation, dedup, provenance ---


def test_valid_threads_get_source_and_provenance():
    result = ingest_threads(records(make_thread()), KNOWN, "generated")
    assert result.errors == []
    [thread] = result.threads
    assert thread["user_id"] == "user_01"
    assert thread["source"] == "generated"
    assert thread["provenance"]["line"] == 1
    assert len(thread["provenance"]["sha256"]) == 64


def test_exact_duplicate_thread_is_dropped():
    result = ingest_threads(records(make_thread(), make_thread()), KNOWN, "generated")
    assert len(result.threads) == 1
    assert result.duplicate_threads == 1


def test_same_id_different_content_is_an_error():
    result = ingest_threads(records(make_thread(), make_thread(body="Different text")), KNOWN, "generated")
    assert any("different content" in e for e in result.errors)


def test_same_email_in_two_inboxes_is_kept_for_both_users():
    result = ingest_threads(records(make_thread("user_01"), make_thread("user_02")), KNOWN, "generated")
    assert [t["user_id"] for t in result.threads] == ["user_01", "user_02"]
    assert result.duplicate_threads == 0


def test_repeated_message_within_a_thread_is_dropped():
    thread = make_thread()
    thread["messages"].append(copy.deepcopy(thread["messages"][0]))
    result = ingest_threads(records(thread), KNOWN, "generated")
    assert len(result.threads[0]["messages"]) == 1
    assert result.duplicate_messages == 1


def test_invalid_thread_is_reported_with_its_line():
    result = ingest_threads(records(make_thread(user_id="user_99")), KNOWN, "generated")
    assert result.threads == []
    assert any("line 1" in e and "unknown user_id" in e for e in result.errors)


def test_output_order_does_not_depend_on_input_order():
    a, b, c = make_thread("user_02", "t001"), make_thread("user_01", "t002"), make_thread("user_01", "t001")
    first = ingest_threads(records(a, b, c), KNOWN, "generated").threads
    second = ingest_threads(records(c, a, b), KNOWN, "generated").threads
    key = lambda t: (t["user_id"], t["thread_id"])  # noqa: E731
    assert [key(t) for t in first] == [key(t) for t in second] == [("user_01", "t001"), ("user_01", "t002"), ("user_02", "t001")]


# --- run: files in, files out ---


def test_run_writes_threads_and_is_identical_across_runs(tmp_path):
    write_source(tmp_path, [make_thread("user_02"), make_thread("user_01")])
    assert run(tmp_path) == 0
    output = tmp_path / "raw" / "threads.jsonl"
    first = output.read_bytes()
    assert run(tmp_path) == 0
    assert output.read_bytes() == first  # same input, byte-identical output
    lines = [json.loads(line) for line in first.decode().splitlines()]
    assert [t["user_id"] for t in lines] == ["user_01", "user_02"]
    # no temp files left behind
    assert [p.name for p in (tmp_path / "raw").iterdir()] == ["threads.jsonl"]


def test_run_fails_and_writes_nothing_on_invalid_data(tmp_path):
    bad = make_thread()
    bad["messages"][0]["label"] = "meeting"
    write_source(tmp_path, [make_thread("user_02"), bad])
    assert run(tmp_path) == 1
    assert not (tmp_path / "raw" / "threads.jsonl").exists()


def test_run_keeps_old_output_when_new_data_is_invalid(tmp_path):
    write_source(tmp_path, [make_thread()])
    assert run(tmp_path) == 0
    good_output = (tmp_path / "raw" / "threads.jsonl").read_bytes()
    (tmp_path / "source" / "generated_threads.jsonl").write_text("{not json\n")
    assert run(tmp_path) == 1
    assert (tmp_path / "raw" / "threads.jsonl").read_bytes() == good_output


def test_run_explains_missing_source(tmp_path, caplog):
    assert run(tmp_path) == 1
    assert "dvc pull" in caplog.text


def test_llm_collector_is_only_a_placeholder():
    with pytest.raises(NotImplementedError):
        list(LLMCollector().threads())


def test_file_collector_skips_blank_lines(tmp_path):
    write_source(tmp_path, [make_thread()])
    path = tmp_path / "source" / "generated_threads.jsonl"
    path.write_text("\n" + path.read_text() + "\n\n")
    assert len(list(FileCollector(tmp_path / "source").threads())) == 1
