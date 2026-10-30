"""Label the dashboard's recent emails with the classifier (Gemini), using the cache.

How a dashboard load works:
  1. Ask the classifier's /health for the current rules version. If it can't
     be reached, every email falls back to the old keyword match.
  2. Emails already in the cache for that rules version are shown at once.
  3. The rest are classified in the background, MAX_PARALLEL at a time: fetch
     the Gmail thread (read-only), strip quoted replies and signatures, send it.
     Each answer is saved to the cache as soon as it arrives.
  4. The page waits at most WAIT_SECONDS. Emails not done by then show as
     "Classifying..." and keep going in the background, so a reload shows them.

Logs hold Gmail message ids, labels and timing only, never email text.
"""

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

from google.oauth2.credentials import Credentials

import classifier_client
import cleaning
import google_data
from api_client import LABELS
from classification_cache import ClassificationCache

log = logging.getLogger("fixture.labels")

MAX_PARALLEL = 5  # Gemini calls at once (also Gmail thread fetches)
WAIT_SECONDS = 15  # longest the dashboard waits for new labels
MAX_THREAD_MESSAGES = 20  # thread messages sent, ending at the target (the classifier uses the last 10)
MAX_BODY_CHARS = 10_000  # per message, before sending (the classifier cuts at 4,000)

_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix="classify")
# Classifications still running, by (account, Gmail message id), so a reload
# during a slow first load waits for the same job instead of calling Gemini again.
_running: dict[tuple[str, str], Future] = {}
_running_lock = threading.Lock()


def label_emails(creds: Credentials, emails: list[dict], cache: ClassificationCache, user_email: str,
                 wait_seconds: float = WAIT_SECONDS) -> dict:
    """Add an "ai" entry to every email, and return a summary for the page.

    email["ai"]["state"] is one of:
      "done"     label, label_name, needs_response, reason are set
      "pending"  still classifying (shown as "Classifying...")
      "error"    this email couldn't be classified; the page shows its keyword match
      "off"      the classifier is down; the page shows keyword matches for all emails
    Also sets email["is_scheduling"] and email["needs_response"] for the filters.
    """
    try:
        info = classifier_client.health()
    except classifier_client.ClassifierUnavailable as e:
        log.warning("classifier unavailable (%s); using keyword fallback", e)
        for email in emails:
            _set(email, {"state": "off"})
        return {"mode": "fallback", "model": None, "rules_version": None, "pending": 0, "errors": 0}

    version = info["rules_version"]
    cached = cache.load_many(user_email, [e["id"] for e in emails], version)
    jobs = {e["id"]: _start(creds, e, cache, user_email) for e in emails if e["id"] not in cached}
    finished, _ = wait(jobs.values(), timeout=wait_seconds) if jobs else (set(), set())

    for email in emails:
        if email["id"] in cached:
            _set(email, _done(cached[email["id"]]))
        elif jobs[email["id"]] not in finished:
            _set(email, {"state": "pending"})
        elif jobs[email["id"]].exception() is not None:
            _set(email, {"state": "error"})
        else:
            _set(email, _done(jobs[email["id"]].result()))

    states = [e["ai"]["state"] for e in emails]
    return {"mode": "gemini", "model": info.get("model"), "rules_version": version,
            "pending": states.count("pending"), "errors": states.count("error")}


def _done(result: dict) -> dict:
    return {"state": "done", "label": result["label"], "label_name": LABELS.get(result["label"], result["label"]),
            "needs_response": bool(result["needs_response"]), "reason": result["reason"]}


def _set(email: dict, ai: dict) -> None:
    """Attach the result, and the two flags the dashboard's filters use."""
    email["ai"] = ai
    if ai["state"] == "done":
        email["is_scheduling"] = ai["label"] != "none"
    else:  # keyword fallback (also shown for pending, until the label arrives)
        email["is_scheduling"] = bool(email.get("scheduling_match"))
    email["needs_response"] = ai.get("needs_response", False)


def _start(creds, email, cache, user_email) -> Future:
    """Start classifying one email in the background, or join the job already running."""
    key = (user_email.lower(), email["id"])
    with _running_lock:
        job = _running.get(key)
        if job is None:
            job = _executor.submit(classify_one, creds, email["id"], email["thread_id"], cache, user_email)
            _running[key] = job
            job.add_done_callback(lambda _, key=key: _forget(key))
        return job


def _forget(key: tuple[str, str]) -> None:
    with _running_lock:
        _running.pop(key, None)


def classify_one(creds, message_id: str, thread_id: str, cache: ClassificationCache, user_email: str) -> dict:
    """Fetch one email's thread, classify it, cache the answer and return it.

    Raises on any failure (Gmail error, classifier down, message not found):
    nothing is cached and the page shows the keyword fallback for this email.
    """
    start = time.perf_counter()
    try:
        thread = google_data.fetch_thread(creds, thread_id)
        payload, target = thread_payload(thread, message_id, user_email)
        result = classifier_client.classify(payload, target, message_id=message_id)
    except Exception as e:
        # The exception type only: messages from Gmail or httpx could carry details.
        log.warning("classify failed message_id=%s error=%s", message_id, type(e).__name__)
        raise
    cache.save(user_email, message_id, result)
    log.info("classified message_id=%s label=%s needs_response=%s classifier_ms=%s total_ms=%d",
             message_id, result["label"], result["needs_response"], result.get("latency_ms"),
             (time.perf_counter() - start) * 1000)
    return result


def thread_payload(thread: list[dict], message_id: str, user_email: str) -> tuple[list[dict], int]:
    """Build the classifier's thread (up to and including the target) and the target's index.

    Bodies are cleaned with the rules copied from src/preprocess (quoted replies,
    signatures and footers removed). Raises LookupError if the message isn't in the thread.
    """
    ids = [m["id"] for m in thread]
    if message_id not in ids:
        raise LookupError("message not in its thread")
    end = ids.index(message_id) + 1
    messages = thread[max(0, end - MAX_THREAD_MESSAGES):end]
    payload = []
    for m in messages:
        body = cleaning.clean_body(m["body"], m["sender_name"]) or m["body"].strip()
        payload.append({
            "from": m["from"],
            "to": m["to"],
            "date": m["date"],
            "subject": m["subject"],
            "body": body[:MAX_BODY_CHARS],
            "from_user": m["sent"] or (bool(user_email) and m["address"].lower() == user_email.lower()),
        })
    return payload, len(payload) - 1
