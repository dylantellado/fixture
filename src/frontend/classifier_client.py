"""Calls to the Fixture classifier (src/classifier), which labels emails with Gemini.

All HTTP calls to the classifier live here, so tests can replace these
functions with fakes. Email text goes out in the request body only; it is
never logged here.
"""

import os

import httpx

# Where the classifier runs. Docker sets CLASSIFIER_URL=http://classifier:8002.
CLASSIFIER_URL = os.environ.get("CLASSIFIER_URL", "http://localhost:8002")

HEALTH_TIMEOUT = 3
# The classifier retries Gemini on rate limits, so one call can take a while.
CLASSIFY_TIMEOUT = 60


class ClassifierUnavailable(Exception):
    """The classifier couldn't be reached, or couldn't classify (e.g. Gemini is down)."""


def health() -> dict:
    """GET /health: {"status", "model", "rules_version"}. Raises ClassifierUnavailable."""
    try:
        response = httpx.get(f"{CLASSIFIER_URL}/health", timeout=HEALTH_TIMEOUT)
        response.raise_for_status()
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
    body = {"thread": thread, "target_index": target_index, "message_id": message_id}
    try:
        response = httpx.post(f"{CLASSIFIER_URL}/classify", json=body, timeout=CLASSIFY_TIMEOUT)
    except httpx.HTTPError as e:
        raise ClassifierUnavailable(type(e).__name__) from e
    if response.status_code != 200:
        raise ClassifierUnavailable(f"classifier returned {response.status_code}")
    return response.json()
