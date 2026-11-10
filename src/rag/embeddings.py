"""Text embeddings from Vertex AI, used for both indexing (rag) and search (api).

KEEP IN SYNC: src/rag/embeddings.py and src/api/embeddings.py are identical
copies, because services don't import from each other. Change both together;
a test in each service fails if they differ.

Settings come from environment variables (build_embedding_function):
  EMBEDDING_MODEL       Vertex AI embedding model (default gemini-embedding-001)
  GOOGLE_CLOUD_PROJECT  our GCP project (default fixture-ac215-96dhbm)
  EMBEDDING_LOCATION    Vertex AI region (default us-central1)

Credentials: Google application-default credentials (run
`gcloud auth application-default login` once; Docker mounts ~/.config/gcloud
read-only). No API keys and nothing in .env.

Task types: documents are embedded with RETRIEVAL_DOCUMENT and searches with
RETRIEVAL_QUERY, which the model is trained to match against each other.

Failures are never hidden: if Vertex AI can't embed something (no
credentials, rate limits that outlast the retries, a text over the token
limit), EmbeddingError says so. There is no fallback to another model, which
would produce vectors that can't be compared with the stored ones.

PRIVACY: the texts sent here are email text. They go to Vertex AI in our own
GCP project and are never logged; logs may hold counts, timings and model ids.
"""

import logging
import os
import random
import time
from dataclasses import dataclass

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from google import genai
from google.genai import errors, types

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_PROJECT = "fixture-ac215-96dhbm"
DEFAULT_LOCATION = "us-central1"

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

# Longest input each model accepts, in tokens. We send auto_truncate=False, so
# Vertex AI rejects a longer text instead of silently cutting it; rag sizes
# chunks to stay under this.
TOKEN_LIMITS = {
    "gemini-embedding-001": 2048,
    "text-embedding-005": 2048,
    "text-multilingual-embedding-002": 2048,
}
DEFAULT_TOKEN_LIMIT = 2048

# One request holds at most this many texts and characters (Vertex AI caps a
# request at 250 texts and 20,000 tokens; characters are a safe stand-in).
BATCH_MAX_TEXTS = 100
BATCH_MAX_CHARS = 20_000

# Retries for rate limits (429), timeouts and temporary server errors:
# waits about 1, 2, 4, 8, 16 s (plus jitter) between tries.
TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6
CALL_TIMEOUT_MS = 60_000


class EmbeddingError(Exception):
    """Vertex AI couldn't embed the texts. The message says why (never the texts)."""


class EmbeddingModelMismatch(Exception):
    """A collection was built with a different embedding model than this service uses."""


@dataclass(frozen=True)
class EmbeddingSettings:
    model: str = DEFAULT_MODEL
    project: str = DEFAULT_PROJECT
    location: str = DEFAULT_LOCATION

    @classmethod
    def from_env(cls) -> "EmbeddingSettings":
        return cls(
            model=os.environ.get("EMBEDDING_MODEL") or DEFAULT_MODEL,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT,
            location=os.environ.get("EMBEDDING_LOCATION") or DEFAULT_LOCATION,
        )

    @property
    def token_limit(self) -> int:
        return TOKEN_LIMITS.get(self.model, DEFAULT_TOKEN_LIMIT)


def build_embedding_function(settings: EmbeddingSettings | None = None) -> "VertexEmbeddingFunction":
    """The embedding function for this service, from the environment settings."""
    return VertexEmbeddingFunction(settings or EmbeddingSettings.from_env())


def batches(texts: list[str], max_texts: int = BATCH_MAX_TEXTS, max_chars: int = BATCH_MAX_CHARS) -> list[tuple[int, int]]:
    """Split texts into (start, end) ranges that each fit in one request.

    A range always holds at least one text, even if that text alone is over
    max_chars (Vertex AI then decides whether it fits its token limit).
    """
    ranges = []
    start = 0
    while start < len(texts):
        end, chars = start + 1, len(texts[start])
        while end < len(texts) and end - start < max_texts and chars + len(texts[end]) <= max_chars:
            chars += len(texts[end])
            end += 1
        ranges.append((start, end))
        start = end
    return ranges


def is_transient(error: Exception) -> bool:
    """Worth retrying: rate limits, timeouts, temporary server errors, network hiccups."""
    if isinstance(error, errors.APIError):
        return error.code in TRANSIENT_CODES
    return isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError))


def with_retries(call, max_attempts: int = MAX_ATTEMPTS, sleep=time.sleep):
    """Run call(); on a transient error wait 1, 2, 4, ... s (plus jitter) and retry.

    A permanent error is re-raised at once, a transient one after max_attempts tries.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as error:
            if attempt == max_attempts or not is_transient(error):
                raise
            # Only the code: never anything that could contain email text.
            log.warning("Vertex AI embedding attempt %d failed (%s), retrying",
                        attempt, getattr(error, "code", type(error).__name__))
            sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))


def describe(error: Exception) -> str:
    """A safe, useful description of a failed call (no request text)."""
    if isinstance(error, errors.APIError):
        hint = {
            400: "a text may be over the model's token limit",
            401: "credentials were rejected; run `gcloud auth application-default login`",
            403: "no permission to use Vertex AI in this project",
            404: "the model isn't available in this project and location",
            429: "rate limited, and still limited after retrying",
        }.get(error.code, "temporary Vertex AI problem")
        return f"Vertex AI returned {error.code} {error.status or ''}".rstrip() + f" ({hint})"
    return f"{type(error).__name__} while calling Vertex AI"


class VertexEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embeds texts with a Vertex AI model through google-genai.

    Works as a Chroma embedding function (__call__ embeds documents,
    embed_query embeds searches), but rag and the api call it directly and
    give Chroma the vectors, so Chroma never embeds anything by itself.
    The Vertex AI client is created on first use, so a service can start
    (and answer /health) without credentials.
    """

    def __init__(self, settings: EmbeddingSettings | None = None, client=None, sleep=time.sleep):
        self.settings = settings or EmbeddingSettings()
        self._client = client  # tests pass a fake client
        self._sleep = sleep

    # --- Settings, recorded in each collection's metadata ---------------------

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def token_limit(self) -> int:
        return self.settings.token_limit

    def collection_metadata(self, dimension: int) -> dict:
        """What a collection must record about how it was embedded."""
        return {
            "embedding_model": self.model,
            "embedding_dimension": dimension,
            "embedding_task_document": TASK_DOCUMENT,
            "embedding_task_query": TASK_QUERY,
            "embedding_token_limit": self.token_limit,
        }

    # --- Calling Vertex AI ------------------------------------------------------

    def client(self):
        if self._client is None:
            try:
                self._client = genai.Client(
                    vertexai=True,
                    project=self.settings.project,
                    location=self.settings.location,
                    http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS),
                )
            except Exception as error:  # e.g. no application-default credentials
                raise EmbeddingError(
                    f"Can't create the Vertex AI client ({type(error).__name__}). "
                    "Run `gcloud auth application-default login` and check GOOGLE_CLOUD_PROJECT."
                ) from error
        return self._client

    def embed(self, texts: list[str], task_type: str) -> tuple[list[list[float]], list[int]]:
        """Embed texts in batches. Returns (vectors, token counts), in the order given.

        Raises EmbeddingError if any batch fails after retries.
        """
        vectors: list[list[float]] = []
        token_counts: list[int] = []
        config = types.EmbedContentConfig(task_type=task_type, auto_truncate=False)
        for start, end in batches(texts, BATCH_MAX_TEXTS, BATCH_MAX_CHARS):
            batch = texts[start:end]
            try:
                response = with_retries(
                    lambda: self.client().models.embed_content(model=self.model, contents=batch, config=config),
                    sleep=self._sleep,
                )
            except EmbeddingError:
                raise
            except Exception as error:
                raise EmbeddingError(f"Couldn't embed {len(batch)} text(s) with {self.model}: {describe(error)}") from error
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                # Some models merge a list into one vector; never accept that silently.
                raise EmbeddingError(f"{self.model} returned {len(embeddings)} embeddings for {len(batch)} texts")
            for embedding in embeddings:
                vectors.append(list(embedding.values))
                stats = embedding.statistics
                token_counts.append(int(stats.token_count) if stats and stats.token_count is not None else 0)
        return vectors, token_counts

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], list[int]]:
        """Embed texts to store (RETRIEVAL_DOCUMENT). Returns (vectors, token counts)."""
        return self.embed(texts, TASK_DOCUMENT)

    # --- Chroma's embedding function interface ---------------------------------------

    def __call__(self, input: Documents) -> Embeddings:
        return self.embed(list(input), TASK_DOCUMENT)[0]

    def embed_query(self, input: Documents) -> Embeddings:
        return self.embed(list(input), TASK_QUERY)[0]

    @staticmethod
    def name() -> str:
        return "fixture_vertex_ai"

    def get_config(self) -> dict:
        return {"model": self.settings.model, "project": self.settings.project, "location": self.settings.location}

    @staticmethod
    def build_from_config(config: dict) -> "VertexEmbeddingFunction":
        return VertexEmbeddingFunction(EmbeddingSettings(**config))


def check_collection_model(collection_name: str, metadata: dict | None, model: str) -> None:
    """Refuse a collection built with a different embedding model.

    Vectors from different models can't be compared, so searching such a
    collection would return nonsense. Raises EmbeddingModelMismatch.
    """
    built_with = (metadata or {}).get("embedding_model", "")
    if built_with != model:
        raise EmbeddingModelMismatch(
            f"Collection {collection_name} was built with embedding model "
            f"{built_with or '(unknown)'!r}, but this service uses {model!r}. "
            "Rerun rag to rebuild the index with the current model."
        )
