"""Tests for the classifier API and the Gemini wrapper. Gemini is never called:
/classify gets a fake labeler, and the wrapper tests use fake errors."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors

import gemini
import main

client = TestClient(main.app)

THREAD = [
    {"from": "Jordan Lee <jordan@example.com>", "date": "Tue, 13 Oct 2026 09:12:00 -0400",
     "subject": "Coffee chat?", "body": "Could we find 20 minutes next week? SECRET-BODY-TEXT"},
    {"from": "Sam Student <sam@example.edu>", "date": "Tue, 13 Oct 2026 10:00:00 -0400",
     "subject": "Re: Coffee chat?", "body": "Sure! Tue 2-4 or Wed after 1?", "from_user": True},
]


class FakeLabeler:
    """Records what it was asked and returns a fixed answer, or raises an error."""

    def __init__(self, answer=None, error=None):
        self.answer = answer or {"label": "new_request", "needs_response": True, "reason": "D1: asks to meet; NR1."}
        self.error = error
        self.calls = []

    def label(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return {**self.answer, "usage": {"attempts": 1, "input_tokens": 10, "output_tokens": 5, "thinking_tokens": 0}}


@pytest.fixture
def fake():
    labeler = FakeLabeler()
    main.app.dependency_overrides[main.get_labeler] = lambda: labeler
    yield labeler
    main.app.dependency_overrides.clear()


def test_health_reports_model_and_rules_version():
    body = client.get("/health").json()
    assert body == {"status": "ok", "model": main.MODEL, "rules_version": main.RULES_VERSION}


def test_classify_returns_answer_and_metadata(fake):
    response = client.post("/classify", json={"thread": THREAD, "target_index": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "new_request"
    assert body["needs_response"] is True
    assert body["reason"] == "D1: asks to meet; NR1."
    assert body["model"] == main.MODEL
    assert body["rules_version"] == main.RULES_VERSION
    assert isinstance(body["latency_ms"], int)
    system, user = fake.calls[0]
    assert system == main.SYSTEM_PROMPT
    assert "<target_email>" in user and "Could we find 20 minutes" in user


def test_users_own_message_never_needs_response(fake):
    # The fake model says true; NR1 overrides it for the user's own message.
    response = client.post("/classify", json={"thread": THREAD, "target_index": 1})
    assert response.json()["needs_response"] is False


@pytest.mark.parametrize("payload", [
    {"thread": [], "target_index": 0},
    {"thread": THREAD, "target_index": 2},
    {"thread": THREAD, "target_index": -1},
    {"target_index": 0},
])
def test_bad_requests_are_rejected(fake, payload):
    assert client.post("/classify", json=payload).status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize("error,status", [
    (gemini.GeminiError("Gemini is rate limited; try again shortly", 503), 503),
    (gemini.GeminiError("Gemini's answer was not valid", 502), 502),
])
def test_failures_return_an_error_never_a_label(error, status):
    main.app.dependency_overrides[main.get_labeler] = lambda: FakeLabeler(error=error)
    try:
        response = client.post("/classify", json={"thread": THREAD, "target_index": 0})
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == status
    assert "label" not in response.json()
    assert response.json()["detail"].startswith("classification failed")


def test_logs_never_contain_email_text(fake, caplog):
    with caplog.at_level(logging.INFO, logger="classifier"):
        client.post("/classify", json={"thread": THREAD, "target_index": 0, "message_id": "abc123"})
    logged = caplog.text
    assert "message_id=abc123" in logged and "label=new_request" in logged
    assert "SECRET-BODY-TEXT" not in logged and "Coffee chat" not in logged


# --- gemini.py ----------------------------------------------------------------


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": "fake", "status": "FAKE"}})


def test_retries_rate_limits_then_succeeds():
    attempts, waits = [], []

    def call():
        attempts.append(1)
        if len(attempts) < 3:
            raise api_error(429)
        return "ok"

    assert gemini.with_retries(call, sleep=waits.append) == ("ok", 3)
    assert len(waits) == 2 and waits[0] < waits[1]  # backoff grows


def test_gives_up_after_max_attempts():
    waits = []

    def call():
        raise api_error(429)

    with pytest.raises(errors.APIError):
        gemini.with_retries(call, max_attempts=3, sleep=waits.append)
    assert len(waits) == 2


def test_permanent_errors_are_not_retried():
    waits = []

    def call():
        raise api_error(400)

    with pytest.raises(errors.APIError):
        gemini.with_retries(call, sleep=waits.append)
    assert waits == []


def test_network_errors_are_transient():
    assert gemini.is_transient(httpx.ConnectError("down"))
    assert not gemini.is_transient(ValueError("bug"))


def test_parse_answer_accepts_valid_json():
    answer = gemini.parse_answer('{"reason": "D2: offers\\n times.", "label": "proposed_times", "needs_response": true}')
    assert answer == {"label": "proposed_times", "needs_response": True, "reason": "D2: offers times."}


@pytest.mark.parametrize("text", [
    "not json",
    "[]",
    '{"label": "maybe", "needs_response": true}',
    '{"label": "none", "needs_response": "yes"}',
])
def test_parse_answer_rejects_bad_answers(text):
    with pytest.raises(ValueError):
        gemini.parse_answer(text)


class FakeModels:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


def labeler_with(outcome, thinking_budget=None) -> gemini.GeminiLabeler:
    labeler = gemini.GeminiLabeler("gemini-test", "test-project", "global", thinking_budget)
    labeler._client = type("FakeClient", (), {"models": FakeModels(outcome)})()
    return labeler


def test_labeler_returns_checked_answer():
    answer = labeler_with(FakeResponse('{"reason": "E2", "label": "none", "needs_response": false}')).label("s", "u")
    assert answer["label"] == "none" and answer["needs_response"] is False
    assert answer["usage"]["attempts"] == 1


def test_labeler_sends_temperature_0_schema_and_thinking_budget():
    labeler = labeler_with(FakeResponse('{"reason": "E2", "label": "none", "needs_response": false}'), thinking_budget=128)
    labeler.label("s", "u")
    config = labeler._client.models.calls[0]["config"]
    assert config.temperature == 0 and config.response_mime_type == "application/json"
    assert config.thinking_config.thinking_budget == 128


def test_service_default_thinking_budget_is_128():
    assert main.THINKING_BUDGET == 128 and main.labeler.thinking_budget == 128


def test_labeler_turns_bad_answer_into_error():
    with pytest.raises(gemini.GeminiError) as raised:
        labeler_with(FakeResponse('{"label": "guess"}')).label("s", "u")
    assert raised.value.status == 502


def test_labeler_turns_permanent_api_error_into_error():
    with pytest.raises(gemini.GeminiError) as raised:
        labeler_with(api_error(404)).label("s", "u")
    assert raised.value.status == 502


def test_labeler_without_project_fails_clearly():
    with pytest.raises(gemini.GeminiError, match="GOOGLE_CLOUD_PROJECT"):
        gemini.GeminiLabeler("gemini-test", None, "global").label("s", "u")
