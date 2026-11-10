"""Tests for "Draft reply": gathering the inputs (free/busy, time zone, past emails,
cached label), the /api/draft-reply route and the dashboard button. Google and the
drafter are never called: every test uses fakes and made-up emails."""

import json
import logging
import os
import sqlite3
import uuid
from base64 import b64encode
from datetime import datetime
from types import SimpleNamespace

import httplib2
import pytest
from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from itsdangerous import TimestampSigner

import classifier_client
import draft_inputs
import drafter_client
import google_data
import main

USER = "draft.user@example.com"


class Call:
    """Stands in for a googleapiclient request: .execute() returns the result."""

    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def http_error(status=500):
    return HttpError(httplib2.Response({"status": status}), b"{}")


# --- Calendar: free/busy and time zone ----------------------------------------------


class FakeCalendar:
    def __init__(self, calendars, freebusy, timezone="America/New_York"):
        self.calendars_list, self.freebusy_result, self.timezone = calendars, freebusy, timezone
        self.queries = []

    def calendarList(self):
        return SimpleNamespace(list=lambda: Call({"items": self.calendars_list}))

    def calendars(self):
        return SimpleNamespace(get=lambda calendarId: Call({"timeZone": self.timezone}))

    def freebusy(self):
        def query(body):
            self.queries.append(body)
            return Call(self.freebusy_result)
        return SimpleNamespace(query=query)


def test_calendar_context_reads_free_busy_of_checked_calendars(monkeypatch):
    service = FakeCalendar(
        calendars=[{"id": "me@example.com", "primary": True, "selected": True},
                   {"id": "class@example.com", "summary": "Classes", "selected": True},
                   {"id": "hidden@example.com", "summary": "Hidden", "selected": False},
                   {"id": "shared@example.com", "summary": "Team", "selected": True, "accessRole": "freeBusyReader"},
                   {"id": "broken@example.com", "summary": "Broken", "selected": True}],
        freebusy={"calendars": {
            "me@example.com": {"busy": [{"start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"}]},
            "class@example.com": {"busy": [{"start": "2026-11-11T15:00:00Z", "end": "2026-11-11T16:15:00Z"}]},
            "shared@example.com": {"busy": [{"start": "2026-11-12T18:00:00Z", "end": "2026-11-12T19:00:00Z"}]},
            "broken@example.com": {"errors": [{"domain": "global", "reason": "notFound"}]},
        }})
    monkeypatch.setattr(google_data, "build", lambda *args, **kwargs: service)
    result = google_data.fetch_calendar_context("creds", days=14)
    assert result["timezone"] == "America/New_York"
    assert [b["start"] for b in result["busy"]] == ["2026-11-10T14:00:00Z", "2026-11-11T15:00:00Z",
                                                     "2026-11-12T18:00:00Z"]
    assert result["unreadable"] == ["Broken"] and result["calendars"] == 3
    [query] = service.queries
    assert [item["id"] for item in query["items"]] == ["me@example.com", "class@example.com", "shared@example.com",
                                                       "broken@example.com"]  # checked calendars only
    assert query["timeMax"] == result["busy_until"]
    span = datetime.fromisoformat(query["timeMax"]) - datetime.fromisoformat(query["timeMin"])
    assert span.days == 14


# --- Gmail: past messages with the sender --------------------------------------------


def thread_message(message_id, body, sender="Jordan Lee <jordan@example.com>", to=USER, sent=False):
    name, address = sender.split(" <")
    return {"id": message_id, "from": sender, "sender_name": name, "address": address.rstrip(">").lower(),
            "to": to, "date": "Tue, 20 Oct 2026 16:05:00 -0400", "subject": "Earlier chat", "body": body,
            "sent": sent}


class FakeGmail:
    def __init__(self, thread_ids):
        self.thread_ids = thread_ids
        self.queries = []

    def users(self):
        return self

    def threads(self):
        return self

    def list(self, userId, q, maxResults):
        self.queries.append({"q": q, "maxResults": maxResults})
        return Call({"threads": [{"id": t} for t in self.thread_ids]})


def test_past_messages_search_the_sender_and_skip_this_thread(monkeypatch):
    gmail = FakeGmail(["current", "t1", "t2", "t3"])
    monkeypatch.setattr(google_data, "build", lambda *args, **kwargs: gmail)
    threads = {
        "t1": [thread_message("a", "from Jordan"),
               thread_message("b", "from Sam", sender=f"Sam <{USER}>", to="jordan@example.com", sent=True),
               thread_message("c", "someone else", sender="Other <other@example.com>")],
        "t2": [thread_message(f"d{i}", f"message {i}") for i in range(8)],
        "t3": http_error(404),
    }

    def fake_fetch_thread(creds, thread_id):
        result = threads[thread_id]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(google_data, "fetch_thread", fake_fetch_thread)
    found = google_data.fetch_past_messages("creds", "jordan@example.com", "current", max_threads=10)
    assert gmail.queries == [{"q": 'from:"jordan@example.com" OR to:"jordan@example.com"', "maxResults": 11}]
    assert [m["id"] for m in found] == ["a", "b", "d3", "d4", "d5", "d6", "d7"]  # last 5 per thread; t3 skipped
    assert {m["thread_id"] for m in found} == {"t1", "t2"}


@pytest.mark.parametrize("address", ["", "not an address", 'x@example.com" OR from:"y@example.com'])
def test_unsearchable_addresses_are_not_searched(monkeypatch, address):
    monkeypatch.setattr(google_data, "build", lambda *a, **k: pytest.fail("Gmail should not be called"))
    assert google_data.fetch_past_messages("creds", address, "current") == []


# --- Gathering the drafter's inputs ---------------------------------------------------


@pytest.fixture
def google(monkeypatch):
    """Fake Gmail, Calendar, classifier health and drafter. Returns what the drafter was sent."""
    sent = {}
    thread = [
        thread_message("m1", "Could we find 30 minutes next week?\n\nBest,\nJordan\nRecruiter, Example Co\n+1 617 555 0142"),
        thread_message("m2", "Sure!\n\nOn Tue, Jordan Lee wrote:\n> Could we find 30 minutes?",
                       sender=f"Sam <{USER}>", to="jordan@example.com", sent=True),
        thread_message("m3", "Great, what works for you?"),
    ]
    monkeypatch.setattr(google_data, "fetch_thread", lambda creds, thread_id: [dict(m) for m in thread])
    monkeypatch.setattr(google_data, "fetch_calendar_context", lambda creds, days: {
        "busy": [{"start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"}],
        "busy_from": "2026-11-09T15:00:00+00:00", "busy_until": "2026-11-23T15:00:00+00:00",
        "timezone": "America/Chicago", "calendars": 2, "unreadable": []})
    monkeypatch.setattr(google_data, "fetch_past_messages", lambda creds, address, thread_id: [
        {**thread_message("p1", "I prefer mornings.\n\nOn Mon, Sam wrote:\n> hi"), "thread_id": "t9",
         "subject": "Info session", "date": "Tue, 20 Oct 2026 16:05:00 -0400"}])
    monkeypatch.setattr(classifier_client, "health", lambda: {"status": "ok", "model": "m", "rules_version": "1.5"})

    def fake_draft(payload):
        sent.update(payload)
        return {"status": "drafted", "draft_text": "Hi Jordan, ... Sam", "action": "offer_times",
                "offered_times": [{"start": "2026-11-11T10:00:00-06:00", "end": "2026-11-11T10:30:00-06:00",
                                   "label": "Wed, Nov 11, 10:00–10:30 AM CST"}],
                "accepted_time": None, "confirmed_time": None, "checks": [{"name": "answer_well_formed",
                                                                          "passed": True, "detail": "ok"}],
                "context_used": [{"id": "p1", "why": "Prefers mornings", "score": 0.8, "cited": True}],
                "warnings": ["from the drafter"], "model": "gemini-test", "rules_version": "1.0", "attempts": 1,
                "latency_ms": 4000, "label": "new_request"}

    monkeypatch.setattr(drafter_client, "draft", fake_draft)
    return sent


@pytest.fixture
def cache(tmp_path):
    from classification_cache import ClassificationCache
    return ClassificationCache(tmp_path / "fixture.db")


def test_draft_inputs_are_gathered_and_cleaned(google, cache):
    cache.save(USER, "m3", {"label": "proposed_times", "needs_response": True, "reason": "D2.", "model": "m",
                            "rules_version": "1.5"})
    result = draft_inputs.draft_reply("creds", cache, {"name": "Sam Rivera", "email": USER}, "m3", "thread-1")
    assert google["target_index"] == 2 and len(google["thread"]) == 3
    assert "617" not in google["thread"][0]["body"] and "Recruiter" not in google["thread"][0]["body"]
    assert google["thread"][1]["body"] == "Sure!" and google["thread"][1]["from_user"] is True
    assert google["user"] == {"name": "Sam Rivera", "email": USER, "timezone": "America/Chicago"}
    assert google["busy"] == [{"start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"}]
    assert google["busy_until"] == "2026-11-23T15:00:00+00:00"
    assert google["past_messages"] == [{"id": "p1", "thread_id": "t9", "from": "Jordan Lee <jordan@example.com>",
                                        "to": USER, "date": "Tue, 20 Oct 2026 16:05:00 -0400",
                                        "subject": "Info session", "body": "I prefer mornings.", "from_user": False}]
    assert google["classification"] == {"label": "proposed_times", "needs_response": True, "reason": "D2."}
    assert google["regenerate"] is False and google["message_id"] == "m3" and google["now"]
    # The browser gets the subject and date of each past email used (the drafter only knows ids).
    assert result["context_used"][0] == {"id": "p1", "why": "Prefers mornings", "score": 0.8, "cited": True,
                                              "subject": "Info session", "date": "Tue, Oct 20"}
    assert result["timezone"] == "America/Chicago" and result["warnings"] == ["from the drafter"]


def test_without_a_current_cached_label_the_drafter_classifies(google, cache):
    cache.save(USER, "m3", {"label": "none", "needs_response": False, "reason": "x", "model": "m",
                            "rules_version": "1.4"})  # old rules: ignored
    draft_inputs.draft_reply("creds", cache, {"name": "", "email": USER}, "m3", "thread-1", regenerate=True)
    assert "classification" not in google and google["regenerate"] is True


def test_older_email_and_unreadable_calendars_add_warnings(google, cache, monkeypatch):
    monkeypatch.setattr(google_data, "fetch_calendar_context", lambda creds, days: {
        "busy": [], "busy_from": "", "busy_until": "2026-11-23T15:00:00+00:00", "timezone": "UTC",
        "calendars": 1, "unreadable": ["Team"]})
    result = draft_inputs.draft_reply("creds", cache, {"name": "", "email": USER}, "m1", "thread-1")
    assert google["target_index"] == 0 and len(google["thread"]) == 1  # up to the email that was opened
    assert result["warnings"][:2] == ["Couldn't read busy times from: Team. Times there may not be free.",
                                      "This thread has newer messages; the draft replies to the email you opened."]


def test_replying_to_your_own_email_skips_the_past_email_search(google, cache, monkeypatch):
    monkeypatch.setattr(google_data, "fetch_past_messages", lambda *a: pytest.fail("no search for the user's own email"))
    draft_inputs.draft_reply("creds", cache, {"name": "", "email": USER}, "m2", "thread-1")
    assert google["past_messages"] == []


# --- The route and the dashboard ---------------------------------------------------------


@pytest.fixture
def browser(monkeypatch):
    """A signed-in browser (credentials faked)."""
    main.store.save(USER, Credentials(token="fake"), name="Sam Rivera")
    monkeypatch.setattr(main, "current_credentials", lambda request: "fake-credentials")
    client = TestClient(main.app)
    session = b64encode(json.dumps({"email": USER}).encode())
    client.cookies.set("session", TimestampSigner(os.environ["SESSION_SECRET"]).sign(session).decode())
    return client


def test_route_returns_the_drafters_answer(google, browser):
    response = browser.post("/api/draft-reply", json={"message_id": "m3", "thread_id": "thread-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "drafted" and body["context_used"][0]["subject"] == "Info session"
    assert google["user"]["name"] == "Sam Rivera"


def test_route_needs_sign_in(monkeypatch):
    monkeypatch.setattr(main, "current_credentials", lambda request: None)
    response = TestClient(main.app).post("/api/draft-reply", json={"message_id": "m3", "thread_id": "t"})
    assert response.status_code == 401 and "sign" in response.json()["error"]


@pytest.mark.parametrize("payload", [
    {"message_id": "m3"},
    {"message_id": "../etc", "thread_id": "t"},
    {"message_id": "m3", "thread_id": "a b"},
])
def test_route_rejects_bad_ids(browser, payload):
    assert browser.post("/api/draft-reply", json=payload).status_code == 422


@pytest.mark.parametrize("error, status", [
    (LookupError("not in thread"), 404),
    (http_error(500), 502),
    (drafter_client.DrafterUnavailable("ConnectError"), 503),
])
def test_route_turns_failures_into_messages(browser, monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(draft_inputs, "draft_reply", fail)
    response = browser.post("/api/draft-reply", json={"message_id": "m3", "thread_id": "t"})
    assert response.status_code == status and response.json()["error"] == main.DRAFT_ERRORS[
        {404: "not_found", 502: "google", 503: "drafter_down"}[status]]


def test_drafts_are_not_stored_or_logged(google, browser, caplog, monkeypatch):
    marker = "SECRET-" + uuid.uuid4().hex
    monkeypatch.setattr(google_data, "fetch_thread", lambda creds, thread_id: [
        thread_message("m3", f"{marker} could we meet?", sender=f"{marker} <jordan@example.com>")])
    original = drafter_client.draft
    monkeypatch.setattr(drafter_client, "draft", lambda payload: {**original(payload), "draft_text": marker})
    with caplog.at_level(logging.DEBUG):
        response = browser.post("/api/draft-reply", json={"message_id": "m3", "thread_id": "thread-1"})
    assert response.json()["draft_text"] == marker  # the browser gets it...
    assert marker not in caplog.text  # ...the logs don't
    assert "draft message_id=m3 status=drafted" in caplog.text
    with sqlite3.connect(main.DATA_DIR / "fixture.db") as db:  # ...and the database doesn't
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert sorted(tables) == ["classifications", "users"]
        for table in tables:
            assert marker not in json.dumps(db.execute(f"SELECT * FROM {table}").fetchall(), default=str)


def test_dashboard_shows_the_button_only_when_a_reply_is_needed(browser, monkeypatch):
    def labeled(message_id, needs_response):
        return {"id": message_id, "thread_id": f"t-{message_id}", "sender": "Jordan", "address": "j@example.com",
                "subject": "Hi", "date": "Tue, Nov 10", "unread": False, "snippet": "...", "scheduling_match": None}

    emails = [labeled("needs1", True), labeled("fyi1", False)]
    monkeypatch.setattr(google_data, "fetch_events", lambda creds: {"items": [], "calendars": [], "skipped": []})
    monkeypatch.setattr(google_data, "fetch_emails", lambda creds: [dict(e) for e in emails])

    def fake_labels(creds, items, cache, email):
        for item in items:
            needs = item["id"] == "needs1"
            item["ai"] = {"state": "done", "label": "new_request" if needs else "none", "label_name": "x",
                          "needs_response": needs, "reason": "r"}
            item["is_scheduling"], item["needs_response"] = needs, needs
        return {"mode": "gemini", "model": "m", "rules_version": "1.5", "pending": 0, "errors": 0}

    monkeypatch.setattr(main.live_labels, "label_emails", fake_labels)
    page = browser.get("/").text
    assert page.count('class="btn-draft"') == 1
    assert 'data-message-id="needs1" data-thread-id="t-needs1"' in page
    assert 'data-message-id="fyi1"' not in page
    assert "/static/draft.js" in page and "open one marked Needs response to draft a reply" in page


def test_draft_script_never_uses_inner_html():
    script = (main.APP_DIR / "static" / "draft.js").read_text()
    assert ".innerHTML" not in script and ".outerHTML" not in script and "insertAdjacentHTML(" not in script
    assert "textContent" in script
