"""Tests for classifier_client: which URLs get a Google ID token, how the token is
cached and refreshed, and the keyword fallback when there is no token.

Nothing here touches the network: httpx and Google's auth library are faked,
and the tokens are made-up JWTs with no real signature.
"""

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import google.auth
import google.oauth2.credentials
import google.oauth2.id_token
import httpx
import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError, TransportError

import classifier_client
import live_labels
from classification_cache import ClassificationCache

CLOUD_RUN = "https://fixture-classifier-test.us-east1.run.app"
HEALTH = {"status": "ok", "model": "gemini-test", "rules_version": "1.5"}
LABEL = {"label": "new_request", "needs_response": True, "reason": "D1.", "model": "gemini-test",
         "rules_version": "1.5", "latency_ms": 5}
THREAD = [{"from": "jordan@example.com", "date": "Tue, 13 Oct 2026", "subject": "Coffee?", "body": "Free Tuesday?"}]


def fake_jwt(expires_at: float, name: str = "token") -> str:
    """A JWT-shaped string with an "exp" claim (unsigned: only our code reads it)."""
    def part(data) -> str:
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return ".".join([part({"alg": "RS256", "typ": "JWT"}), part({"exp": int(expires_at), "sub": name}),
                     part(b"not-a-signature")])


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Every test starts with no cached token, and can't reach Google or the classifier."""
    monkeypatch.setattr(classifier_client, "_token", {"audience": None, "value": None, "expires_at": 0.0})
    monkeypatch.setattr(google.auth, "default", _forbidden("google.auth.default"))
    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token", _forbidden("fetch_id_token"))


def _forbidden(name):
    def fake(*args, **kwargs):
        raise AssertionError(f"{name} must be faked in this test")
    return fake


@pytest.fixture
def server(monkeypatch):
    """Fake classifier: records each request's URL and headers. Set server.status to fail."""
    server = SimpleNamespace(requests=[], status=200)

    def respond(method, url, headers, payload):
        server.requests.append({"method": method, "url": url, "headers": dict(headers or {})})
        body = payload if server.status == 200 else {"detail": "denied"}
        return httpx.Response(server.status, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: respond("GET", url, headers, HEALTH))
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None: respond("POST", url, headers, LABEL))
    return server


@pytest.fixture
def tokens(monkeypatch):
    """Fake token source: each fetch returns a new token valid for an hour. Records audiences."""
    fetched = []

    def fetch(audience):
        fetched.append(audience)
        return fake_jwt(time.time() + 3600, name=f"token-{len(fetched)}")

    monkeypatch.setattr(classifier_client, "_fetch_id_token", fetch)
    return fetched


# --- Which URLs get a token ---------------------------------------------------------


@pytest.mark.parametrize("url", ["http://localhost:8002", "http://classifier:8002"])
def test_http_urls_get_no_token(monkeypatch, server, url):
    monkeypatch.setenv("CLASSIFIER_URL", url)
    monkeypatch.setattr(classifier_client, "_fetch_id_token", _forbidden("_fetch_id_token"))
    assert classifier_client.health() == HEALTH
    assert classifier_client.classify(THREAD, 0, message_id="m1") == LABEL
    assert [r["url"] for r in server.requests] == [f"{url}/health", f"{url}/classify"]
    assert all("Authorization" not in r["headers"] for r in server.requests)


def test_default_url_is_local(monkeypatch, server):
    monkeypatch.delenv("CLASSIFIER_URL", raising=False)
    classifier_client.health()
    assert server.requests[0]["url"] == "http://localhost:8002/health"
    assert "Authorization" not in server.requests[0]["headers"]


def test_https_url_gets_a_token_on_every_request(monkeypatch, server, tokens):
    monkeypatch.setenv("CLASSIFIER_URL", CLOUD_RUN + "/")  # a trailing slash is dropped
    assert classifier_client.health() == HEALTH
    assert classifier_client.classify(THREAD, 0) == LABEL
    assert [r["url"] for r in server.requests] == [f"{CLOUD_RUN}/health", f"{CLOUD_RUN}/classify"]
    token = server.requests[0]["headers"]["Authorization"]
    assert token.startswith("Bearer ") and server.requests[1]["headers"]["Authorization"] == token
    assert tokens == [CLOUD_RUN]  # one token for both requests; audience = the service URL


def test_cloud_run_rejection_is_unavailable(monkeypatch, server, tokens):
    """No roles/run.invoker: Cloud Run answers 403 before the request reaches the classifier."""
    monkeypatch.setenv("CLASSIFIER_URL", CLOUD_RUN)
    server.status = 403
    with pytest.raises(classifier_client.ClassifierUnavailable, match="returned 403"):
        classifier_client.health()
    with pytest.raises(classifier_client.ClassifierUnavailable, match="returned 403"):
        classifier_client.classify(THREAD, 0)


# --- Caching and refreshing the token --------------------------------------------------


def test_token_is_reused_until_shortly_before_it_expires(monkeypatch, tokens):
    clock = SimpleNamespace(now=1_000_000.0)
    monkeypatch.setattr(classifier_client, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(classifier_client, "_fetch_id_token",
                        lambda audience: tokens.append(audience) or fake_jwt(clock.now + 3600, f"token-{len(tokens)}"))

    first = classifier_client.id_token(CLOUD_RUN)
    clock.now += 3600 - classifier_client.TOKEN_REFRESH_MARGIN - 1  # just inside the margin: still reused
    assert classifier_client.id_token(CLOUD_RUN) == first and len(tokens) == 1
    clock.now += 2  # within the margin of expiry: get a new one
    second = classifier_client.id_token(CLOUD_RUN)
    assert second != first and len(tokens) == 2
    assert classifier_client.id_token(CLOUD_RUN) == second and len(tokens) == 2


def test_another_url_gets_its_own_token(tokens):
    first = classifier_client.id_token(CLOUD_RUN)
    other = classifier_client.id_token("https://other-service.run.app")
    assert other != first and tokens == [CLOUD_RUN, "https://other-service.run.app"]


def test_parallel_requests_share_one_token_fetch(monkeypatch, tokens):
    """The dashboard classifies several emails at once; they must not all refresh the login."""
    fetch = classifier_client._fetch_id_token

    def slow_fetch(audience):
        time.sleep(0.05)
        return fetch(audience)

    monkeypatch.setattr(classifier_client, "_fetch_id_token", slow_fetch)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: classifier_client.id_token(CLOUD_RUN), range(5)))
    assert len(set(results)) == 1 and len(tokens) == 1


def test_a_failed_fetch_is_not_cached(monkeypatch):
    answers = [RefreshError("offline"), fake_jwt(time.time() + 3600)]

    def fetch(audience):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(classifier_client, "_fetch_id_token", fetch)
    with pytest.raises(classifier_client.ClassifierUnavailable):
        classifier_client.id_token(CLOUD_RUN)
    assert classifier_client.id_token(CLOUD_RUN)  # the next call tries again


# --- Where the token comes from ----------------------------------------------------


class FakeUserLogin(google.oauth2.credentials.Credentials):
    """A gcloud user login (application-default credentials). Refreshing sets an ID token."""

    def __init__(self, id_token):
        super().__init__(token=None, refresh_token="fake-refresh")
        self.new_id_token = id_token
        self.refreshes = 0

    def refresh(self, request):
        self.refreshes += 1
        self._id_token = self.new_id_token


def test_user_login_uses_the_id_token_from_a_refresh(monkeypatch):
    login = FakeUserLogin(fake_jwt(time.time() + 3600, "user"))
    monkeypatch.setattr(google.auth, "default", lambda: (login, "fake-project"))
    assert classifier_client._fetch_id_token(CLOUD_RUN) == login.new_id_token
    assert login.refreshes == 1


def test_service_account_asks_for_the_service_url_as_audience(monkeypatch):
    audiences = []
    monkeypatch.setattr(google.auth, "default", lambda: (object(), "fake-project"))
    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token",
                        lambda request, audience: audiences.append(audience) or "service-account-token")
    assert classifier_client._fetch_id_token(CLOUD_RUN) == "service-account-token"
    assert audiences == [CLOUD_RUN]


def test_login_without_an_id_token_is_unavailable(monkeypatch, server):
    monkeypatch.setenv("CLASSIFIER_URL", CLOUD_RUN)
    monkeypatch.setattr(google.auth, "default", lambda: (FakeUserLogin(None), "fake-project"))
    with pytest.raises(classifier_client.ClassifierUnavailable, match="ValueError"):
        classifier_client.health()
    assert server.requests == []  # never sent without a token


# --- Fallback when there's no token ----------------------------------------------------


@pytest.mark.parametrize("error", [
    DefaultCredentialsError("no credentials for sam@example.edu"),  # never ran gcloud auth application-default login
    RefreshError("invalid_grant for sam@example.edu"),  # the login expired or was revoked
    TransportError("can't reach oauth2.googleapis.com"),  # offline
])
def test_auth_failure_falls_back_to_keywords_and_logs_only_the_error_type(monkeypatch, server, tmp_path, caplog,
                                                                          error):
    monkeypatch.setenv("CLASSIFIER_URL", CLOUD_RUN)
    monkeypatch.setattr(google.auth, "default", lambda: (_ for _ in ()).throw(error))
    emails = [{"id": "m1", "thread_id": "t1", "scheduling_match": "meeting"},
              {"id": "m2", "thread_id": "t2", "scheduling_match": None}]

    summary = live_labels.label_emails("creds", emails, ClassificationCache(tmp_path / "fixture.db"), "sam@example.edu")

    assert summary["mode"] == "fallback"  # the dashboard shows its "isn't reachable" notice
    assert [e["ai"]["state"] for e in emails] == ["off", "off"]
    assert [e["is_scheduling"] for e in emails] == [True, False]  # keyword tags
    assert server.requests == []
    assert type(error).__name__ in caplog.text
    assert "sam@example.edu" not in caplog.text  # the error's details aren't logged


def test_auth_failure_during_classify_raises_unavailable(monkeypatch, server):
    monkeypatch.setenv("CLASSIFIER_URL", CLOUD_RUN)
    monkeypatch.setattr(classifier_client, "_fetch_id_token", lambda audience: (_ for _ in ()).throw(RefreshError()))
    with pytest.raises(classifier_client.ClassifierUnavailable, match="RefreshError"):
        classifier_client.classify(THREAD, 0)
    assert server.requests == []
