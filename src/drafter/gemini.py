"""Call Gemini on Vertex AI for structured JSON, retrying on rate limits.

Same approach as src/classifier/gemini.py (services don't import from each
other): application-default credentials, the client created on first use,
retries with backoff on transient errors, and errors that say what kind of
failure it was without any request text.
"""

import json
import logging
import random
import time

import httpx
from google import genai
from google.genai import errors, types

log = logging.getLogger("drafter")

TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3  # waits about 1 and 2 s between tries; a draft may also be retried once by the checker
CALL_TIMEOUT_MS = 45_000


class GeminiError(Exception):
    """Gemini couldn't give a valid answer. kind is a short name for logs and the response:
    no_project, client_error, rate_limited, api_error, unreachable, invalid_answer."""

    def __init__(self, message: str, kind: str = "error", code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.code = code


def is_transient(error: Exception) -> bool:
    if isinstance(error, errors.APIError):
        return error.code in TRANSIENT_CODES
    return isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError))


def with_retries(call, max_attempts: int = MAX_ATTEMPTS, sleep=time.sleep):
    """Run call(); on a transient error wait 1, 2, ... s (plus jitter) and retry. Returns (result, attempts)."""
    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt
        except Exception as error:
            if attempt == max_attempts or not is_transient(error):
                raise
            code = getattr(error, "code", None)
            log.warning("gemini attempt %d failed (%s), retrying", attempt, code or type(error).__name__,
                        extra={"fields": {"event": "gemini_retry", "attempts": attempt, "gemini_code": code,
                                          "error_type": type(error).__name__}})
            sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))


class GeminiClient:
    """generate_json(system, user, schema, temperature) -> (answer dict, usage dict)."""

    def __init__(self, model: str, project: str | None, location: str, thinking_budget: int | None = None):
        self.model = model
        self.project = project
        self.location = location
        self.thinking_budget = thinking_budget
        self._client = None  # created on first use, so the service starts without credentials

    def client(self) -> genai.Client:
        if self._client is None:
            if not self.project:
                raise GeminiError("GOOGLE_CLOUD_PROJECT is not set", kind="no_project")
            try:
                self._client = genai.Client(vertexai=True, project=self.project, location=self.location,
                                            http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS))
            except Exception as error:  # e.g. no application-default credentials
                raise GeminiError(f"can't create the Vertex AI client: {type(error).__name__}",
                                  kind="client_error") from error
        return self._client

    def generate_json(self, system: str, user: str, schema: dict, temperature: float) -> tuple[dict, dict]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=(types.ThinkingConfig(thinking_budget=self.thinking_budget)
                             if self.thinking_budget is not None else None),
        )
        client = self.client()
        try:
            response, attempts = with_retries(
                lambda: client.models.generate_content(model=self.model, contents=user, config=config))
        except errors.APIError as error:
            if error.code == 429:
                raise GeminiError("Gemini is rate limited; try again shortly", kind="rate_limited", code=429) from error
            raise GeminiError(f"Gemini returned an error ({error.code})", kind="api_error", code=error.code) from error
        except Exception as error:
            raise GeminiError(f"couldn't reach Gemini ({type(error).__name__})", kind="unreachable") from error

        try:
            answer = json.loads(response.text or "")
            if not isinstance(answer, dict):
                raise ValueError("answer is not a JSON object")
        except (ValueError, TypeError) as error:
            raise GeminiError("Gemini's answer was not valid JSON", kind="invalid_answer") from error

        usage = response.usage_metadata
        return answer, {
            "attempts": attempts,
            "input_tokens": (usage and usage.prompt_token_count) or 0,
            "output_tokens": (usage and usage.candidates_token_count) or 0,
            "thinking_tokens": (usage and usage.thoughts_token_count) or 0,
        }
