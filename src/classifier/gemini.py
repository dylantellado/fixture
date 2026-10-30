"""Call Gemini on Vertex AI to label one email, retrying on rate limits.

Uses Google application-default credentials (`gcloud auth application-default
login`; Docker mounts ~/.config/gcloud). No API keys.

GeminiLabeler.label() either returns a checked answer or raises GeminiError.
It never guesses a label.
"""

import json
import logging
import random
import time

import httpx
from google import genai
from google.genai import errors, types

from prompt import LABELS, RESPONSE_SCHEMA

log = logging.getLogger("classifier")

# HTTP codes worth retrying: rate limit (429), timeout, and temporary server errors.
TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4  # waits about 1, 2, 4 s between tries, so the whole call stays well under a minute
CALL_TIMEOUT_MS = 30_000  # per Gemini call


class GeminiError(Exception):
    """Gemini couldn't give a valid answer. `status` is the HTTP code main.py returns."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def is_transient(error: Exception) -> bool:
    if isinstance(error, errors.APIError):
        return error.code in TRANSIENT_CODES
    return isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError))


def with_retries(call, max_attempts: int = MAX_ATTEMPTS, sleep=time.sleep):
    """Run call(); on a transient error wait 1, 2, 4, ... s (plus jitter) and retry.

    Returns (result, attempts). A permanent error is re-raised at once, a
    transient one after max_attempts tries.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt
        except Exception as error:
            if attempt == max_attempts or not is_transient(error):
                raise
            # Log the code only: API error messages are safe, but keep logs minimal.
            log.warning("gemini attempt %d failed (%s), retrying", attempt, getattr(error, "code", type(error).__name__))
            sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))


def parse_answer(text: str) -> dict:
    """Check Gemini's JSON answer (the schema should guarantee it, but never trust it blindly)."""
    answer = json.loads(text)
    if not isinstance(answer, dict):
        raise ValueError("answer is not a JSON object")
    if answer.get("label") not in LABELS:
        raise ValueError("label is not one of the six labels")
    if not isinstance(answer.get("needs_response"), bool):
        raise ValueError("needs_response is not true or false")
    reason = " ".join(str(answer.get("reason", "")).split())  # one line
    return {"label": answer["label"], "needs_response": answer["needs_response"], "reason": reason}


class GeminiLabeler:
    def __init__(self, model: str, project: str | None, location: str, thinking_budget: int | None = None):
        self.model = model
        self.thinking_budget = thinking_budget  # max thinking tokens per call; None = the model's default
        self.project = project
        self.location = location
        self._client = None  # created on first use, so the service starts without credentials

    def client(self) -> genai.Client:
        if self._client is None:
            if not self.project:
                raise GeminiError("GOOGLE_CLOUD_PROJECT is not set")
            try:
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project,
                    location=self.location,
                    http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS),
                )
            except Exception as error:  # e.g. no application-default credentials
                raise GeminiError(f"can't create the Vertex AI client: {type(error).__name__}") from error
        return self._client

    def label(self, system: str, user: str) -> dict:
        """Label one email. Returns {label, needs_response, reason, usage} or raises GeminiError."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=self.thinking_budget) if self.thinking_budget is not None else None
            ),
        )
        client = self.client()
        try:
            response, attempts = with_retries(
                lambda: client.models.generate_content(model=self.model, contents=user, config=config)
            )
        except errors.APIError as error:
            if error.code == 429:
                raise GeminiError("Gemini is rate limited; try again shortly") from error
            raise GeminiError(f"Gemini returned an error ({error.code})", 502 if error.code < 500 else 503) from error
        except Exception as error:
            raise GeminiError(f"couldn't reach Gemini ({type(error).__name__})") from error

        try:
            answer = parse_answer(response.text or "")
        except (ValueError, TypeError) as error:  # json.JSONDecodeError is a ValueError
            raise GeminiError(f"Gemini's answer was not valid: {error}", 502) from error

        usage = response.usage_metadata
        answer["usage"] = {
            "attempts": attempts,
            "input_tokens": (usage and usage.prompt_token_count) or 0,
            "output_tokens": (usage and usage.candidates_token_count) or 0,
            "thinking_tokens": (usage and usage.thoughts_token_count) or 0,
        }
        return answer
