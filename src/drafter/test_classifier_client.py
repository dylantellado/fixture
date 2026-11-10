"""The classifier client the drafter uses when a request has no label.

classifier_client.py is an identical copy of src/frontend/classifier_client.py
(the web app's, with the Cloud Run ID-token helper); its own tests live there.
These check the copy is identical and that the drafter uses it as expected.
No network: httpx and the token source are faked.
"""

import base64
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

import classifier_client
import main
import pipeline
from conftest import FakeEmbedder, FakeGemini, base_request, offer_answer

HERE = Path(__file__).resolve().parent
CLOUD_RUN = "https://fixture-classifier-test.us-east1.run.app"
LABEL = {"label": "new_request", "needs_response": True, "reason": "D1.", "model": "m", "rules_version": "1.5",
         "latency_ms": 5}


def test_same_file_as_the_web_apps_copy():
    frontend = HERE.parent / "frontend" / "classifier_client.py"
    assert (HERE / "classifier_client.py").read_text() == frontend.read_text(), \
        "src/drafter/classifier_client.py must stay identical to src/frontend/classifier_client.py"


def fake_jwt(expires_at: float) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part({'exp': int(expires_at)})}.c2ln"


@pytest.fixture
def server(monkeypatch):
    """Fake classifier: records each request's URL and headers."""
    requests = []

    def post(url, json=None, headers=None, timeout=None):
        requests.append({"url": url, "headers": dict(headers or {}), "json": json})
        return httpx.Response(200, json=LABEL, request=httpx.Request("POST", url))

    monkeypatch.setattr(classifier_client.httpx, "post", post)
    monkeypatch.setattr(classifier_client, "_token", {"audience": None, "value": None, "expires_at": 0.0})
    return requests


def draft_without_label(monkeypatch, url):
    """POST /draft with no classification, using the real classifier_client module."""
    monkeypatch.setenv("CLASSIFIER_URL", url)
    deps = pipeline.Deps(gemini=FakeGemini(offer_answer("S2", "S4", labels=[
        "Wed, Nov 11, 10:00–10:30 AM EST", "Thu, Nov 12, 10:00–10:30 AM EST"])), embedder=FakeEmbedder(),
        classifier=classifier_client, model="gemini-test", embedding_model="embedding-test")
    main.app.dependency_overrides[main.get_deps] = lambda: deps
    request = base_request()
    del request["classification"]
    try:
        return TestClient(main.app).post("/draft", json=request).json()
    finally:
        main.app.dependency_overrides.clear()


def test_local_classifier_is_called_without_a_token(server, monkeypatch):
    body = draft_without_label(monkeypatch, "http://localhost:8002")
    assert body["status"] == "drafted" and body["usage"]["classifier_called"] is True
    assert server[0]["url"] == "http://localhost:8002/classify" and "Authorization" not in server[0]["headers"]
    assert server[0]["json"]["target_index"] == 0 and server[0]["json"]["message_id"] == "test-message"


def test_cloud_run_classifier_gets_an_id_token(server, monkeypatch):
    token = fake_jwt(time.time() + 3600)
    monkeypatch.setattr(classifier_client, "_fetch_id_token", lambda audience: token)
    body = draft_without_label(monkeypatch, CLOUD_RUN)
    assert body["status"] == "drafted"
    assert server[0]["url"] == f"{CLOUD_RUN}/classify"
    assert server[0]["headers"]["Authorization"] == f"Bearer {token}"


def test_no_token_means_classifier_unavailable_and_no_request(server, monkeypatch):
    def expired(audience):
        raise RefreshError("expired login")
    monkeypatch.setattr(classifier_client, "_fetch_id_token", expired)
    body = draft_without_label(monkeypatch, CLOUD_RUN)
    assert body["status"] == "error" and body["error_type"] == "classifier_unavailable"
    assert server == []  # nothing sent without a token


def test_a_partial_answer_is_not_used(monkeypatch):
    monkeypatch.setattr(classifier_client.httpx, "post", lambda url, **kwargs: httpx.Response(
        200, json={"detail": "odd"}, request=httpx.Request("POST", url)))
    body = draft_without_label(monkeypatch, "http://localhost:8002")
    assert body["status"] == "error" and body["error_type"] == "classifier_unavailable"
