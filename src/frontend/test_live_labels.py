"""Tests for live email labeling: the cache, building the classifier's thread,
the keyword fallback, and the dashboard. Gmail and the classifier are never
called: every test uses fakes and made-up emails."""

import base64
import json
import os
import sqlite3
import threading
import uuid
from base64 import b64encode

import pytest
from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials
from itsdangerous import TimestampSigner

import classifier_client
import google_data
import live_labels
import main
from classification_cache import ClassificationCache, account_key

USER = "sam@example.edu"
OTHER = "someone.else@example.com"


def new_id() -> str:
    """A fresh message id per test, so background jobs from one test never meet another's."""
    return uuid.uuid4().hex[:16]


def email(message_id: str, keyword: str | None = None) -> dict:
    """An email as google_data.fetch_emails returns it."""
    return {"id": message_id, "thread_id": f"t-{message_id}", "sender": "Jordan Lee", "address": "jordan@example.com",
            "subject": "Coffee chat?", "date": "Tue, Oct 13", "unread": False, "snippet": "Could we meet?",
            "scheduling_match": keyword}


def thread_message(message_id: str, body: str, sender="Jordan Lee <jordan@example.com>", sent=False) -> dict:
    """A thread message as google_data.fetch_thread returns it."""
    name, address = sender.split(" <")
    return {"id": message_id, "from": sender, "sender_name": name, "address": address.rstrip(">"),
            "to": USER, "date": "Tue, 13 Oct 2026 09:12:00 -0400", "subject": "Coffee chat?", "body": body, "sent": sent}


def answer(label="new_request", needs_response=True, version="1.2") -> dict:
    return {"label": label, "needs_response": needs_response, "reason": "D1: asks to meet; NR1.",
            "model": "gemini-test", "rules_version": version, "latency_ms": 5}


@pytest.fixture
def cache(tmp_path):
    return ClassificationCache(tmp_path / "fixture.db")


@pytest.fixture
def classifier(monkeypatch):
    """A fake classifier (rules v1.2) and Gmail. Records every classify call."""
    calls = []

    def fake_classify(thread, target_index, message_id=""):
        calls.append({"thread": thread, "target_index": target_index, "message_id": message_id})
        return answer()

    monkeypatch.setattr(classifier_client, "health", lambda: {"status": "ok", "model": "gemini-test", "rules_version": "1.2"})
    monkeypatch.setattr(classifier_client, "classify", fake_classify)
    monkeypatch.setattr(google_data, "fetch_thread",
                        lambda creds, thread_id: [thread_message(thread_id[2:], "Could we find 20 minutes?")])
    return calls


def raise_(error):
    def fake(*args, **kwargs):
        raise error
    return fake


# --- The cache ----------------------------------------------------------------


def test_cache_saves_and_loads(cache):
    cache.save(USER, "m1", answer(needs_response=False))
    row = cache.load_many(USER, ["m1", "missing"], "1.2")["m1"]
    assert row["label"] == "new_request" and row["needs_response"] is False
    assert row["model"] == "gemini-test" and row["rules_version"] == "1.2" and row["classified_at"]
    assert cache.load_many(USER, [], "1.2") == {}


def test_cache_ignores_rows_from_other_rules_versions(cache):
    cache.save(USER, "m1", answer(version="1.1"))
    assert cache.load_many(USER, ["m1"], "1.2") == {}
    cache.save(USER, "m1", answer(label="acceptance", version="1.2"))  # re-classified: replaces the row
    assert cache.load_many(USER, ["m1"], "1.2")["m1"]["label"] == "acceptance"


def test_cache_is_separate_per_account(cache):
    cache.save(USER, "m1", answer(label="acceptance"))
    assert cache.load_many(OTHER, ["m1"], "1.2") == {}  # same message id, other account
    cache.save(OTHER, "m1", answer(label="none"))
    assert cache.load_many(USER, ["m1"], "1.2")["m1"]["label"] == "acceptance"
    assert cache.load_many(OTHER, ["m1"], "1.2")["m1"]["label"] == "none"
    assert cache.load_many(USER.upper(), ["m1"], "1.2")["m1"]["label"] == "acceptance"  # case doesn't matter


def test_delete_account_removes_only_that_accounts_rows(cache):
    cache.save(USER, "m1", answer())
    cache.save(USER, "m2", answer())
    cache.save(OTHER, "m1", answer())
    cache.delete_account(USER)
    assert cache.load_many(USER, ["m1", "m2"], "1.2") == {}
    assert set(cache.load_many(OTHER, ["m1"], "1.2")) == {"m1"}


def test_cache_has_no_email_text_or_address(cache):
    cache.save(USER, "m1", answer())
    with sqlite3.connect(cache.db_path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(classifications)")]
        stored = db.execute("SELECT * FROM classifications").fetchone()
    assert columns == ["account", "message_id", "label", "needs_response", "reason", "model", "rules_version",
                       "classified_at"]
    assert stored[0] == account_key(USER) and USER not in " ".join(map(str, stored))  # hashed, not the address


def test_old_cache_table_without_accounts_is_replaced(tmp_path):
    with sqlite3.connect(tmp_path / "fixture.db") as db:
        db.execute("CREATE TABLE classifications (message_id TEXT PRIMARY KEY, label TEXT)")
        db.execute("INSERT INTO classifications VALUES ('m1', 'none')")
    cache = ClassificationCache(tmp_path / "fixture.db")
    cache.save(USER, "m1", answer())
    assert set(cache.load_many(USER, ["m1"], "1.2")) == {"m1"}


# --- Building the thread for the classifier --------------------------------------


def test_thread_payload_cleans_bodies_and_marks_the_user():
    thread = [
        thread_message("a", "Could we find 20 minutes next week?"),
        thread_message("b", "Sure, Tue 2-4 works.\n\nOn Tue, Oct 13, 2026 Jordan Lee wrote:\n> Could we find 20 minutes?",
                       sender="Sam Student <SAM@example.edu>"),  # matched by address, case-insensitively
        thread_message("c", "Tuesday at 2:30 works.\n\nBest,\nJordan\nAssociate, Example Co\n+1 617 555 0142"),
        thread_message("d", "A later message."),
    ]
    payload, target = live_labels.thread_payload(thread, "c", USER)
    assert target == 2 and len(payload) == 3  # stops at the target
    assert payload[1]["body"] == "Sure, Tue 2-4 works."  # quoted reply cut (cleaning copied from preprocess)
    assert "Associate" not in payload[2]["body"] and "555" not in payload[2]["body"]  # signature cut
    assert [m["from_user"] for m in payload] == [False, True, False]
    assert set(payload[0]) == {"from", "to", "date", "subject", "body", "from_user"}


def test_sent_label_marks_the_users_message():
    payload, _ = live_labels.thread_payload([thread_message("a", "Hi", sent=True)], "a", "")
    assert payload[0]["from_user"] is True


def test_long_threads_are_trimmed_before_sending():
    thread = [thread_message(str(i), f"message {i}") for i in range(30)]
    payload, target = live_labels.thread_payload(thread, "29", USER)
    assert len(payload) == live_labels.MAX_THREAD_MESSAGES and target == len(payload) - 1
    assert payload[-1]["body"] == "message 29"


def test_message_missing_from_thread():
    with pytest.raises(LookupError):
        live_labels.thread_payload([thread_message("a", "Hi")], "zzz", USER)


# --- Labeling a page of emails ----------------------------------------------------


def test_uncached_emails_are_classified_and_cached(classifier, cache):
    emails = [email(new_id()), email(new_id())]
    summary = live_labels.label_emails("creds", emails, cache, USER)
    assert summary == {"mode": "gemini", "model": "gemini-test", "rules_version": "1.2", "pending": 0, "errors": 0}
    assert {c["message_id"] for c in classifier} == {e["id"] for e in emails}
    assert all(e["ai"]["state"] == "done" and e["ai"]["label_name"] == "New request" for e in emails)
    assert all(e["is_scheduling"] and e["needs_response"] for e in emails)
    assert set(cache.load_many(USER, [e["id"] for e in emails], "1.2")) == {e["id"] for e in emails}


def test_cached_emails_are_not_classified_again(classifier, cache):
    cached = email(new_id())
    cache.save(USER, cached["id"], answer(label="none", needs_response=False))
    live_labels.label_emails("creds", [cached], cache, USER)
    assert classifier == []
    assert cached["ai"]["label"] == "none" and not cached["is_scheduling"] and not cached["needs_response"]


def test_new_rules_version_means_classify_again(classifier, cache):
    old = email(new_id())
    cache.save(USER, old["id"], answer(version="1.1"))
    live_labels.label_emails("creds", [old], cache, USER)
    assert [c["message_id"] for c in classifier] == [old["id"]]


def test_another_accounts_cache_is_not_used(classifier, cache):
    shared = email(new_id())
    cache.save(OTHER, shared["id"], answer(label="none"))
    live_labels.label_emails("creds", [shared], cache, USER)
    assert [c["message_id"] for c in classifier] == [shared["id"]]


def test_classifier_down_falls_back_to_keywords(monkeypatch, cache):
    monkeypatch.setattr(classifier_client, "health", raise_(classifier_client.ClassifierUnavailable("down")))
    monkeypatch.setattr(classifier_client, "classify", raise_(AssertionError("must not be called")))
    emails = [email(new_id(), keyword="meeting"), email(new_id())]
    summary = live_labels.label_emails("creds", emails, cache, USER)
    assert summary["mode"] == "fallback"
    assert [e["ai"]["state"] for e in emails] == ["off", "off"]
    assert [e["is_scheduling"] for e in emails] == [True, False]  # the keyword match decides
    assert not any(e["needs_response"] for e in emails)


def test_one_failed_email_falls_back_and_is_not_cached(classifier, monkeypatch, cache):
    monkeypatch.setattr(classifier_client, "classify", raise_(classifier_client.ClassifierUnavailable("503")))
    failed = email(new_id(), keyword="interview")
    summary = live_labels.label_emails("creds", [failed], cache, USER)
    assert summary["errors"] == 1
    assert failed["ai"] == {"state": "error"} and failed["is_scheduling"] is True
    assert cache.load_many(USER, [failed["id"]], "1.2") == {}


def test_slow_emails_show_as_pending_and_finish_in_the_background(classifier, monkeypatch, cache):
    release = threading.Event()

    def slow_classify(thread, target_index, message_id=""):
        release.wait(5)
        return answer()

    monkeypatch.setattr(classifier_client, "classify", slow_classify)
    slow = email(new_id())
    summary = live_labels.label_emails("creds", [slow], cache, USER, wait_seconds=0.05)
    assert summary["pending"] == 1 and slow["ai"] == {"state": "pending"}

    release.set()
    for job in list(live_labels._running.values()):
        job.result(timeout=5)
    assert slow["id"] in cache.load_many(USER, [slow["id"]], "1.2")  # cached for the next page load


# --- Reading Gmail messages (no network) --------------------------------------------


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_message_text_prefers_plain_text_and_skips_attachments():
    payload = {"mimeType": "multipart/mixed", "parts": [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("Plain café text")}},
            {"mimeType": "text/html", "body": {"data": b64("<p>HTML text</p>")}},
        ]},
        {"mimeType": "text/plain", "filename": "notes.txt", "body": {"attachmentId": "x"}},
    ]}
    assert google_data.message_text(payload) == "Plain café text"


def test_message_text_converts_html_only_mail():
    markup = "<html><head><style>p {color: red}</style></head><body><p>Hi&nbsp;Sam,</p><div>Free Tue?</div></body></html>"
    payload = {"mimeType": "text/html", "body": {"data": b64(markup)}}
    assert google_data.message_text(payload) == "Hi\xa0Sam,\n\nFree Tue?"


def test_format_thread_message():
    message = {"id": "m1", "labelIds": ["SENT"], "snippet": "", "payload": {
        "mimeType": "text/plain", "body": {"data": b64("Sure!")},
        "headers": [{"name": "From", "value": "Sam Student <Sam@Example.edu>"},
                    {"name": "To", "value": "Jordan Lee <jordan@example.com>"},
                    {"name": "Cc", "value": "team@example.com"},
                    {"name": "Subject", "value": "Re: Coffee chat?"}]}}
    result = google_data.format_thread_message(message)
    assert result["address"] == "sam@example.edu" and result["sender_name"] == "Sam Student"
    assert result["to"] == "jordan@example.com, team@example.com"
    assert result["body"] == "Sure!" and result["sent"] is True


# --- The dashboard ----------------------------------------------------------------


@pytest.fixture
def dashboard(monkeypatch):
    """A signed-in browser whose Google data is faked. Returns (client, emails, address)."""
    address = "dashboard.user@example.com"
    main.store.save(address, Credentials(token="fake"), name="Dash User")
    monkeypatch.setattr(main, "current_credentials", lambda request: "fake-credentials")
    monkeypatch.setattr(google_data, "fetch_events", lambda creds: {"items": [], "calendars": [], "skipped": []})
    emails = [email(new_id(), keyword="meeting"), email(new_id())]
    monkeypatch.setattr(google_data, "fetch_emails", lambda creds: [dict(e) for e in emails])

    browser = TestClient(main.app)
    session = b64encode(json.dumps({"email": address}).encode())
    browser.cookies.set("session", TimestampSigner(os.environ["SESSION_SECRET"]).sign(session).decode())
    return browser, emails, address


def test_dashboard_shows_gemini_labels(dashboard, classifier):
    browser, emails, address = dashboard
    main.label_cache.save(address, emails[1]["id"], answer(label="none", needs_response=False))
    page = browser.get("/").text
    assert "Labeled by Gemini (gemini-test) using labeling rules v1.2" in page
    assert 'class="label-chip label-new_request" title="D1: asks to meet; NR1."' in page  # reason on hover
    assert "Needs response</span>" in page and 'data-filter="needs-response"' in page
    assert "Not scheduling" in page  # the cached one
    assert [c["message_id"] for c in classifier] == [emails[0]["id"]]  # only the uncached one
    assert "keyword rules" not in page.split("<footer")[0].split('class="footnote"')[0]

    browser.get("/")  # reload: everything is cached now
    assert len(classifier) == 1


def test_sign_out_deletes_the_accounts_cached_labels(dashboard, classifier):
    browser, emails, address = dashboard
    browser.get("/")
    ids = [e["id"] for e in emails]
    assert set(main.label_cache.load_many(address, ids, "1.2")) == set(ids)
    main.label_cache.save(OTHER, ids[0], answer())

    browser.get("/auth/logout", follow_redirects=False)
    assert main.label_cache.load_many(address, ids, "1.2") == {}
    assert set(main.label_cache.load_many(OTHER, ids, "1.2")) == {ids[0]}  # other accounts keep theirs


def test_dashboard_falls_back_when_classifier_is_down(dashboard, monkeypatch):
    browser, _, _ = dashboard
    monkeypatch.setattr(classifier_client, "health", raise_(classifier_client.ClassifierUnavailable("down")))
    page = browser.get("/").text
    assert "The Gemini classifier isn't reachable" in page
    assert ">Scheduling</span>" in page  # the keyword tag
    assert "mentions <strong>“meeting”</strong>" in page
    assert 'data-filter="needs-response"' not in page  # no Gemini, no needs-response filter


def test_unreachable_classifier_raises_classifier_unavailable(monkeypatch):
    monkeypatch.setattr(classifier_client, "CLASSIFIER_URL", "http://127.0.0.1:9")  # nothing listens here
    with pytest.raises(classifier_client.ClassifierUnavailable):
        classifier_client.health()
    with pytest.raises(classifier_client.ClassifierUnavailable):
        classifier_client.classify([{"from": "a@example.com", "body": "hi"}], 0)
