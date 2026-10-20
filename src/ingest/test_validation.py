"""Tests for validation.py and the fake-corpus rules in validate.py."""

import copy

from validate import generated_corpus_errors
from validation import parse_timestamp, validate_thread

USERS = {"user_01", "user_02"}

GOOD_THREAD = {
    "user_id": "user_01",
    "thread_id": "t001",
    "subject": "Advising appointment",
    "participants": [
        "Priya Shah <priya.shah@example.com>",
        "Dana Whitfield <dana.whitfield@careers.college.example>",
    ],
    "messages": [
        {
            "sender": "Priya Shah <priya.shah@example.com>",
            "recipients": ["Dana Whitfield <dana.whitfield@careers.college.example>"],
            "timestamp": "Thu, 03 Sep 2026 10:02:00 -0400",
            "body": "Hi Dana, could I book an appointment?",
            "label": "new_request",
        },
        {
            "sender": "Dana Whitfield <dana.whitfield@careers.college.example>",
            "recipients": ["Priya Shah <priya.shah@example.com>"],
            "timestamp": "Thu, 03 Sep 2026 14:30:00 -0400",
            "body": "Tue Sep 8 at 3:00 or 3:30?\n\nDana Whitfield\n(617) 555-0142",
            "label": "proposed_times",
        },
    ],
}


def thread_with(**changes):
    """A copy of GOOD_THREAD with some top-level fields changed."""
    thread = copy.deepcopy(GOOD_THREAD)
    thread.update(changes)
    return thread


def test_good_thread_has_no_errors():
    assert validate_thread(GOOD_THREAD, USERS) == []
    assert generated_corpus_errors(GOOD_THREAD) == ([], [])


def test_parse_timestamp_keeps_offset():
    parsed = parse_timestamp("Tue, 13 Oct 2026 09:12:00 -0400")
    assert parsed.isoformat() == "2026-10-13T09:12:00-04:00"


def test_missing_field():
    thread = copy.deepcopy(GOOD_THREAD)
    del thread["subject"]
    assert any("missing field 'subject'" in e for e in validate_thread(thread, USERS))


def test_unknown_and_badly_formatted_user_id():
    assert any("unknown user_id" in e for e in validate_thread(thread_with(user_id="user_99"), USERS))
    assert any("lowercase" in e for e in validate_thread(thread_with(user_id="User-01"), USERS))


def test_message_user_id_must_match_thread():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["messages"][1]["user_id"] = "user_02"
    assert any("differs from the thread's" in e for e in validate_thread(thread, USERS))


def test_bad_label_and_timestamp():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["messages"][0]["label"] = "meeting"
    thread["messages"][1]["timestamp"] = "next tuesday"
    errors = validate_thread(thread, USERS)
    assert any("label 'meeting'" in e for e in errors)
    assert any("unparseable timestamp" in e for e in errors)


def test_messages_out_of_order():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["messages"][1]["timestamp"] = "Thu, 03 Sep 2026 09:00:00 -0400"
    assert any("earlier than the message before" in e for e in validate_thread(thread, USERS))


def test_sender_must_be_a_participant():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["messages"][1]["sender"] = "Someone Else <someone@college.example>"
    assert any("not in participants" in e for e in validate_thread(thread, USERS))


def test_corpus_rules_catch_real_domain_and_wrong_weekday():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["participants"][1] = "Dana Whitfield <dana@mail.test>"
    thread["messages"][0]["timestamp"] = "Fri, 03 Sep 2026 10:02:00 -0400"  # Sep 3 is a Thursday
    errors, _warnings = generated_corpus_errors(thread)
    assert any("not a fictional" in e for e in errors)
    assert any("wrong weekday" in e for e in errors)


def test_corpus_rules_warn_on_real_looking_phone():
    thread = copy.deepcopy(GOOD_THREAD)
    thread["messages"][1]["body"] = "Call me at (617) 495-1000."
    _errors, warnings = generated_corpus_errors(thread)
    assert warnings
