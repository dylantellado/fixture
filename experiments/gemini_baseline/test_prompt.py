"""Tests for the prompt builder (no API calls)."""

import hashlib
import json
import re

import pytest

import main
from data import EVAL_DIR, REPO_ROOT, TRAINING_USERS, load_training, message_id
from prompt import LABELS, RULES_PATH, load_rules, owner_address, strip_sections, system_prompt, text_sha256, user_prompt

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
    with pytest.raises(ValueError, match="Change log"):
        strip_sections(RULES.split("## Change log")[0])


def test_renamed_section_is_an_error():
    """A renamed heading must fail loudly, not slip into the prompt."""
    with pytest.raises(ValueError, match="Not adopted"):
        strip_sections(RULES.replace("## 5. Not adopted", "## 5. Proposals"))


def test_heading_must_start_with_the_listed_name():
    # "Not adopted" mentioned inside another section's heading doesn't remove that section.
    text = RULES.replace("## 1. Labels", "## 1. Labels (Not adopted ones are in section 5)")
    assert "D1 new_request" in strip_sections(text)


def test_real_rules_file():
    text, version = load_rules(RULES_PATH)
    assert version == "1.4"
    assert "E17 (introductions)" in text and "NR9 (directive move)" in text
    assert "E20 (confirming the user's choice)" in text and "NR10 (introductions" in text
    assert "P6 (we'll be in touch)" not in text and "Open questions for Will" not in text
    assert system_prompt(text).endswith(text)


# ---- Leak checks on the real prompt: the system part and every training user part ----


def training_ids():
    """message_id of every training message, from the annotations (no processed data needed)."""
    with open(REPO_ROOT / "data" / "source" / "annotations.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {message_id(r["user_id"], r["thread_id"], r["position"]) for r in rows}


def eval_ids():
    """message_id of every eval-v1 message. Reads only the keys, to check nothing leaks."""
    with open(EVAL_DIR / "v1" / "annotations.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {message_id(r["user_id"], r["thread_id"], r["position"]) for r in rows}


def real_system_prompt():
    return system_prompt(load_rules(RULES_PATH)[0])


def real_user_prompts():
    if not (REPO_ROOT / "data" / "processed" / "messages.jsonl").exists():
        pytest.skip("run ingest and preprocess first")
    messages, owners = load_training()
    return [user for _m, user in main.build_jobs(messages, owners, TRAINING_USERS, None)]


def test_no_training_message_id_in_prompt():
    ids = training_ids()
    assert len(ids) == 377
    system = real_system_prompt()
    assert not [i for i in ids if i in system]
    # Nothing that even looks like a message id (16 hex characters).
    assert not re.findall(r"\b[0-9a-f]{16}\b", system)
    for user in real_user_prompts():
        assert not [i for i in ids if i in user]


def test_no_eval_id_or_eval_user_in_prompt():
    ids = eval_ids()
    assert len(ids) == 298
    system = real_system_prompt()
    assert "eval_" not in system
    assert not [i for i in ids if i in system]
    for user in real_user_prompts():
        assert "eval_" not in user
        assert not [i for i in ids if i in user]


def test_excluded_headings_absent_and_every_label_defined():
    system = real_system_prompt()
    assert "Not adopted" not in system
    assert "Change log" not in system
    for rule_id, label in zip(["D1", "D2", "D3", "D4", "D5", "D6"], LABELS):
        assert f"| {rule_id} | `{label}` |" in system, f"{rule_id} {label} missing"
    for heading in ["## 1. Labels", "### PR:", "## 2. needs_response", "## 3. Edge cases", "## 4. Tie-break rules"]:
        assert heading in system


def test_rules_hash_is_of_the_text_sent():
    text, _ = load_rules(RULES_PATH)
    assert text_sha256(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert text_sha256(text) != text_sha256(text + " ")


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
