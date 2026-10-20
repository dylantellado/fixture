"""Input: sample fallback, and validation failures that must stop the job."""

import logging

import pytest

from helpers import SAMPLES_DIR, make_message, write_pipeline_data
from inputs import InputError, find_input_files, load_and_validate

USERS = [{"user_id": "user_01", "name": "Priya Shah"}]


def validate(data_dir, messages, users=USERS):
    """Write the files and run the same load + validate step as the job."""
    write_pipeline_data(data_dir, messages, users)
    return load_and_validate(find_input_files(data_dir, SAMPLES_DIR))


def error_text(data_dir, messages, users=USERS) -> str:
    with pytest.raises(InputError) as excinfo:
        validate(data_dir, messages, users)
    return str(excinfo.value)


# --- Finding the input ---


def test_falls_back_to_samples_with_warning(data_dir, caplog):
    with caplog.at_level(logging.WARNING):
        files = find_input_files(data_dir, SAMPLES_DIR)
    assert files.used_sample
    assert files.messages_path == SAMPLES_DIR / "messages_sample.jsonl"
    assert files.users_path == SAMPLES_DIR / "users.json"
    assert files.manifest_path is None
    assert "SAMPLE DATA USED" in caplog.text


def test_prefers_pipeline_output_and_manifest(data_dir):
    write_pipeline_data(data_dir, [make_message()], USERS, manifest={"git_commit": "abc"})
    files = find_input_files(data_dir, SAMPLES_DIR)
    assert not files.used_sample
    assert files.messages_path == data_dir / "processed" / "messages.jsonl"
    assert files.users_path == data_dir / "source" / "users.json"
    assert files.manifest_path == data_dir / "processed" / "manifest.json"


def test_committed_samples_are_valid():
    users, messages, manifest = load_and_validate(find_input_files(SAMPLES_DIR / "missing", SAMPLES_DIR))
    assert len(messages) == 20
    assert {u["user_id"] for u in users} == {"user_01", "user_02"}
    assert manifest == {}


def test_valid_pipeline_data_passes(data_dir):
    users, messages, _ = validate(data_dir, [make_message()])
    assert len(messages) == 1


# --- Validation failures ---


def test_missing_field_fails(data_dir):
    message = make_message()
    del message["subject"]
    assert "missing field 'subject'" in error_text(data_dir, [message])


def test_null_field_fails(data_dir):
    # The contract says no nulls; "" is the value for missing strings.
    assert "'sender' must be a str" in error_text(data_dir, [make_message(sender=None)])


def test_recipients_must_be_a_list(data_dir):
    assert "'recipients' must be a list" in error_text(data_dir, [make_message(recipients="a")])


@pytest.mark.parametrize("bad_user_id", ["User_01", "user-01", "user 01", "", "user_01_"])
def test_bad_user_id_fails(data_dir, bad_user_id):
    users = [{"user_id": bad_user_id, "name": "X"}]
    text = error_text(data_dir, [make_message(user_id=bad_user_id)], users)
    assert "user_id" in text


def test_user_missing_from_users_json_fails(data_dir):
    text = error_text(data_dir, [make_message(user_id="user_09")])
    assert "'user_09' is not in users.json" in text


def test_unknown_label_fails(data_dir):
    assert "label 'meeting'" in error_text(data_dir, [make_message(label="meeting")])


def test_duplicate_message_id_fails(data_dir):
    messages = [make_message(), make_message(thread_id="t002")]  # same message_id
    assert "duplicate message_id 'abc123def4567890'" in error_text(data_dir, messages)


@pytest.mark.parametrize("bad_timestamp", ["2026-10-13T09:12:00", "next Tuesday"])
def test_timestamp_without_offset_fails(data_dir, bad_timestamp):
    assert "UTC offset" in error_text(data_dir, [make_message(timestamp=bad_timestamp)])


def test_empty_messages_file_fails(data_dir):
    assert "no messages" in error_text(data_dir, [])


def test_invalid_json_line_fails(data_dir):
    write_pipeline_data(data_dir, [make_message()], USERS)
    with open(data_dir / "processed" / "messages.jsonl", "a", encoding="utf-8") as f:
        f.write("{not json\n")
    with pytest.raises(InputError, match="line 2: not valid JSON"):
        load_and_validate(find_input_files(data_dir, SAMPLES_DIR))


def test_missing_users_file_fails(data_dir):
    write_pipeline_data(data_dir, [make_message()], USERS)
    (data_dir / "source" / "users.json").unlink()
    with pytest.raises(InputError, match="Users file not found"):
        load_and_validate(find_input_files(data_dir, SAMPLES_DIR))


def test_duplicate_user_in_users_json_fails(data_dir):
    assert "duplicate user_id 'user_01'" in error_text(data_dir, [make_message()], USERS + USERS)


def test_all_problems_are_listed_together(data_dir):
    messages = [make_message(label="bad"), make_message(message_id="other", user_id="Bad")]
    text = error_text(data_dir, messages)
    assert "2 problem(s)" in text
    assert "label 'bad'" in text and "user_id 'Bad'" in text
