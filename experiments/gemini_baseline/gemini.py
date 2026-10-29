"""Call Gemini on Vertex AI for one message, with retries on transient errors.

Uses application-default credentials (gcloud auth application-default login):
no API keys, no .env.
"""

import json
import random
import time

import httpx
from google import genai
from google.genai import errors, types

from prompt import LABELS, RESPONSE_SCHEMA

PROJECT = "fixture-ac215-96dhbm"
# Gemini 3.x Flash models are served only on the global endpoint for this project;
# us-central1 returns 404 for every Flash model (checked 2026-10-29).
LOCATION = "global"

# HTTP codes worth retrying: timeout, rate limit, server errors.
TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6
TIMEOUT_MS = 120_000


def make_client(project: str = PROJECT, location: str = LOCATION) -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=project,
        location=location,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )


def is_transient(error: Exception) -> bool:
    if isinstance(error, errors.APIError):
        return error.code in TRANSIENT_CODES
    return isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError))


def with_retries(call, max_attempts: int = MAX_ATTEMPTS, sleep=time.sleep):
    """Run `call()`; on a transient error wait 2, 4, 8, ... s (capped at 60, plus jitter) and retry.

    Returns (result, attempts). Re-raises a permanent error at once, and a
    transient one after `max_attempts` tries.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt
        except Exception as error:
            if attempt == max_attempts or not is_transient(error):
                raise
            sleep(min(60, 2**attempt) + random.uniform(0, 1))


def parse_answer(text: str) -> dict:
    """Check Gemini's JSON answer against the schema (in case the API ever lets a bad one through)."""
    answer = json.loads(text)
    if answer.get("label") not in LABELS:
        raise ValueError(f"label {answer.get('label')!r} is not one of the six labels")
    if not isinstance(answer.get("needs_response"), bool):
        raise ValueError(f"needs_response {answer.get('needs_response')!r} is not a bool")
    return {"label": answer["label"], "needs_response": answer["needs_response"], "reason": str(answer.get("reason", ""))}


def classify(client: genai.Client, model: str, system: str, user: str, thinking_budget: int | None = None) -> dict:
    """Label one message. Never raises: errors come back in the `error` field.

    `thinking_budget` caps the model's thinking tokens (None: the model's default).
    It is a soft cap: gemini-3.8-flash still thinks a little with a budget of 0.
    """
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget is not None else None,
    )

    def call():
        start = time.perf_counter()
        response = client.models.generate_content(model=model, contents=user, config=config)
        return response, time.perf_counter() - start

    result = {"pred_label": None, "pred_needs_response": None, "reason": "", "error": None}
    try:
        (response, latency), attempts = with_retries(call)
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        return result

    usage = response.usage_metadata
    result.update(
        attempts=attempts,
        latency_s=round(latency, 3),
        model_version=response.model_version,
        input_tokens=usage.prompt_token_count or 0,
        cached_input_tokens=usage.cached_content_token_count or 0,
        output_tokens=usage.candidates_token_count or 0,
        thinking_tokens=usage.thoughts_token_count or 0,
    )
    try:
        answer = parse_answer(response.text or "")
    except Exception as error:
        result["error"] = f"bad answer: {error}: {(response.text or '')[:200]!r}"
        return result
    result.update(pred_label=answer["label"], pred_needs_response=answer["needs_response"], reason=answer["reason"])
    return result
