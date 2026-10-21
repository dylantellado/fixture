"""Tests for the /search page and api_client.py. The API is never called:
each test replaces api_client's functions with fakes."""

import json
import os
import socket
from base64 import b64encode

import pytest
from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials
from itsdangerous import TimestampSigner
from markupsafe import escape

import api_client
import google_data
import main

client = TestClient(main.app)

USERS = [
    {"user_id": "user_01", "name": "Priya Shah", "indexed_at": "2026-10-20T01:20:48+00:00"},
    {"user_id": "user_02", "name": "Marcus Bell", "indexed_at": "2026-10-20T01:20:48+00:00"},
]

RESULT = {
    "text": "From: Jordan Lee\nSubject: Re: Northbridge Capital first-round interview\n"
            "Date: 2026-10-13T15:05:00-04:00\n\nGreat, let's do Tuesday, October 20 at 2:30 pm Eastern.",
    "score": 0.797,
    "metadata": {
        "message_id": "0ed574b41b112de0",
        "user_id": "user_01",
        "sender": "Jordan Lee <EMAIL_003>",
        "sender_name": "Jordan Lee",
        "timestamp": "2026-10-13T15:05:00-04:00",
        "subject": "Re: Northbridge Capital first-round interview",
        "label": "acceptance",
    },
}


def shown(page_text: str, message: str) -> bool:
    """Is this message on the page? (The page HTML-escapes it, e.g. ' becomes &#39;.)"""
    return str(escape(message)) in page_text


def raise_(error):
    """A fake API function that always fails with this error."""
    def fake(*args, **kwargs):
        raise error
    return fake


@pytest.fixture
def api(monkeypatch):
    """A fake API with two users. Records every search it's asked to run."""
    searches = []

    def fake_search(user_id, query, k=5, label=None):
        searches.append({"user_id": user_id, "query": query, "k": k, "label": label})
        return [RESULT]

    monkeypatch.setattr(api_client, "list_users", lambda: USERS)
    monkeypatch.setattr(api_client, "search", fake_search)
    return searches


# --- The page ----------------------------------------------------------------


def test_page_renders_without_sign_in(api):
    response = client.get("/search")
    assert response.status_code == 200
    assert "Search past threads" in response.text
    assert "Demo data" in response.text
    # The picker is filled from GET /users.
    assert "Priya Shah" in response.text and "Marcus Bell" in response.text
    assert api == []  # no query yet, so no search


def test_results_render(api):
    response = client.get("/search", params={"user_id": "user_01", "q": "Northbridge interview"})

    assert response.status_code == 200
    page = response.text
    assert "Jordan Lee" in page
    assert "Tue, Oct 13, 2026 · 3:05 PM" in page
    assert "Re: Northbridge Capital first-round interview" in page
    assert "Acceptance" in page
    assert "0.797" in page
    assert "Great, let&#39;s do Tuesday" in page  # snippet, HTML-escaped
    assert "Show full text" in page
    assert "0ed574b41b112de0" in page  # each result shows the message it came from
    assert api == [{"user_id": "user_01", "query": "Northbridge interview", "k": 5, "label": None}]


def test_label_filter_is_sent_and_unknown_labels_are_ignored(api):
    client.get("/search", params={"user_id": "user_02", "q": "move", "label": "reschedule"})
    client.get("/search", params={"user_id": "user_02", "q": "move", "label": "bogus"})
    assert [s["label"] for s in api] == ["reschedule", None]


def test_first_user_is_the_default(api):
    client.get("/search", params={"q": "interview"})
    assert api[0]["user_id"] == "user_01"


def test_blank_query_does_not_search(api):
    client.get("/search", params={"user_id": "user_01", "q": "   "})
    assert api == []


def test_no_results_message(api, monkeypatch):
    monkeypatch.setattr(api_client, "search", lambda *a, **kw: [])
    response = client.get("/search", params={"user_id": "user_01", "q": "dentist"})
    assert "No messages matched “dentist”" in response.text


# --- Friendly errors -------------------------------------------------------------


def test_api_down_message(monkeypatch):
    monkeypatch.setattr(api_client, "list_users", raise_(api_client.ApiUnavailable("refused")))
    response = client.get("/search", params={"q": "interview"})
    assert response.status_code == 200
    assert shown(response.text, main.SEARCH_ERRORS["api_down"])
    assert "Traceback" not in response.text


def test_api_down_during_search(api, monkeypatch):
    monkeypatch.setattr(api_client, "search", raise_(api_client.ApiUnavailable("503")))
    response = client.get("/search", params={"user_id": "user_01", "q": "interview"})
    assert shown(response.text, main.SEARCH_ERRORS["api_down"])


def test_no_indexed_users_message(monkeypatch):
    monkeypatch.setattr(api_client, "list_users", lambda: [])
    response = client.get("/search")
    assert shown(response.text, main.SEARCH_ERRORS["no_users"])


def test_unknown_user_message(api, monkeypatch):
    monkeypatch.setattr(api_client, "search", raise_(api_client.UnknownUser()))
    response = client.get("/search", params={"user_id": "user_99", "q": "interview"})
    assert shown(response.text, main.SEARCH_ERRORS["unknown_user"])
    # The picker asks for a mailbox instead of pretending user_99 is the first user.
    assert '<option value="" selected disabled>Choose a mailbox</option>' in response.text


def test_known_user_has_no_placeholder(api):
    response = client.get("/search", params={"user_id": "user_02", "q": "interview"})
    assert "Choose a mailbox" not in response.text
    assert '<option value="user_02" selected>' in response.text


# --- Links to the page ------------------------------------------------------------


def test_sign_in_page_links_to_search():
    response = client.get("/")  # not signed in, so this is the sign-in page
    assert "Sign in with Google" in response.text
    assert 'href="/search"' in response.text


def test_dashboard_and_top_bar_when_signed_in(monkeypatch, api):
    """The signed-in dashboard still renders, and the shared top bar shows the
    account on every page. Google is never called: the user's data is faked."""
    email = "test.user@example.com"
    main.store.save(email, Credentials(token="fake"), name="Test User")  # temporary test database
    monkeypatch.setattr(main, "current_credentials", lambda request: "fake-credentials")
    monkeypatch.setattr(google_data, "fetch_events", lambda creds: {"items": [], "calendars": [], "skipped": []})
    monkeypatch.setattr(google_data, "fetch_emails", lambda creds: [])

    # Sign in by sending the same signed session cookie the app would set.
    signed_in = TestClient(main.app)
    session = b64encode(json.dumps({"email": email}).encode())
    signed_in.cookies.set("session", TimestampSigner(os.environ["SESSION_SECRET"]).sign(session).decode())

    response = signed_in.get("/")
    assert "Welcome, Test." in response.text
    assert 'href="/search"' in response.text
    assert 'href="/" aria-current="page">Dashboard' in response.text

    response = signed_in.get("/search")
    assert email in response.text and "Sign out" in response.text
    assert 'href="/search" aria-current="page">Search' in response.text


def test_signed_out_top_bar(api):
    response = client.get("/search")
    assert 'href="/search" aria-current="page">Search' in response.text
    assert ">Dashboard<" not in response.text  # only for signed-in users
    assert ">Sign in<" in response.text


def test_result_count_is_sent_and_limited(api):
    client.get("/search", params={"user_id": "user_01", "q": "x", "k": "10"})
    client.get("/search", params={"user_id": "user_01", "q": "x", "k": "7"})  # not offered
    client.get("/search", params={"user_id": "user_01", "q": "x", "k": "abc"})  # not a number
    assert [s["k"] for s in api] == [10, 5, 5]


def test_example_questions_follow_the_mailbox(api, monkeypatch):
    response = client.get("/search", params={"user_id": "user_02"})
    assert "When does Professor Osei meet?" in response.text
    # Each example is a link that runs that search in the same mailbox.
    assert 'href="/search?user_id=user_02&amp;q=When+does+Professor+Osei+meet%3F&amp;k=5"' in response.text

    # A mailbox without its own examples gets the general ones.
    monkeypatch.setattr(api_client, "list_users", lambda: [{"user_id": "user_09", "name": "New", "indexed_at": ""}])
    response = client.get("/search")
    assert main.GENERAL_QUESTIONS[0] in response.text


def test_mailbox_shows_when_it_was_indexed(api):
    response = client.get("/search", params={"user_id": "user_01"})
    assert "Indexed Tue, Oct 20, 2026 · 1:20 AM UTC" in response.text


def test_guide_shows_before_the_first_search(api):
    assert "How to search" in client.get("/search").text
    assert "How to search" not in client.get("/search", params={"q": "interview"}).text


# --- How it works ------------------------------------------------------------------


def test_about_page_shows_status_and_mailboxes(api, monkeypatch):
    monkeypatch.setattr(api_client, "is_healthy", lambda: True)
    response = client.get("/about")
    assert response.status_code == 200
    assert "How Fixture works" in response.text
    assert "API and database up" in response.text
    assert "Marcus Bell" in response.text and "user_02" in response.text
    assert 'href="/about" aria-current="page">How it works' in response.text


def test_about_page_when_api_is_down(monkeypatch):
    monkeypatch.setattr(api_client, "is_healthy", lambda: False)
    response = client.get("/about")
    assert response.status_code == 200
    assert "API unreachable" in response.text


def test_about_page_when_database_is_down(monkeypatch):
    monkeypatch.setattr(api_client, "is_healthy", lambda: True)
    monkeypatch.setattr(api_client, "list_users", raise_(api_client.ApiUnavailable("503")))
    response = client.get("/about")
    assert "Database unreachable" in response.text


# --- api_client ------------------------------------------------------------------


def test_unreachable_api_raises_api_unavailable(monkeypatch):
    with socket.socket() as s:  # find a local port with nothing listening
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(api_client, "API_URL", f"http://localhost:{port}")
    with pytest.raises(api_client.ApiUnavailable):
        api_client.list_users()


def test_format_result():
    assert api_client.format_result(RESULT) == {
        "sender": "Jordan Lee",
        "date": "Tue, Oct 13, 2026 · 3:05 PM",
        "subject": "Re: Northbridge Capital first-round interview",
        "label": "Acceptance",
        "label_key": "acceptance",
        "score": "0.797",
        "strength": 80,
        "snippet": "Great, let's do Tuesday, October 20 at 2:30 pm Eastern.",
        "body": "Great, let's do Tuesday, October 20 at 2:30 pm Eastern.",
        "message_id": "0ed574b41b112de0",
        "thread_id": "",
        "chunk_index": 0,
    }


def test_sender_without_name_shows_placeholder():
    assert api_client.sender_label({"sender_name": "", "sender": "<EMAIL_007>"}) == "EMAIL_007"
    assert api_client.sender_label({"sender_name": "", "sender": "EMAIL_007"}) == "EMAIL_007"


def test_long_snippet_is_cut_on_a_word():
    text = "word " * 100
    result = api_client.snippet(text)
    assert len(result) <= api_client.SNIPPET_LENGTH + 1
    assert result.endswith("word…")


def test_bad_timestamp_is_shown_as_is():
    assert api_client.readable_date("") == ""
    assert api_client.readable_date("not a date") == "not a date"


def test_full_text_keeps_line_breaks_and_drops_the_header():
    text = "From: A\nSubject: S\nDate: D\n\nHi,\n\nSee you then."
    assert api_client.message_body(text) == "Hi,\n\nSee you then."


def test_match_bar_width_stays_between_0_and_100():
    assert api_client.format_result({**RESULT, "score": 1.2})["strength"] == 100
    assert api_client.format_result({**RESULT, "score": -0.1})["strength"] == 0


def test_format_user():
    user = {"user_id": "user_01", "name": "Priya Shah", "indexed_at": "2026-10-20T02:25:39+00:00"}
    assert api_client.format_user(user)["indexed"] == "Tue, Oct 20, 2026 · 2:25 AM UTC"
    assert api_client.format_user({**user, "indexed_at": ""})["indexed"] == ""
