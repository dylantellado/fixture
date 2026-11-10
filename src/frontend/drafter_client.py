"""Calls to the Fixture drafter (src/drafter), which drafts a reply to one email.

All HTTP calls to the drafter live here, so tests can replace them with fakes.
Email text goes out in the request body only; it is never logged here.
"""

import os

import httpx

# Where the drafter runs. Docker sets DRAFTER_URL=http://drafter:8003.
DRAFTER_URL = os.environ.get("DRAFTER_URL", "http://localhost:8003")

# Gemini, maybe a retry, and maybe a classifier call: allow up to two minutes.
DRAFT_TIMEOUT = 120


class DrafterUnavailable(Exception):
    """The drafter couldn't be reached or answered with an HTTP error."""


def draft(payload: dict) -> dict:
    """POST /draft. Returns the drafter's response (it has a "status"). Raises DrafterUnavailable."""
    try:
        response = httpx.post(f"{DRAFTER_URL}/draft", json=payload, timeout=DRAFT_TIMEOUT)
    except httpx.HTTPError as e:
        raise DrafterUnavailable(type(e).__name__) from e
    if response.status_code != 200:
        raise DrafterUnavailable(f"drafter returned {response.status_code}")
    try:
        return response.json()
    except ValueError as e:
        raise DrafterUnavailable("drafter answer is not JSON") from e
