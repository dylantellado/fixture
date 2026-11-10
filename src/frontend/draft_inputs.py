"""Gather what the drafter needs for one email, and shape its answer for the browser.

When the user clicks "Draft reply", main.py calls draft_reply(), which:
  1. reads the email's Gmail thread (read-only) and builds it like the
     classifier's thread: quoted replies and signatures stripped, the user's own
     messages marked;
  2. reads Calendar free/busy for the next 14 days across the checked calendars,
     and the calendar's time zone (read-only; no event details);
  3. searches Gmail for recent messages exchanged with the sender in the last
     ~10 other threads (read-only), cleaned the same way;
  4. adds the cached classification, if there is one for the current rules;
  5. sends it all to the drafter and returns its answer, with the subject and
     date of each past email it used (looked up here: the drafter only returns ids).

Nothing here is stored: no drafts, no email text, no calendar data. Logs hold the
Gmail message id, the status, counts and timing only.

SWAP LATER: step 3 is a live sender search. A persistent per-user inbox index
(built by a Gmail watcher) will replace it; the drafter's context.py is the
matching swap point on the service side.
"""

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import classifier_client
import cleaning
import drafter_client
import google_data
import live_labels
from classification_cache import ClassificationCache

log = logging.getLogger("fixture.drafts")

MAX_PAST_MESSAGES = 40  # sent to the drafter, which keeps the 5 most relevant
MAX_PAST_BODY_CHARS = 3000
BUSY_DAYS = 14


def cached_classification(cache: ClassificationCache, user_email: str, message_id: str) -> dict | None:
    """The dashboard's cached label for this email, if it was made with the current rules."""
    try:
        version = classifier_client.health()["rules_version"]
    except classifier_client.ClassifierUnavailable:
        return None  # the drafter will try the classifier itself
    row = cache.load_many(user_email, [message_id], version).get(message_id)
    if row is None:
        return None
    return {"label": row["label"], "needs_response": row["needs_response"], "reason": row["reason"]}


def past_messages(creds, address: str, thread_id: str, user_email: str) -> list[dict]:
    """Recent messages with the sender from other threads, cleaned, in the drafter's format."""
    found = google_data.fetch_past_messages(creds, address, thread_id)[:MAX_PAST_MESSAGES]
    return [{
        "id": m["id"], "thread_id": m["thread_id"], "from": m["from"], "to": m["to"], "date": m["date"],
        "subject": m["subject"],
        "body": (cleaning.clean_body(m["body"], m["sender_name"]) or m["body"].strip())[:MAX_PAST_BODY_CHARS],
        "from_user": m["sent"] or m["address"] == user_email.lower(),
    } for m in found]


def draft_reply(creds, cache: ClassificationCache, user: dict, message_id: str, thread_id: str,
                regenerate: bool = False) -> dict:
    """Gather the inputs, call the drafter, and return what the browser shows.

    user is {"name", "email"} of the signed-in user. Raises googleapiclient's
    HttpError (Gmail or Calendar failed), LookupError (the email isn't in that
    thread) or drafter_client.DrafterUnavailable.
    """
    started = time.perf_counter()
    thread = google_data.fetch_thread(creds, thread_id)
    payload_thread, target_index = live_labels.thread_payload(thread, message_id, user["email"])
    target = next(m for m in thread if m["id"] == message_id)
    calendar = google_data.fetch_calendar_context(creds, BUSY_DAYS)
    past = past_messages(creds, target["address"], thread_id, user["email"]) if not target["sent"] else []
    classification = cached_classification(cache, user["email"], message_id)
    gathered_ms = round((time.perf_counter() - started) * 1000)

    payload = {
        "message_id": message_id,
        "thread": payload_thread,
        "target_index": target_index,
        "user": {"name": user.get("name") or "", "email": user["email"], "timezone": calendar["timezone"]},
        "busy": calendar["busy"],
        "busy_until": calendar["busy_until"],
        "past_messages": past,
        "now": datetime.now(timezone.utc).isoformat(),
        "regenerate": regenerate,
    }
    if classification:
        payload["classification"] = classification
    result = drafter_client.draft(payload)

    # Warnings only the web app knows about.
    notes = []
    if calendar["unreadable"]:
        notes.append(f"Couldn't read busy times from: {', '.join(calendar['unreadable'])}. "
                     "Times there may not be free.")
    if thread[-1]["id"] != message_id:
        notes.append("This thread has newer messages; the draft replies to the email you opened.")

    past_by_id = {m["id"]: m for m in past}
    shown = dict(result)
    shown["warnings"] = notes + list(result.get("warnings", []))
    shown["context_used"] = [
        {**c, "subject": past_by_id.get(c["id"], {}).get("subject") or "(no subject)",
         "date": short_date(past_by_id.get(c["id"], {}).get("date", ""))}
        for c in result.get("context_used", [])]
    shown["timezone"] = calendar["timezone"]
    log.info("draft message_id=%s status=%s attempts=%s past=%d busy=%d gather_ms=%d drafter_ms=%s total_ms=%d",
             message_id, result.get("status"), result.get("attempts"), len(past), len(calendar["busy"]),
             gathered_ms, result.get("latency_ms"), (time.perf_counter() - started) * 1000)
    return shown


def short_date(header: str) -> str:
    """'Tue, 20 Oct 2026 16:05:00 -0400' -> 'Tue, Oct 20'; anything unparseable -> ''."""
    try:
        return google_data.format_day(parsedate_to_datetime(header).date())
    except (TypeError, ValueError, IndexError):
        return ""
