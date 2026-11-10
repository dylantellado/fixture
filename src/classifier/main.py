"""Fixture classifier: label one email with Gemini, following docs/data/labeling_rules.md.

Endpoints (see src/classifier/README.md):
    GET  /health     is the service up? Also reports the model and rules version.
    POST /classify   label one email in its thread: label, needs_response, reason

Settings (environment variables):
    GOOGLE_CLOUD_PROJECT    GCP project for Vertex AI (required to classify)
    GOOGLE_CLOUD_LOCATION   Vertex AI location, default "global"
    GEMINI_MODEL            default "gemini-3.8-flash"
    GEMINI_THINKING_BUDGET  max thinking tokens per email, default 128 (the baseline
                            showed the same accuracy as the default for ~1/3 less cost and time)
    RULES_PATH              labeling rules file, default docs/data/labeling_rules.md
                            (the Docker image sets /app/labeling_rules.md; see Dockerfile)
    PORT                    only read by the Docker image's start command (Cloud Run sets 8080)

Logs are structured JSON for Cloud Logging (logs.py). At startup the service logs the
rules version and the sha256 of the rules file, so you can check which rules a
deployment uses.

Privacy: email text is sent to Gemini in our own GCP project and is never
logged or saved here. Logs hold message ids, labels, timing and token counts only,
never email text, subjects, addresses or Gemini's reason.

Run from src/classifier with:
    uv run uvicorn main:app --port 8002 --reload
"""

import hashlib
import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import logs
import prompt
from gemini import GeminiError, GeminiLabeler

logs.setup()
log = logging.getLogger("classifier")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
# Gemini 3.x Flash models are served on the global endpoint for our project
# (us-central1 returned 404 when checked on 2026-10-29).
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "128"))
RULES_PATH = Path(os.environ.get("RULES_PATH", prompt.RULES_PATH))

# Read the rules once at startup. A missing or malformed file stops the service:
# labeling without the rules would mean guessing.
RULES_TEXT, RULES_VERSION = prompt.load_rules(RULES_PATH)
# Compare with `shasum -a 256 docs/data/labeling_rules.md` to check a deployment's rules.
RULES_SHA256 = hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()
SYSTEM_PROMPT = prompt.system_prompt(RULES_TEXT)

log.info(
    "classifier starting: model=%s rules_version=%s", MODEL, RULES_VERSION,
    extra={"fields": {"event": "startup", "model": MODEL, "project": PROJECT, "location": LOCATION,
                      "thinking_budget": THINKING_BUDGET, "rules_version": RULES_VERSION,
                      "rules_sha256": RULES_SHA256, "rules_path": str(RULES_PATH)}},
)

app = FastAPI(title="Fixture classifier")
labeler = GeminiLabeler(MODEL, PROJECT, LOCATION, THINKING_BUDGET)


def get_labeler() -> GeminiLabeler:
    """FastAPI injects this into /classify. Tests override it with a fake."""
    return labeler


class ThreadMessage(BaseModel):
    # "from" is a Python keyword, so the field is from_ and accepts "from" in JSON.
    from_: str = Field(default="", alias="from")
    to: str = ""  # optional: helps with group and mailing-list rules (E3, E4, NR9)
    date: str = ""
    subject: str = ""
    body: str = ""
    from_user: bool = False  # optional: sent by the mailbox owner (NR1)

    def as_dict(self) -> dict:
        return {"from": self.from_, "to": self.to, "date": self.date, "subject": self.subject,
                "body": self.body, "from_user": self.from_user}


class ClassifyRequest(BaseModel):
    thread: list[ThreadMessage] = Field(min_length=1, max_length=100)
    target_index: int = Field(ge=0)
    message_id: str = Field(default="", max_length=200)  # optional, only used in logs

    @model_validator(mode="after")
    def target_in_thread(self):
        if self.target_index >= len(self.thread):
            raise ValueError("target_index is outside the thread")
        return self


class ClassifyResponse(BaseModel):
    label: str
    needs_response: bool
    reason: str
    model: str
    rules_version: str
    latency_ms: int


@app.get("/health")
def health():
    """Doesn't call Gemini, so it's fast and free. The web app reads rules_version
    from here to decide which cached labels are out of date."""
    return {"status": "ok", "model": MODEL, "rules_version": RULES_VERSION}


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest, labeler: GeminiLabeler = Depends(get_labeler)):
    """Label thread[target_index]. On any failure: an error response, never a guessed label."""
    thread = [m.as_dict() for m in request.thread]
    # Fields on every classify log line (one per request). Never email text or the reason.
    fields = {"event": "classify", "message_id": request.message_id or None, "thread_length": len(thread),
              "target_index": request.target_index, "model": MODEL, "rules_version": RULES_VERSION}
    start = time.perf_counter()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - start) * 1000)

    try:
        answer = labeler.label(SYSTEM_PROMPT, prompt.user_prompt(thread, request.target_index))
    except GeminiError as error:
        log.error(
            "classify failed: %s (%s)", error.kind, error,
            extra={"fields": {**fields, "outcome": "error", "error_type": error.kind, "status": error.status,
                              "gemini_code": error.code, "latency_ms": elapsed_ms()}},
        )
        raise HTTPException(status_code=error.status, detail=f"classification failed: {error}")
    except Exception as error:
        # A bug, not a Gemini problem. Count it as a failed request and log the stack
        # trace (logs.py keeps the exception type but drops its message).
        log.error(
            "classify failed: unexpected %s", type(error).__name__, exc_info=True,
            extra={"fields": {**fields, "outcome": "error", "error_type": type(error).__name__, "status": 500,
                              "latency_ms": elapsed_ms()}},
        )
        raise HTTPException(status_code=500, detail="classification failed: internal error")
    latency_ms = elapsed_ms()

    # NR1 is a hard rule, so enforce it here rather than trust the model.
    needs_response = answer["needs_response"] and not thread[request.target_index]["from_user"]

    usage = answer.get("usage", {})
    log.info(
        "classified: label=%s needs_response=%s latency_ms=%d", answer["label"], needs_response, latency_ms,
        extra={"fields": {**fields, "outcome": "ok", "status": 200, "label": answer["label"],
                          "needs_response": needs_response, "latency_ms": latency_ms,
                          "attempts": usage.get("attempts"), "input_tokens": usage.get("input_tokens"),
                          "output_tokens": usage.get("output_tokens"),
                          "thinking_tokens": usage.get("thinking_tokens")}},
    )
    return ClassifyResponse(
        label=answer["label"],
        needs_response=needs_response,
        reason=answer["reason"],
        model=MODEL,
        rules_version=RULES_VERSION,
        latency_ms=latency_ms,
    )
