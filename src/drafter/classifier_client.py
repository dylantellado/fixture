"""Call the classifier (src/classifier) when a request comes without a classification.

CLASSIFIER_URL picks which one:
  http://localhost:8002                                   local (no auth)
  http://classifier:8002                                  Docker Compose (no auth)
  https://fixture-classifier-...-uc.a.run.app             Cloud Run (needs an ID token)

For an https URL the request carries a Google identity token for that URL
(CLASSIFIER_AUTH=auto, the default; "id_token" forces it, "none" turns it off):
  1. On Cloud Run (or with a service-account key) google-auth fetches one from
     the metadata server for the classifier's URL. The drafter's service
     account then needs roles/run.invoker on the classifier.
  2. Locally, with `gcloud auth application-default login` user credentials,
     that isn't possible, so the token from refreshing those credentials is
     used (the same kind `gcloud auth print-identity-token` prints). Cloud Run
     accepts it if the person has roles/run.invoker.
Tokens are reused until five minutes before they expire.

Email text goes out in the request body only and is never logged here.
"""

import base64
import json
import os
import threading
import time

import httpx

CLASSIFY_TIMEOUT = 60  # the classifier retries Gemini on rate limits, so a call can take a while
REFRESH_MARGIN_S = 300


class ClassifierError(Exception):
    """The classifier couldn't be reached, refused the request, or couldn't classify. Message is safe to log."""


def _expiry(token: str) -> float:
    """The exp claim of a JWT (not verified: it's our own token, used only for caching)."""
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except (IndexError, KeyError, ValueError):
        return time.time() + 600  # unknown: reuse for 10 minutes


class IdTokenSource:
    def __init__(self, audience: str):
        self.audience = audience
        self._token, self._expires = "", 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> str:
        # Imported here so tests and local http use never need google-auth's transport.
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        try:
            return id_token.fetch_id_token(Request(), self.audience)  # Cloud Run, or a service-account key
        except DefaultCredentialsError:
            pass  # user credentials from gcloud: use the ID token that comes with a refresh
        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        token = getattr(credentials, "id_token", None)
        if not token:
            raise ClassifierError("no Google identity token available for the classifier")
        return token

    def token(self) -> str:
        with self._lock:
            if not self._token or time.time() > self._expires - REFRESH_MARGIN_S:
                try:
                    self._token = self._fetch()
                except ClassifierError:
                    raise
                except Exception as error:
                    raise ClassifierError(f"couldn't get an identity token ({type(error).__name__})") from error
                self._expires = _expiry(self._token)
            return self._token


class ClassifierClient:
    def __init__(self, url: str, auth: str = "auto", post=httpx.post):
        self.url = url.rstrip("/")
        use_token = auth == "id_token" or (auth == "auto" and self.url.startswith("https://"))
        self.tokens = IdTokenSource(self.url) if use_token else None
        self._post = post  # tests pass a fake

    def classify(self, thread: list[dict], target_index: int, message_id: str = "") -> dict:
        """POST /classify. Returns {label, needs_response, reason, model, rules_version, latency_ms}."""
        headers = {"Authorization": f"Bearer {self.tokens.token()}"} if self.tokens else {}
        body = {"thread": thread, "target_index": target_index, "message_id": message_id}
        try:
            response = self._post(f"{self.url}/classify", json=body, headers=headers, timeout=CLASSIFY_TIMEOUT)
        except httpx.HTTPError as error:
            raise ClassifierError(f"classifier unreachable ({type(error).__name__})") from error
        if response.status_code != 200:
            raise ClassifierError(f"classifier returned {response.status_code}")
        answer = response.json()
        if not isinstance(answer.get("needs_response"), bool) or not answer.get("label"):
            raise ClassifierError("classifier answer is missing its label")
        return answer


def from_env() -> ClassifierClient:
    return ClassifierClient(os.environ.get("CLASSIFIER_URL", "http://localhost:8002"),
                            os.environ.get("CLASSIFIER_AUTH", "auto"))
