"""Calls to the Fixture classifier (src/classifier), which labels emails with Gemini.

KEEP IN SYNC: src/frontend/classifier_client.py and src/drafter/classifier_client.py
are identical copies, because services don't import from each other. The web app
uses it to label the dashboard's emails; the drafter uses it when a draft request
comes without a label. Change both together; a test in each service fails if
they differ.

All HTTP calls to the classifier live here, so tests can replace these
functions with fakes. Email text goes out in the request body only; it is
never logged here.

Where the classifier runs is CLASSIFIER_URL:
  http://localhost:8002 (default)   local `uv run uvicorn`, no token
  http://classifier:8002            Docker Compose's classifier, no token
  https://...run.app                the deployed service on Cloud Run, which
                                    requires a Google ID token on every request

For an https URL we get the ID token from the Google credentials of whoever
runs the service (application-default credentials: your gcloud login locally,
the mounted ~/.config/gcloud in Docker, its service account on Cloud Run). That
account needs roles/run.invoker on the classifier (project owners have it).
"""

import logging
import os
import threading
import time

import google.auth
import google.auth.jwt
import google.oauth2.credentials
import google.oauth2.id_token
import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest

log = logging.getLogger("fixture.classifier")

DEFAULT_URL = "http://localhost:8002"

HEALTH_TIMEOUT = 3
# The classifier retries Gemini on rate limits, so one call can take a while.
CLASSIFY_TIMEOUT = 60
# Get a new ID token this many seconds before the current one expires (they last an hour).
TOKEN_REFRESH_MARGIN = 300


class ClassifierUnavailable(Exception):
    """The classifier couldn't be reached, or couldn't classify (e.g. Gemini is down)."""


def classifier_url() -> str:
    """CLASSIFIER_URL without a trailing slash.

    Read on every call, not at import: main.py imports this module before it
    loads .env, so a module-level constant would miss a value set there.
    """
    return os.environ.get("CLASSIFIER_URL", DEFAULT_URL).rstrip("/")


def health() -> dict:
    """GET /health: {"status", "model", "rules_version"}. Raises ClassifierUnavailable."""
    url = classifier_url()
    try:
        response = httpx.get(f"{url}/health", headers=_auth_headers(url), timeout=HEALTH_TIMEOUT)
        if response.status_code != 200:
            raise ClassifierUnavailable(f"classifier returned {response.status_code}")
        info = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ClassifierUnavailable(type(e).__name__) from e
    if info.get("status") != "ok" or not info.get("rules_version"):
        raise ClassifierUnavailable("unexpected /health answer")
    return info


def classify(thread: list[dict], target_index: int, message_id: str = "") -> dict:
    """POST /classify: label thread[target_index].

    Returns {label, needs_response, reason, model, rules_version, latency_ms}.
    Raises ClassifierUnavailable on any failure; the classifier never guesses.
    """
    url = classifier_url()
    body = {"thread": thread, "target_index": target_index, "message_id": message_id}
    try:
        response = httpx.post(f"{url}/classify", json=body, headers=_auth_headers(url), timeout=CLASSIFY_TIMEOUT)
    except httpx.HTTPError as e:
        raise ClassifierUnavailable(type(e).__name__) from e
    if response.status_code != 200:
        raise ClassifierUnavailable(f"classifier returned {response.status_code}")
    return response.json()


# --- ID tokens for the classifier on Cloud Run ------------------------------------

# One cached token, shared by the dashboard's parallel classify calls.
_token: dict = {"audience": None, "value": None, "expires_at": 0.0}
_token_lock = threading.Lock()


def _auth_headers(url: str) -> dict:
    """{"Authorization": "Bearer <ID token>"} for an https URL, {} for http (local, Docker).

    Raises ClassifierUnavailable if no token can be had (no credentials, expired login, offline).
    """
    if not url.startswith("https://"):
        return {}
    return {"Authorization": f"Bearer {id_token(url)}"}


def id_token(audience: str) -> str:
    """A Google ID token for calling `audience`, cached until TOKEN_REFRESH_MARGIN before it expires."""
    with _token_lock:  # one refresh at a time; the other threads then reuse its token
        if (_token["audience"] == audience and _token["value"]
                and time.time() < _token["expires_at"] - TOKEN_REFRESH_MARGIN):
            return _token["value"]
        try:
            value = _fetch_id_token(audience)
            # The token's own expiry ("exp", seconds since 1970). It came straight from
            # Google over https, so we only read it here; Cloud Run checks the signature.
            expires_at = float(google.auth.jwt.decode(value, verify=False)["exp"])
        except (GoogleAuthError, ValueError, KeyError) as e:
            # The type only: auth errors can carry account details.
            log.warning("no ID token for the classifier (%s); run `gcloud auth application-default login`",
                        type(e).__name__)
            raise ClassifierUnavailable(f"no ID token ({type(e).__name__})") from e
        _token.update(audience=audience, value=value, expires_at=expires_at)
        return value


def _fetch_id_token(audience: str) -> str:
    """Get a fresh ID token from the application-default credentials. Makes a network call."""
    credentials, _ = google.auth.default()
    if isinstance(credentials, google.oauth2.credentials.Credentials):
        # A person's gcloud login (`gcloud auth application-default login`). Google can't
        # mint a token for a chosen audience for a user, so we refresh the login and use
        # the ID token Google sends back. Its audience is gcloud's own client id, which
        # Cloud Run accepts from users with roles/run.invoker (it's what
        # `gcloud auth print-identity-token` prints).
        credentials.refresh(GoogleRequest())
        if not credentials.id_token:
            raise ValueError("this login has no ID token")
        return credentials.id_token
    # A service account (e.g. if the web app itself ran on Cloud Run): ask for a
    # token whose audience is the classifier's URL.
    return google.oauth2.id_token.fetch_id_token(GoogleRequest(), audience)
