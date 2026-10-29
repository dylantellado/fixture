"""Tests for the scoring math (no API calls)."""

import pandas as pd
import pytest

import gemini
from scoring import (
    by_user,
    confusion,
    informative_mistakes,
    label_accuracy,
    needs_response_metrics,
    per_label_table,
    render_report,
    scheduling_recall,
    usage,
)


def row(i, user, true, pred, nr_true, nr_pred, error=None):
    return {
        "message_id": f"m{i}", "user_id": user, "subject": "s", "true_label": true, "pred_label": pred,
        "true_needs_response": nr_true, "pred_needs_response": nr_pred, "reason": "r", "error": error,
        "latency_s": float(i), "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "thinking_tokens": 5,
        "model_version": "gemini-test",
    }  # fmt: skip


@pytest.fixture
def df():
    return pd.DataFrame(
        [
            row(1, "user_01", "acceptance", "acceptance", False, False),
            row(2, "user_01", "proposed_times", "acceptance", True, True),
            row(3, "user_02", "reschedule", "none", True, False),  # scheduling missed
            row(4, "user_03", "none", "none", False, False),
            row(5, "user_04", "none", "new_request", False, True),  # false alarm
            row(6, "user_04", "new_request", "new_request", True, False),  # needs_response missed
            row(7, "user_04", "acceptance", None, False, None, error="APIError: 500"),  # failure
        ]
    )


def test_label_accuracy_skips_failures(df):
    assert label_accuracy(df) == pytest.approx(3 / 6)


def test_per_label_table(df):
    t = per_label_table(df)
    # acceptance: predicted twice (1 right), true once (found).
    assert t.loc["acceptance", "precision"] == pytest.approx(0.5)
    assert t.loc["acceptance", "recall"] == pytest.approx(1.0)
    assert t.loc["acceptance", "f1"] == pytest.approx(2 / 3)
    # none: predicted twice (1 right), true twice (1 found).
    assert t.loc["none", "precision"] == pytest.approx(0.5) and t.loc["none", "recall"] == pytest.approx(0.5)
    assert t.loc["assistant_handoff", "support"] == 0 and t.loc["assistant_handoff", "f1"] == 0


def test_confusion(df):
    c = confusion(df)
    assert c.loc["reschedule", "none"] == 1
    assert c.loc["proposed_times", "acceptance"] == 1
    assert c.values.sum() == 6


def test_scheduling_recall(df):
    s = scheduling_recall(df)
    assert s["n"] == 4 and s["missed"] == 1 and s["recall"] == pytest.approx(0.75)
    assert s["n_none"] == 2 and s["false_alarms"] == 1


def test_needs_response(df):
    nr = needs_response_metrics(df)
    # true: m2, m3, m6. predicted true: m2, m5.
    assert nr["accuracy"] == pytest.approx(3 / 6)
    assert nr["precision"] == pytest.approx(1 / 2)
    assert nr["recall"] == pytest.approx(1 / 3)
    assert nr["missed"] == 2 and nr["extra"] == 1


def test_by_user_groups(df):
    t = by_user(df)
    assert t.loc["user_01–03", "messages"] == 4 and t.loc["user_04", "messages"] == 3
    assert t.loc["user_04", "failures"] == 1
    assert t.loc["user_04", "label_acc"] == pytest.approx(1 / 2)
    assert t.loc["all", "messages"] == 7


def test_usage(df):
    u = usage(df, (1.0, 10.0))
    assert u["input_tokens"] == 700 and u["output_tokens"] == 70 and u["thinking_tokens"] == 35
    assert u["cost_usd"] == pytest.approx((700 * 1.0 + 105 * 10.0) / 1e6)
    assert u["latency_median_s"] == pytest.approx(3.5)  # failures' latency isn't counted
    assert usage(df, None)["cost_usd"] is None


def test_informative_mistakes_worst_first(df):
    m = informative_mistakes(df)
    assert list(m["message_id"]) == ["m3", "m5", "m2", "m6"]
    assert informative_mistakes(df, n=2)["message_id"].tolist() == ["m3", "m5"]


def test_informative_mistakes_spread_over_kinds():
    rows = [row(i, "user_01", "reschedule", "none", True, False) for i in range(30)]
    rows += [row(100, "user_01", "acceptance", "none", False, False)]
    m = informative_mistakes(pd.DataFrame(rows), n=5)
    assert "m100" in m["message_id"].tolist()  # the rare kind isn't crowded out


def test_report_renders(df):
    info = {
        "model": "gemini-test", "model_versions": ["gemini-test"], "project": "p", "location": "l",
        "rules_version": "1.2", "annotation_rules_version": "1.2", "git_commit": "abc", "date": "today",
        "limit": None, "concurrency": 4, "prices": (1.0, 10.0),
    }  # fmt: skip
    text = render_report(df, info)
    assert "**Accuracy: 0.500**" in text and "Failures: 1" in text and "| m3 |" in text
    assert "Hard negatives: not scored" in text


def test_retries_transient_errors_then_gives_up():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise gemini.errors.APIError(429, {"error": {"message": "rate limited"}})
        return "ok"

    assert gemini.with_retries(flaky, sleep=lambda s: None) == ("ok", 3)

    def broken():
        raise gemini.errors.APIError(400, {"error": {"message": "bad request"}})

    with pytest.raises(gemini.errors.APIError):
        gemini.with_retries(broken, sleep=lambda s: None)  # permanent: no retry


def test_parse_answer_rejects_bad_labels():
    assert gemini.parse_answer('{"label": "none", "needs_response": false, "reason": "x"}')["label"] == "none"
    with pytest.raises(ValueError):
        gemini.parse_answer('{"label": "maybe", "needs_response": false, "reason": "x"}')
