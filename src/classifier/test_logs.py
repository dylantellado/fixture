"""Tests for the structured JSON logs (logs.py) and for the self-contained Cloud Run
image: startup with the bundled rules file, and what goes into the build folder.

All emails here are made up. Every field of the test thread carries a SECRET-... marker,
and no marker may appear in any log line.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gemini
import logs
import main
import prompt

HERE = Path(__file__).resolve().parent
client = TestClient(main.app)

SECRET_THREAD = [
    {"from": "SECRET-SENDER Jordan Lee <secret-sender@example.com>", "to": "SECRET-TO <secret-to@example.edu>",
     "date": "Tue, 13 Oct 2026 09:12:00 -0400", "subject": "SECRET-SUBJECT Coffee chat?",
     "body": "Could we find 20 minutes next week? SECRET-BODY-1"},
    {"from": "Sam Student <sam@example.edu>", "date": "Tue, 13 Oct 2026 10:00:00 -0400",
     "subject": "Re: SECRET-SUBJECT Coffee chat?", "body": "Sure! Tue 2-4 or Wed after 1? SECRET-BODY-2",
     "from_user": True},
]
SECRET_REASON = "D1: asks to meet. SECRET-REASON"
SECRETS = ["SECRET", "secret-sender@example.com", "secret-to@example.edu", "Coffee chat", "20 minutes",
           "Tue 2-4"]


class FakeLabeler:
    def __init__(self, error=None):
        self.error = error

    def label(self, system, user):
        if self.error:
            raise self.error
        return {"label": "new_request", "needs_response": True, "reason": SECRET_REASON,
                "usage": {"attempts": 1, "input_tokens": 7000, "output_tokens": 30, "thinking_tokens": 0}}


def classify_and_capture(caplog, labeler, **extra):
    """POST /classify with the secret thread; return (response, JSON log lines, raw log text)."""
    main.app.dependency_overrides[main.get_labeler] = lambda: labeler
    try:
        with caplog.at_level(logging.DEBUG):  # every logger, every level
            response = client.post("/classify", json={"thread": SECRET_THREAD, "target_index": 0, **extra})
    finally:
        main.app.dependency_overrides.clear()
    formatter = logs.JsonFormatter()
    raw = [formatter.format(record) for record in caplog.records]
    return response, [json.loads(line) for line in raw], "\n".join(raw)


def classify_line(lines):
    found = [line for line in lines if line.get("event") == "classify"]
    assert len(found) == 1, "exactly one classify log line per request"
    return found[0]


# --- the formatter --------------------------------------------------------------


def record(msg="hello", level=logging.INFO, fields=None, exc_info=None):
    r = logging.LogRecord("classifier", level, __file__, 1, msg, None, exc_info)
    if fields is not None:
        r.fields = fields
    return r


def test_formatter_writes_cloud_logging_json():
    line = json.loads(logs.JsonFormatter().format(record("classified", logging.WARNING,
                                                         {"event": "classify", "label": "none"})))
    assert line["severity"] == "WARNING" and line["message"] == "classified"
    assert line["time"].endswith("Z") and line["logger"] == "classifier"
    assert line["event"] == "classify" and line["label"] == "none"


def test_formatter_drops_fields_not_on_the_allow_list():
    fields = {"label": "none", "body": "SECRET", "subject": "SECRET", "reason": "SECRET", "from": "SECRET",
              "to": "SECRET", "message_id": None}
    line = json.loads(logs.JsonFormatter().format(record(fields=fields)))
    assert line["label"] == "none"
    assert "SECRET" not in json.dumps(line)
    assert "message_id" not in line  # None values are left out


def test_allow_list_has_no_email_fields():
    assert not {"body", "subject", "from", "to", "sender", "recipients", "reason", "thread"} & logs.ALLOWED_FIELDS


def test_stack_traces_keep_the_type_but_not_the_message():
    # Raised from a variable: the trace shows the raise line's source code, which in real
    # code never holds email text.
    quoted = "SECRET-BODY-TEXT quoted in an exception"
    try:
        raise ValueError(quoted)
    except ValueError:
        line = json.loads(logs.JsonFormatter().format(record(level=logging.ERROR, exc_info=sys.exc_info())))
    assert "ValueError" in line["stack_trace"] and "test_logs.py" in line["stack_trace"]
    assert "SECRET" not in line["stack_trace"]


# --- what /classify logs ------------------------------------------------------------


def test_classify_logs_one_structured_line_without_email_text(caplog):
    response, lines, raw = classify_and_capture(caplog, FakeLabeler(), message_id="msg-123")
    assert response.status_code == 200 and response.json()["reason"] == SECRET_REASON
    line = classify_line(lines)
    assert line["severity"] == "INFO" and line["outcome"] == "ok" and line["status"] == 200
    assert line["message_id"] == "msg-123"
    assert line["label"] == "new_request" and line["needs_response"] is True
    assert isinstance(line["latency_ms"], int)
    assert line["model"] == main.MODEL and line["rules_version"] == main.RULES_VERSION
    assert (line["input_tokens"], line["output_tokens"], line["thinking_tokens"], line["attempts"]) == (7000, 30, 0, 1)
    assert line["thread_length"] == 2 and line["target_index"] == 0
    for secret in SECRETS:
        assert secret not in raw


def test_classify_without_message_id_leaves_it_out(caplog):
    _, lines, _ = classify_and_capture(caplog, FakeLabeler())
    assert "message_id" not in classify_line(lines)


def test_gemini_failure_is_logged_as_error_without_email_text(caplog):
    error = gemini.GeminiError("Gemini returned an error (404)", 502, kind="api_error", code=404)
    response, lines, raw = classify_and_capture(caplog, FakeLabeler(error=error), message_id="msg-9")
    assert response.status_code == 502
    line = classify_line(lines)
    assert line["severity"] == "ERROR" and line["outcome"] == "error"
    assert line["error_type"] == "api_error" and line["status"] == 502 and line["gemini_code"] == 404
    assert "label" not in line and isinstance(line["latency_ms"], int)
    for secret in SECRETS:
        assert secret not in raw


def test_unexpected_failure_logs_stack_trace_without_email_text(caplog):
    error = RuntimeError("bug that quotes SECRET-BODY-1 from the email")
    response, lines, raw = classify_and_capture(caplog, FakeLabeler(error=error))
    assert response.status_code == 500
    line = classify_line(lines)
    assert line["outcome"] == "error" and line["error_type"] == "RuntimeError" and line["status"] == 500
    assert "RuntimeError" in line["stack_trace"]
    for secret in SECRETS:
        assert secret not in raw


def test_gemini_retries_are_logged_with_the_code_only(caplog):
    calls = []

    def call():
        calls.append(1)
        if len(calls) < 2:
            raise gemini.errors.APIError(429, {"error": {"message": "SECRET from the API", "status": "X"}})
        return "ok"

    with caplog.at_level(logging.DEBUG):
        gemini.with_retries(call, sleep=lambda _: None)
    lines = [json.loads(logs.JsonFormatter().format(r)) for r in caplog.records]
    retry = [line for line in lines if line.get("event") == "gemini_retry"]
    assert len(retry) == 1 and retry[0]["gemini_code"] == 429 and retry[0]["severity"] == "WARNING"
    assert "SECRET" not in json.dumps(lines)


# --- startup with the bundled rules file (what the Cloud Run image does) -------------


def start_service(rules_path) -> subprocess.CompletedProcess:
    """Import main in a fresh Python, as uvicorn does at startup, with RULES_PATH set."""
    env = {**os.environ, "RULES_PATH": str(rules_path)}
    return subprocess.run([sys.executable, "-c", "import main"], cwd=HERE, env=env,
                          capture_output=True, text=True, timeout=120)


def test_startup_with_bundled_rules_logs_version_and_sha256(tmp_path):
    # The image keeps the rules at /app/labeling_rules.md, next to main.py.
    bundled = tmp_path / "labeling_rules.md"
    bundled.write_bytes(prompt.RULES_PATH.read_bytes())

    result = start_service(bundled)
    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines()]  # every line is JSON
    startup = [line for line in lines if line.get("event") == "startup"]
    assert len(startup) == 1
    text = bundled.read_text(encoding="utf-8")
    assert startup[0]["rules_version"] == prompt.rules_version(text)
    assert startup[0]["rules_sha256"] == hashlib.sha256(bundled.read_bytes()).hexdigest()
    assert startup[0]["rules_path"] == str(bundled)
    assert startup[0]["severity"] == "INFO" and startup[0]["thinking_budget"] == 128


@pytest.mark.parametrize("contents", [None, "# Labeling rules with no version line\n"])
def test_startup_fails_without_a_valid_rules_file(tmp_path, contents):
    rules = tmp_path / "labeling_rules.md"
    if contents is not None:
        rules.write_text(contents, encoding="utf-8")
    assert start_service(rules).returncode != 0


# --- the Cloud Run build folder (cloud/build_context.sh) ----------------------------


def git(*args) -> bytes:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, check=True).stdout


def test_build_folder_has_the_exact_committed_rules_and_nothing_private(tmp_path):
    subprocess.run(["bash", str(HERE / "cloud" / "build_context.sh"), str(tmp_path)], check=True)
    files = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}

    # The exact rules file from the last commit, where the Dockerfile expects it.
    assert (tmp_path / "labeling_rules.md").read_bytes() == git("show", "HEAD:docs/data/labeling_rules.md")
    assert {"Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", ".python-version",
            "main.py", "prompt.py", "gemini.py", "labeling_rules.md"} <= files
    # Nothing else from the repo: no training notes, no data, no tests, no subfolders.
    assert all("/" not in f for f in files)
    assert not [f for f in files if f.startswith("test_") or "training_conflicts" in f or "data" == f]


def test_dockerfile_reads_bundled_rules_and_respects_port():
    dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
    assert "WORKDIR /app" in dockerfile and "RULES_PATH=/app/labeling_rules.md" in dockerfile
    assert "${PORT:-8002}" in dockerfile
    assert "uv sync --locked --no-dev" in dockerfile
