"""Tests for the tuning harness. Gemini and W&B are never called."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import data  # noqa: E402
import main  # noqa: E402
from harness import load_harness, user_prompt  # noqa: E402
from scoring import binary, score  # noqa: E402

HERE = Path(__file__).parent
PROD = HERE / "harnesses" / "prod_v1.yaml"


def test_prod_harness_matches_the_classifier_and_hides_rule_history():
    harness = load_harness(PROD)
    assert harness.rules_version
    assert "## Change log" not in harness.system and "Not adopted" not in harness.system
    assert "# Labeling rules" in harness.system and "NR1" in harness.system
    assert harness.summary()["harness_sha"] == harness.sha


def test_simple_harness_sends_no_rules():
    harness = load_harness(HERE / "harnesses" / "simple_v1.yaml")
    assert harness.rules_version == "none" and harness.rules_text == ""
    assert "NR1" not in harness.system and "# Labeling rules" not in harness.system
    for label in ("new_request", "proposed_times", "acceptance", "reschedule", "assistant_handoff", "none"):
        assert f"- {label}:" in harness.system
    assert harness.summary()["rules_path"] is None


def test_rules_override_is_recorded(tmp_path):
    draft = tmp_path / "rules.md"
    text = (Path(__file__).resolve().parents[2] / "docs/data/labeling_rules.md").read_text()
    draft.write_text(text.replace("**Version 1.5", "**Version 9.9"))
    harness = load_harness(PROD, draft)
    assert harness.rules_version == "9.9" and harness.config["rules_path"] == str(draft)


def make_root(tmp_path: Path) -> Path:
    """A tiny data root: one train user with a 2-message thread, one eval user."""
    (tmp_path / "source").mkdir(parents=True)
    (tmp_path / "processed").mkdir(parents=True)
    users = [{"user_id": "user_05", "name": "Daniel Kim", "email": "d@example.com"},
             {"user_id": "user_11", "name": "Lucas Moreau", "email": "l@example.com"}]
    (tmp_path / "source" / "users.json").write_text(json.dumps(users))
    (tmp_path / "source" / "splits.json").write_text(json.dumps({"train": ["user_05"], "eval": ["user_11"]}))
    messages, answers = [], []
    for user, name in (("user_05", "Daniel Kim"), ("user_11", "Lucas Moreau")):
        for pos, (sender, needs) in enumerate([("Ana Lopez <EMAIL_001>", True), (f"{name} <EMAIL_002>", False)]):
            messages.append({"message_id": data.message_id(user, "g001", pos), "user_id": user, "thread_id": "g001",
                             "sender": sender, "recipients": [], "timestamp": "2026-10-05T09:00:00-04:00",
                             "subject": "Chat", "body": "Free Tue at 3?", "label": "proposed_times"})
            answers.append({"user_id": user, "thread_id": "g001", "position": pos, "needs_response": needs})
    (tmp_path / "processed" / "messages.jsonl").write_text("".join(json.dumps(m) + "\n" for m in messages))
    (tmp_path / "source" / "annotations.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
    states = {"user_id": "user_05", "thread_id": "g001", "states": [{"position": 0, "act": "propose"},
                                                                   {"position": 1, "act": "accept"}]}
    (tmp_path / "source" / "thread_states.jsonl").write_text(json.dumps(states) + "\n")
    return tmp_path


def paths_for(root: Path) -> dict:
    return {"messages": root / "processed/messages.jsonl", "annotations": root / "source/annotations.jsonl",
            "users": root / "source/users.json", "splits": root / "source/splits.json",
            "states": root / "source/thread_states.jsonl"}


def test_load_keeps_only_the_split_and_marks_the_user(tmp_path):
    threads, versions = data.load("train", paths_for(make_root(tmp_path)))
    assert list(threads) == [("user_05", "g001")]
    first, second = threads[("user_05", "g001")]
    assert (first["from_user"], second["from_user"]) == (False, True)
    assert first["act"] == "propose" and first["source_set"] == "generated"
    assert set(versions) >= {"messages_md5", "annotations_md5", "splits_md5"}


def test_eval_v1_is_never_read():
    with pytest.raises(data.DataError):
        data.read_text("data/eval/v1/threads.jsonl")


def test_prompt_never_shows_later_messages(tmp_path):
    threads, _ = data.load("train", paths_for(make_root(tmp_path)))
    thread = threads[("user_05", "g001")]
    harness = load_harness(PROD)
    first = user_prompt(harness, thread, 0)
    assert "first message in its thread" in first and "sent by the user" not in first
    assert "(sent by the user)" in user_prompt(harness, thread, 1)


def test_scoring():
    assert binary([(True, True), (True, False), (False, True), (False, False)])["missed"] == 1
    preds = [{"true_needs_response": True, "needs_response": False, "label": "none", "true_label": "proposed_times",
              "source_set": "generated", "act": "propose", "error": None},
             {"true_needs_response": False, "needs_response": None, "label": None, "true_label": "none",
              "source_set": "v1", "act": "", "error": "boom"}]
    result = score(preds)
    assert result["needs_response/missed"] == 1 and result["failures"] == 1
    assert result["by_act/propose/needs_response_accuracy"] == 0.0


def test_run_end_to_end_with_a_fake_model(tmp_path, monkeypatch):
    root = make_root(tmp_path / "data")
    monkeypatch.setattr(main, "gemini_client", lambda location: None)
    monkeypatch.setattr(main, "classify", lambda client, harness, prompt: {
        "label": "proposed_times", "needs_response": "sent by the user" not in prompt, "reason": "D2; NR1"})
    monkeypatch.setattr(main, "HERE", tmp_path)
    assert main.main(["--harness", str(PROD), "--data-root", str(root), "--no-wandb"]) == 0
    run = next((tmp_path / "runs").iterdir())
    predictions = [json.loads(l) for l in (run / "predictions.jsonl").read_text().splitlines()]
    assert len(predictions) == 2 and all(p["user_id"] == "user_05" for p in predictions)
    assert "needs_response/accuracy | 1.000" in (run / "report.md").read_text()
