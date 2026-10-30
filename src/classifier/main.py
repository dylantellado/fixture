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

Privacy: email text is sent to Gemini in our own GCP project and is never
logged or saved here. Logs hold message ids, labels, timing and token counts only.

Run from src/classifier with:
    uv run uvicorn main:app --port 8002 --reload
"""

import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import prompt
from gemini import GeminiError, GeminiLabeler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
SYSTEM_PROMPT = prompt.system_prompt(RULES_TEXT)

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
    start = time.perf_counter()
    try:
        answer = labeler.label(SYSTEM_PROMPT, prompt.user_prompt(thread, request.target_index))
    except GeminiError as error:
        log.warning("classify failed message_id=%s error=%s", request.message_id or "-", error)
        raise HTTPException(status_code=error.status, detail=f"classification failed: {error}")
    latency_ms = round((time.perf_counter() - start) * 1000)

    # NR1 is a hard rule, so enforce it here rather than trust the model.
    needs_response = answer["needs_response"] and not thread[request.target_index]["from_user"]

    usage = answer.get("usage", {})
    log.info(
        "classified message_id=%s label=%s needs_response=%s latency_ms=%d attempts=%s "
        "input_tokens=%s output_tokens=%s thinking_tokens=%s",
        request.message_id or "-", answer["label"], needs_response, latency_ms, usage.get("attempts"),
        usage.get("input_tokens"), usage.get("output_tokens"), usage.get("thinking_tokens"),
    )
    return ClassifyResponse(
        label=answer["label"],
        needs_response=needs_response,
        reason=answer["reason"],
        model=MODEL,
        rules_version=RULES_VERSION,
        latency_ms=latency_ms,
    )
