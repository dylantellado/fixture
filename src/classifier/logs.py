"""Structured JSON logs that Cloud Logging understands.

Each log record becomes one JSON object on one line of stdout. Cloud Run sends stdout
to Cloud Logging, which reads `severity`, `message` and `time` and keeps every other
field in `jsonPayload`, so entries can be searched (jsonPayload.label="acceptance")
and counted by log-based metrics (see cloud/metrics/).

Example line:
    {"severity": "INFO", "message": "classified: label=none needs_response=false latency_ms=2104",
     "time": "2026-11-09T20:15:02.311Z", "logger": "classifier", "event": "classify",
     "outcome": "ok", "label": "none", "needs_response": false, "latency_ms": 2104, ...}

Privacy: email text, subjects, addresses and Gemini's reason are never passed to the
logger. As a second guard, the formatter writes only the fields in ALLOWED_FIELDS and
drops anything else, and stack traces keep the exception type but not its message
(a message could quote data).

Usage:
    log.info("classified", extra={"fields": {"event": "classify", "label": "none"}})
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

# The only extra fields a log line may carry. Never add email text, subjects,
# senders, recipients or Gemini's reason here.
ALLOWED_FIELDS = {
    "event",            # what happened: startup, classify, gemini_retry
    "outcome",          # classify: ok or error
    "message_id",       # the caller's id for the email (optional), never its text
    "thread_length", "target_index",
    "label", "needs_response",
    "latency_ms",       # time spent getting the label from Gemini, including retries
    "attempts",         # Gemini calls made for this email (1 = no retry)
    "input_tokens", "output_tokens", "thinking_tokens",
    "model", "project", "location", "thinking_budget",
    "rules_version", "rules_sha256", "rules_path",
    "error_type",       # short error kind, e.g. rate_limited, invalid_answer
    "status",           # HTTP status this service returned
    "gemini_code",      # HTTP status Vertex AI returned, when it returned one
}


def _stack_without_message(exc_info) -> str:
    """The traceback's frames and the exception type, without the exception's message."""
    exc_type, _, tb = exc_info
    frames = "".join(traceback.format_tb(tb))
    return f"Traceback (most recent call last):\n{frames}{exc_type.__name__}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            # Cloud Logging reads DEBUG, INFO, WARNING, ERROR and CRITICAL as severities.
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

    # uvicorn sets up its own text handlers before it imports this app. Swap them for
    # the JSON one. (uvicorn.access has no handler when started with --no-access-log;
    # Cloud Run's request logs already record every request.)
    for name in ("uvicorn", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        if uvicorn_logger.handlers:
            uvicorn_logger.handlers[:] = [handler]

    # These log every HTTP request to Vertex AI at INFO; warnings and errors are enough.
    for name in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return handler
