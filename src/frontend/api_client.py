"""Calls to the Fixture API (src/api), and formatting its results for the search page.

All HTTP calls to the API live here, so main.py never deals with httpx and
tests can replace these functions with fakes.
"""

import os
import re
from datetime import datetime

import httpx

# Where the API runs. Docker sets API_URL=http://api:8000.
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Seconds to wait for the API. Search gets longer: the API embeds the query,
# and its very first search also loads the embedding model.
USERS_TIMEOUT = 5
SEARCH_TIMEOUT = 30

# The six labels from the Data contract, with readable names for the page.
LABELS = {
    "new_request": "New request",
    "proposed_times": "Proposed times",
    "acceptance": "Acceptance",
    "reschedule": "Reschedule",
    "assistant_handoff": "Assistant handoff",
    "none": "Not scheduling",
}


class ApiUnavailable(Exception):
    """The API (or the database behind it) couldn't be reached."""


class UnknownUser(Exception):
    """The API doesn't know this user_id (400)."""


class ApiError(Exception):
    """Any other error response from the API."""


def _request(method: str, path: str, timeout: float, **kwargs) -> httpx.Response:
    """Send one request to the API, turning failures into the exceptions above."""
    try:
        response = httpx.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except httpx.HTTPError as e:  # couldn't connect, timed out, ...
        raise ApiUnavailable(str(e)) from e
    if response.status_code == 400:
        raise UnknownUser()
    if response.status_code >= 500:  # e.g. 503 when ChromaDB is down
        raise ApiUnavailable(f"API returned {response.status_code}")
    if response.status_code != 200:
        raise ApiError(f"API returned {response.status_code}")
    return response


def list_users() -> list[dict]:
    """GET /users: the demo users that have indexed messages."""
    return _request("GET", "/users", USERS_TIMEOUT).json()


def search(user_id: str, query: str, k: int = 5, label: str | None = None) -> list[dict]:
    """POST /search: the k best-matching messages for one user, best first."""
    body = {"user_id": user_id, "query": query, "k": k}
    if label:
        body["label"] = label
    return _request("POST", "/search", SEARCH_TIMEOUT, json=body).json()["results"]


def is_healthy() -> bool:
    """GET /health: is the API up? (It doesn't check ChromaDB; list_users does.)"""
    try:
        return _request("GET", "/health", USERS_TIMEOUT).json().get("status") == "ok"
    except (ApiUnavailable, ApiError, UnknownUser):
        return False


# --- Formatting for the page ---

# rag puts a small header ("From: ...", "Subject: ...", "Date: ...") at the
# top of each chunk's text. The page shows those fields separately, so the
# snippet skips them.
HEADER_LINE = re.compile(r"^(From|To|Subject|Date):.*$")
SNIPPET_LENGTH = 280


def message_body(text: str) -> str:
    """The message text without rag's header lines, keeping its line breaks."""
    lines = text.strip().splitlines()
    while lines and (HEADER_LINE.match(lines[0]) or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def snippet(text: str) -> str:
    """The message body on one line, cut to SNIPPET_LENGTH characters."""
    body = " ".join(line.strip() for line in message_body(text).splitlines() if line.strip())
    if len(body) > SNIPPET_LENGTH:
        body = body[:SNIPPET_LENGTH].rsplit(" ", 1)[0] + "…"
    return body


def sender_label(metadata: dict) -> str:
    """The sender's display name, or their placeholder (e.g. EMAIL_003) if they have none."""
    if metadata.get("sender_name"):
        return metadata["sender_name"]
    sender = metadata.get("sender", "")
    match = re.search(r"<([^>]+)>", sender)  # "Jordan Lee <EMAIL_003>" -> EMAIL_003
    return match.group(1) if match else (sender or "Unknown sender")


def readable_date(timestamp: str) -> str:
    """'2026-10-13T09:12:00-04:00' -> 'Tue, Oct 13, 2026 · 9:12 AM', in the message's own time zone."""
    try:
        when = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp  # show it as-is rather than fail
    return f"{when:%a}, {when:%b} {when.day}, {when.year} · {when.hour % 12 or 12}:{when:%M} {when:%p}"


def format_result(result: dict) -> dict:
    """Turn one API search result into the fields the search page shows."""
    metadata = result.get("metadata", {})
    label = metadata.get("label", "")
    text = result.get("text", "")
    score = result["score"]
    return {
        "sender": sender_label(metadata),
        "date": readable_date(metadata.get("timestamp", "")),
        "subject": metadata.get("subject") or "(no subject)",
        "label": LABELS.get(label, label),
        "label_key": label if label in LABELS else "none",  # picks the label's color
        "score": f"{score:.3f}",  # same 3 places the API rounds to
        "strength": round(max(0.0, min(1.0, score)) * 100),  # width of the match bar, in %
        "snippet": snippet(text),
        "body": message_body(text),  # shown under "Show full text"
        # Where the result came from, so every answer can be traced to one email.
        "message_id": metadata.get("message_id", ""),
        "thread_id": metadata.get("thread_id", ""),
        "chunk_index": metadata.get("chunk_index", 0),  # > 0: a later part of a long message
    }


def format_user(user: dict) -> dict:
    """Add a readable 'indexed' time to a user from GET /users.

    rag records indexed_at in UTC, so the time is labeled UTC.
    """
    indexed_at = user.get("indexed_at", "")
    return {**user, "indexed": f"{readable_date(indexed_at)} UTC" if indexed_at else ""}
