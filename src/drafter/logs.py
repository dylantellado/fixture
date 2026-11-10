"""Structured JSON logs that Cloud Logging understands (same format as the classifier's).

Each record is one JSON object on one line of stdout: severity, message, time,
logger, plus allow-listed fields (jsonPayload on Cloud Run), e.g.

    {"severity": "INFO", "message": "draft: status=drafted label=new_request attempts=1 latency_ms=5210",
     "time": "2026-11-09T20:15:02.311Z", "logger": "drafter", "event": "draft", "status": "drafted",
     "label": "new_request", "allowed_slots": 12, "offered_count": 3, "checks_passed": 7,
     "checks_failed": 0, "latency_ms": 5210, "input_tokens": 4120, ...}

Privacy: email text, subjects, addresses, names, the draft and the times in it
are never passed to the logger. As a second guard, the formatter writes only the
fields in ALLOWED_FIELDS and drops anything else, and stack traces keep the
exception type but not its message (a message could quote data). Failed checks
are logged by name only; their details can quote the draft.
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

# The only extra fields a log line may carry. Never add email text, subjects, senders,
# recipients, names, the draft, check details, or times from the draft.
ALLOWED_FIELDS = {
    "event",             # startup, draft, gemini_retry
    "status",            # drafted, no_reply_needed, no_free_time, error
    "error_type",        # e.g. checks_failed, gemini_unavailable, classifier_unavailable, invalid_request
    "message_id",        # the caller's id for the target email (optional), never its text
    "label", "needs_response",
    "classification_source",  # request (sent by the caller) or classifier (called here)
    "action",            # what the draft does: offer_times, accept_time, ...
    "thread_length", "busy_count", "past_messages", "context_used", "context_method",
    "meeting_minutes", "meeting_minutes_source",
    "allowed_slots",     # candidate slots offered to the model
    "free_windows",
    "offered_count", "accepted", "confirmed",
    "checks_passed", "checks_failed", "failed_checks",  # failed_checks: names only
    "attempts",          # draft attempts (2 = the checker asked for one retry)
    "gemini_calls", "input_tokens", "output_tokens", "thinking_tokens", "embedding_tokens",
    "latency_ms", "classify_ms", "context_ms", "gemini_ms",
    "model", "embedding_model", "project", "location", "thinking_budget", "temperature",
    "rules_version", "rules_custom", "warnings_count",
    "gemini_code", "classifier_url_kind",
}


def _stack_without_message(exc_info) -> str:
    exc_type, _, tb = exc_info
    return f"Traceback (most recent call last):\n{''.join(traceback.format_tb(tb))}{exc_type.__name__}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "logger": record.name,
        }
        fields = getattr(record, "fields", None) or {}
        entry.update({k: v for k, v in fields.items() if k in ALLOWED_FIELDS and v is not None})
        if record.exc_info and record.exc_info[0] is not None:
            entry["stack_trace"] = _stack_without_message(record.exc_info)
        return json.dumps(entry, default=str)


def setup(level: int = logging.INFO) -> logging.Handler:
    """Send every log record (ours, uvicorn's, libraries') to stdout as JSON."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        if uvicorn_logger.handlers:
            uvicorn_logger.handlers[:] = [handler]
    for name in ("httpx", "httpcore", "google_genai", "google.auth"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return handler
