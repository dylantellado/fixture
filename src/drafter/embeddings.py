"""Text embeddings from Vertex AI (gemini-embedding-001), for ranking past emails.

The same model and task types as src/rag and src/api (RETRIEVAL_DOCUMENT for the
past emails, RETRIEVAL_QUERY for the current thread), so a persistent per-user
index built by rag could replace this later without changing how relevance is
measured. A smaller copy of their embeddings.py: no Chroma, and texts are cut
to a safe length here (auto_truncate is on) because ranking, unlike indexing,
doesn't need every word.

PRIVACY: the texts are email text. They go to Vertex AI in our own GCP project
and are never logged.
"""

import logging
import random
import time

import httpx
from google import genai
from google.genai import errors, types

log = logging.getLogger("drafter")

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"
BATCH_MAX_TEXTS = 100
BATCH_MAX_CHARS = 20_000
TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
CALL_TIMEOUT_MS = 30_000


class EmbeddingError(Exception):
    """Vertex AI couldn't embed the texts. The message says why (never the texts)."""


def batches(texts: list[str]) -> list[tuple[int, int]]:
    """(start, end) ranges of texts that each fit in one request."""
    ranges, start = [], 0
    while start < len(texts):
        end, chars = start + 1, len(texts[start])
        while end < len(texts) and end - start < BATCH_MAX_TEXTS and chars + len(texts[end]) <= BATCH_MAX_CHARS:
            chars += len(texts[end])
            end += 1
        ranges.append((start, end))
        start = end
    return ranges


class VertexEmbedder:
    def __init__(self, model: str, project: str | None, location: str, client=None, sleep=time.sleep):
        self.model = model
        self.project = project
        self.location = location
        self._client = client  # tests pass a fake
        self._sleep = sleep

    def client(self):
        if self._client is None:
            if not self.project:
                raise EmbeddingError("GOOGLE_CLOUD_PROJECT is not set")
            try:
                self._client = genai.Client(vertexai=True, project=self.project, location=self.location,
                                            http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS))
            except Exception as error:
                raise EmbeddingError(f"can't create the Vertex AI client ({type(error).__name__})") from error
        return self._client

    def _call(self, batch: list[str], config):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self.client().models.embed_content(model=self.model, contents=batch, config=config)
            except EmbeddingError:
                raise
            except Exception as error:
                transient = (isinstance(error, errors.APIError) and error.code in TRANSIENT_CODES) or isinstance(
                    error, (httpx.TransportError, ConnectionError, TimeoutError))
                if attempt == MAX_ATTEMPTS or not transient:
                    code = getattr(error, "code", None)
                    raise EmbeddingError(f"Vertex AI embedding failed ({code or type(error).__name__})") from error
                self._sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))

    def embed(self, texts: list[str], task_type: str) -> tuple[list[list[float]], int]:
        """Embed texts in order. Returns (vectors, total tokens). Raises EmbeddingError."""
        config = types.EmbedContentConfig(task_type=task_type, auto_truncate=True)
        vectors, tokens = [], 0
        for start, end in batches(texts):
            response = self._call(texts[start:end], config)
            embeddings = response.embeddings or []
            if len(embeddings) != end - start:
                raise EmbeddingError(f"{self.model} returned {len(embeddings)} embeddings for {end - start} texts")
            for embedding in embeddings:
                vectors.append(list(embedding.values))
                stats = embedding.statistics
                tokens += int(stats.token_count) if stats and stats.token_count is not None else 0
        return vectors, tokens
