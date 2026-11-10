"""No email text, names, addresses or draft text in any log line, whatever happens.

Every text field of the request carries a SECRET marker, the fake model's draft
carries one too, and no marker may appear in any captured log line.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

import logs
import main
import pipeline
from classifier_client import ClassifierUnavailable
from conftest import FakeClassifier, FakeEmbedder, FakeGemini, base_request, offer_answer
from gemini import GeminiError

client = TestClient(main.app)
S2 = "Wed, Nov 11, 10:00–10:30 AM EST"
S4 = "Thu, Nov 12, 10:00–10:30 AM EST"
SECRETS = ["SECRET", "secret-sender", "secret-user", "Sam Rivera", "analyst role", "Nov 11", "10:00"]


def secret_request(**changes):
    request = base_request(**changes)
    request["user"] = {"name": "Sam Rivera SECRET-NAME", "email": "secret-user@example.edu",
                       "timezone": "America/New_York"}
    request["thread"][0] |= {"from": "SECRET-SENDER <secret-sender@example.com>", "to": "secret-user@example.edu",
                             "subject": "SECRET-SUBJECT", "body": "SECRET-BODY a call about the analyst role?"}
    request["classification"]["reason"] = "SECRET-REASON"
    request["past_messages"] = [{"id": "p1", "from": "secret-sender@example.com", "subject": "SECRET-PAST-SUBJECT",
                                 "body": "SECRET-PAST-BODY coffee", "date": "Mon, 02 Nov 2026 09:00:00 -0500"}]
    return request


def secret_answer():
    return offer_answer("S2", "S4", text=f"Hi SECRET-DRAFT,\n- {S2}\n- {S4}\nSam") | {
        "context_used": [{"id": "p1", "why": "SECRET-WHY"}]}


def capture(caplog, request, gemini=None, classifier=None, embedder=None):
    deps = pipeline.Deps(gemini=gemini or FakeGemini(secret_answer()), embedder=embedder or FakeEmbedder(),
                         classifier=classifier, model="gemini-test", embedding_model="embedding-test")
    main.app.dependency_overrides[main.get_deps] = lambda: deps
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.post("/draft", json=request)
    finally:
        main.app.dependency_overrides.clear()
    formatter = logs.JsonFormatter()
    raw = [formatter.format(r) for r in caplog.records]
    return response, [json.loads(line) for line in raw], "\n".join(raw)


def draft_line(lines):
    found = [line for line in lines if line.get("event") == "draft"]
    assert len(found) == 1, "exactly one draft log line per request"
    return found[0]


def assert_no_secrets(text):
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} reached a log line"


def test_successful_draft_logs_counts_only(caplog):
    response, lines, raw = capture(caplog, secret_request())
    assert response.json()["status"] == "drafted"
    assert "SECRET-DRAFT" in response.json()["draft_text"]  # the caller gets the draft...
    assert_no_secrets(raw)  # ...the logs never do
    line = draft_line(lines)
    assert line["status"] == "drafted" and line["label"] == "new_request" and line["offered_count"] == 2
    assert line["checks_passed"] == 7 and line["checks_failed"] == 0 and line["attempts"] == 1
    assert line["input_tokens"] == 1000 and line["embedding_tokens"] > 0 and line["context_used"] == 1
    assert line["model"] == "gemini-test" and line["rules_version"] == "1.0" and line["severity"] == "INFO"


def test_failed_checks_log_names_not_details(caplog):
    bad = offer_answer("S2", text=f"Hi SECRET-DRAFT, {S2} or Friday at 4pm SECRET-STRAY? Sam")
    response, lines, raw = capture(caplog, secret_request(), gemini=FakeGemini(bad))
    assert response.json()["status"] == "error"
    assert_no_secrets(raw)
    assert "Friday at 4pm" not in raw
    line = draft_line(lines)
    assert line["failed_checks"] == ["no_other_times_in_text"] and line["severity"] == "ERROR"


@pytest.mark.parametrize("kwargs", [
    {"gemini": FakeGemini(error=GeminiError("Gemini returned an error (400)", kind="api_error", code=400))},
    {"embedder": FakeEmbedder(error=True)},
])
def test_upstream_failures_log_no_secrets(caplog, kwargs):
    _, lines, raw = capture(caplog, secret_request(), **kwargs)
    assert_no_secrets(raw)
    draft_line(lines)


def test_classifier_failure_logs_no_secrets(caplog):
    request = secret_request()
    del request["classification"]
    _, lines, raw = capture(caplog, request, classifier=FakeClassifier(error=ClassifierUnavailable("returned 503")))
    assert_no_secrets(raw)
    assert draft_line(lines)["error_type"] == "classifier_unavailable"


LEAKY_MESSAGE = "SECRET-BODY leaked into an exception message"


def test_unexpected_bug_logs_type_not_message(caplog):
    class Broken:
        def generate_json(self, *args):
            # The traceback shows this source line, so the marker lives in a constant.
            raise RuntimeError(LEAKY_MESSAGE)

    response, lines, raw = capture(caplog, secret_request(), gemini=Broken())
    assert response.status_code == 500 and response.json() == {"detail": "draft failed: internal error"}
    assert_no_secrets(raw)
    assert "RuntimeError" in raw


def test_formatter_drops_unknown_fields():
    record = logging.LogRecord("drafter", logging.INFO, __file__, 1, "hi", None, None)
    record.fields = {"event": "draft", "draft_text": "SECRET", "subject": "SECRET", "status": "drafted"}
    line = json.loads(logs.JsonFormatter().format(record))
    assert line["event"] == "draft" and line["status"] == "drafted"
    assert "draft_text" not in line and "subject" not in line
