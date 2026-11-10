"""Calling the classifier locally (no auth) and on Cloud Run (ID token). No network."""

import base64
import json
import time

import httpx
import pytest

import classifier_client
from classifier_client import ClassifierClient, ClassifierError, IdTokenSource

ANSWER = {"label": "proposed_times", "needs_response": True, "reason": "D2.", "model": "m", "rules_version": "1.5",
          "latency_ms": 5}


class FakePost:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error = status, body or ANSWER, error
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.body)


def jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_local_classifier_gets_no_token():
    post = FakePost()
    client = ClassifierClient("http://localhost:8002", post=post)
    assert client.classify([{"from": "a", "body": "b"}], 0, "m1") == ANSWER
    assert post.calls[0]["url"] == "http://localhost:8002/classify"
    assert post.calls[0]["headers"] == {}
    assert post.calls[0]["json"] == {"thread": [{"from": "a", "body": "b"}], "target_index": 0, "message_id": "m1"}


def test_cloud_run_classifier_gets_an_id_token(monkeypatch):
    fetches = []
    token = jwt(time.time() + 3600)
    monkeypatch.setattr(IdTokenSource, "_fetch", lambda self: fetches.append(self.audience) or token)
    post = FakePost()
    client = ClassifierClient("https://fixture-classifier-123.us-east1.run.app/", post=post)
    client.classify([{}], 0)
    client.classify([{}], 0)
    assert post.calls[0]["headers"] == {"Authorization": f"Bearer {token}"}
    assert fetches == ["https://fixture-classifier-123.us-east1.run.app"]  # fetched once, then reused


def test_expiring_token_is_refreshed(monkeypatch):
    tokens = iter([jwt(time.time() + 60), jwt(time.time() + 3600)])
    monkeypatch.setattr(IdTokenSource, "_fetch", lambda self: next(tokens))
    source = IdTokenSource("https://x.run.app")
    first = source.token()
    assert source.token() != first  # under 5 minutes left: fetched again


def test_auth_can_be_forced_or_turned_off():
    assert ClassifierClient("http://classifier:8002", auth="id_token").tokens is not None
    assert ClassifierClient("https://x.run.app", auth="none").tokens is None


@pytest.mark.parametrize("post, message", [
    (FakePost(error=httpx.ConnectError("refused")), "unreachable"),
    (FakePost(status=503), "returned 503"),
    (FakePost(body={"detail": "x"}), "missing its label"),
])
def test_failures_raise_classifier_error(post, message):
    with pytest.raises(ClassifierError, match=message):
        ClassifierClient("http://localhost:8002", post=post).classify([{}], 0)


def test_token_failure_is_a_classifier_error(monkeypatch):
    def broken(self):
        raise RuntimeError("no credentials")
    monkeypatch.setattr(IdTokenSource, "_fetch", broken)
    with pytest.raises(ClassifierError, match="identity token"):
        ClassifierClient("https://x.run.app", post=FakePost()).classify([{}], 0)


def test_from_env(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_URL", "https://y.run.app")
    monkeypatch.setenv("CLASSIFIER_AUTH", "auto")
    assert classifier_client.from_env().tokens is not None
