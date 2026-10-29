"""Tests for the prompt builder (no API calls)."""

import pytest

from prompt import RULES_PATH, load_rules, owner_address, strip_sections, system_prompt, user_prompt

RULES = """# Labeling rules

**Version 9.9, 2026-01-01.** Intro.

## 1. Labels

D1 new_request.

## 5. Not adopted (as of v9.9)

- P4 (proposal): would change things.

## 6. Training data

Notes.

## Change log

| 2026 | 9.9 | stuff |
"""


def test_rules_read_from_file_without_proposals_or_change_log(tmp_path):
    path = tmp_path / "rules.md"
    path.write_text(RULES)
    text, version = load_rules(path)
    assert version == "9.9"
    assert "D1 new_request" in text and "## 6. Training data" in text
    assert "Not adopted" not in text and "P4" not in text
    assert "Change log" not in text and "stuff" not in text


def test_missing_section_is_an_error():
    with pytest.raises(ValueError, match="change log"):
        strip_sections(RULES.split("## Change log")[0])


def test_real_rules_file():
    text, version = load_rules(RULES_PATH)
    assert version == "1.2"
    assert "E17 (introductions)" in text and "NR9 (directive move)" in text
    assert "## 5. Not adopted" not in text and "P6 (we'll be in touch)" not in text
    assert "## Change log" not in text
    assert system_prompt(text).endswith(text)


def msg(position, sender, body):
    return {
        "position": position,
        "sender": sender,
        "recipients": ["Priya Shah <EMAIL_001>"],
        "timestamp": f"2026-10-0{position + 1}T09:00:00-04:00",
        "subject": "Coffee chat",
        "body": body,
    }


THREAD = [
    msg(0, "Priya Shah <EMAIL_001>", "FIRST: could we chat?"),
    msg(1, "Jordan Lee <EMAIL_002>", "SECOND: Tue 2pm or Wed 3pm?"),
    msg(2, "Priya Shah <EMAIL_001>", "THIRD: Tue 2pm works."),
    msg(3, "Jordan Lee <EMAIL_002>", "FOURTH: great, see you then."),
]


def test_user_prompt_has_earlier_messages_oldest_first_then_marked_target():
    text = user_prompt(THREAD, 2, "Priya Shah <EMAIL_001>")
    assert text.index("FIRST") < text.index("SECOND") < text.index("=== TARGET MESSAGE") < text.index("THIRD")
    assert "FOURTH" not in text  # later messages are never shown
    target = text.split("=== TARGET MESSAGE")[1]
    assert "From: Priya Shah <EMAIL_001>" in target and "Date: 2026-10-03T09:00:00-04:00" in target
    assert target.rstrip().endswith("=== END OF TARGET MESSAGE ===")
    earlier = text.split("=== TARGET MESSAGE")[0]
    assert "From: Jordan Lee <EMAIL_002>" in earlier and "Date: 2026-10-02T09:00:00-04:00" in earlier
    assert text.startswith("Mailbox owner (the user): Priya Shah <EMAIL_001>")


def test_first_message_has_no_earlier_context():
    text = user_prompt(list(reversed(THREAD)), 0, "Priya Shah")  # input order doesn't matter
    assert "No earlier messages" in text and "SECOND" not in text and "FIRST" in text


def test_owner_address_from_display_name():
    assert owner_address(THREAD, "Priya Shah") == "Priya Shah <EMAIL_001>"
    assert owner_address(THREAD, "Nobody Here") == "Nobody Here"
