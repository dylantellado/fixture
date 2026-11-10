"""Fixture drafter: draft a calendar-aware reply to one scheduling email.

Endpoints (see src/drafter/README.md):
    GET  /health   is the service up? Also reports the models and default rules version.
    POST /draft    draft a reply: thread, user, busy times, past emails in; checked draft out

The drafter never holds Google user credentials and never reads Gmail or
Calendar: the caller (the web app) sends everything in the request. It calls
only Vertex AI (Gemini and embeddings) and, when no classification is sent,
the classifier. It never sends email, creates drafts or changes a calendar.

Settings (environment variables):
    GOOGLE_CLOUD_PROJECT      GCP project for Vertex AI (required to draft)
    GOOGLE_CLOUD_LOCATION     Gemini location, default "global"
    GEMINI_MODEL              default "gemini-3.8-flash"
    GEMINI_THINKING_BUDGET    max thinking tokens per draft, default 512
    EMBEDDING_MODEL           default "gemini-embedding-001"
    EMBEDDING_LOCATION        default "us-central1"
    CLASSIFIER_URL            default http://localhost:8002 (https = Cloud Run, sent with an ID token)
    CLASSIFIER_AUTH           auto (default), id_token or none
    PORT                      only read by the Docker image's start command (Cloud Run sets 8080)

Privacy: email text goes to Vertex AI in our own GCP project and is never
logged or saved. Logs hold counts, labels, check names, tokens and timing only.

Run from src/drafter with:
    GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8003 --reload
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from pydantic import ValidationError

import classifier_client
import logs
import pipeline
from embeddings import VertexEmbedder
from gemini import GeminiClient
from rules import DEFAULTS, NoStoredRules
from schemas import DraftRequest, DraftResponse

logs.setup()
log = logging.getLogger("drafter")

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "512"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_LOCATION = os.environ.get("EMBEDDING_LOCATION", "us-central1")

classifier = classifier_client.from_env()
deps = pipeline.Deps(
    gemini=GeminiClient(MODEL, PROJECT, LOCATION, THINKING_BUDGET),
    embedder=VertexEmbedder(EMBEDDING_MODEL, PROJECT, EMBEDDING_LOCATION),
    classifier=classifier,
    model=MODEL,
    embedding_model=EMBEDDING_MODEL,
    rules_store=NoStoredRules(),  # SWAP LATER: per-user settings (see rules.py)
)

log.info("drafter starting: model=%s rules_version=%s", MODEL, DEFAULTS["version"],
         extra={"fields": {"event": "startup", "model": MODEL, "project": PROJECT, "location": LOCATION,
                           "thinking_budget": THINKING_BUDGET, "embedding_model": EMBEDDING_MODEL,
                           "rules_version": DEFAULTS["version"],
                           "classifier_url_kind": "cloud_run" if classifier.tokens else "plain_http"}})

app = FastAPI(title="Fixture drafter")


def get_deps() -> pipeline.Deps:
    """FastAPI injects this into /draft. Tests override it with fakes."""
    return deps


@app.get("/health")
def health():
    """Doesn't call any model, so it's fast and free."""
    return {"status": "ok", "model": MODEL, "embedding_model": EMBEDDING_MODEL, "rules_version": DEFAULTS["version"]}


@app.post("/draft", response_model=DraftResponse)
def draft_reply(request: DraftRequest, deps: pipeline.Deps = Depends(get_deps)):
    """Draft a reply to thread[target_index]. Valid requests always get 200 with a status;
    see the README for what each status means. Invalid rule overrides get 422."""
    try:
        return pipeline.run(request, deps)
    except ValidationError as error:
        # Only the field names: the values could be anything the caller sent.
        where = sorted({".".join(str(p) for p in e["loc"]) or "rules" for e in error.errors()})
        raise HTTPException(status_code=422, detail=f"invalid rules: {', '.join(where)}")
    except Exception as error:
        log.error("draft failed: unexpected %s", type(error).__name__, exc_info=True,
                  extra={"fields": {"event": "draft", "status": "error", "error_type": type(error).__name__,
                                    "message_id": request.message_id or None}})
        raise HTTPException(status_code=500, detail="draft failed: internal error")
