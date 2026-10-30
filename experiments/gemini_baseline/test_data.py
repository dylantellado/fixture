"""Tests for the eval-data guard and the training-data checks (no API calls)."""

import json

import pytest

import main
from data import EVAL_DIR, REPO_ROOT, DataError, check_counts, load_training, message_id, refuse_eval_path, refuse_eval_user


@pytest.mark.parametrize(
    "path",
    [
        EVAL_DIR / "v1" / "threads.jsonl",
        EVAL_DIR / "v1" / "processed" / "messages.jsonl",
        EVAL_DIR / "v1.1" / "threads.jsonl",  # later versions of the eval set too
        REPO_ROOT / "data" / "source" / ".." / "eval" / "v1" / "annotations.jsonl",  # sneaks in via ..
        "/somewhere/else/data/eval/v2/messages.jsonl",  # a copy of the repo elsewhere
    ],
)
def test_eval_paths_refused(path):
    with pytest.raises(DataError, match="eval"):
        refuse_eval_path(path)


def test_eval_symlink_refused(tmp_path):
    link = tmp_path / "innocent.jsonl"
    link.symlink_to(EVAL_DIR / "v1" / "threads.jsonl")
    with pytest.raises(DataError, match="eval"):
        refuse_eval_path(link)


def test_training_paths_allowed():
    refuse_eval_path(REPO_ROOT / "data" / "processed" / "messages.jsonl")
    refuse_eval_path(REPO_ROOT / "data" / "source" / "annotations.jsonl")
    refuse_eval_path(REPO_ROOT / "docs" / "data" / "evaluation.md")  # "eval" in a name is fine outside data/eval


def test_eval_users_refused():
    with pytest.raises(DataError, match="eval"):
        refuse_eval_user("eval_01")
    refuse_eval_user("user_01")


@pytest.mark.parametrize(
    "argv",
    [
        ["--users", "eval_01"],
        ["--users", "user_01", "eval_03"],
        ["--messages", str(EVAL_DIR / "v1" / "threads.jsonl")],
        ["--annotations", str(EVAL_DIR / "v1" / "annotations.jsonl")],
    ],
)
def test_cli_exits_on_eval_data(argv, monkeypatch, capsys):
    # If the guard failed, the run would try to reach Gemini: make that blow up instead.
    monkeypatch.setattr(main.gemini, "make_client", lambda *a: pytest.fail("reached the API"))
    assert main.main(argv) == 1
    assert "eval" in capsys.readouterr().err


def test_thinking_budget_default_and_override():
    assert main.parse_args([]).thinking_budget == main.DEFAULT_THINKING_BUDGET == 128
    assert main.parse_args(["--thinking-budget", "512"]).thinking_budget == 512
    assert main.parse_args(["--thinking-budget", "default"]).thinking_budget is None


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_eval_user_inside_a_file_refused(tmp_path):
    """An eval user hidden in an innocently named file is refused too."""
    msg = {"message_id": message_id("eval_01", "t001", 0), "user_id": "eval_01", "thread_id": "t001", "label": "none"}
    ann = {"user_id": "eval_01", "thread_id": "t001", "position": 0, "needs_response": False, "rules_version": "1.2"}
    write_jsonl(tmp_path / "m.jsonl", [msg])
    write_jsonl(tmp_path / "a.jsonl", [ann])
    (tmp_path / "users.json").write_text("[]")
    with pytest.raises(DataError, match="eval_01"):
        load_training(tmp_path / "m.jsonl", tmp_path / "a.jsonl", tmp_path / "users.json")


def test_wrong_counts_stop_the_run():
    messages = [{"label": "none", "true_needs_response": False}] * 10
    with pytest.raises(DataError, match="documented counts"):
        check_counts(messages)


@pytest.mark.skipif(not (REPO_ROOT / "data" / "processed" / "messages.jsonl").exists(), reason="run ingest and preprocess first")
def test_real_training_data_loads():
    messages, owners = load_training()
    assert len(messages) == 377
    assert set(owners) == {"user_01", "user_02", "user_03", "user_04"}
