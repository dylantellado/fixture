"""Settings for the rag service, all in one place.

Paths and the ChromaDB address come from environment variables, so the same
code runs on a laptop (defaults below) and in Docker (docker-compose.yml sets
DATA_DIR=/data, SAMPLES_DIR=/samples, CHROMA_HOST=chromadb, CHROMA_PORT=8000).
"""

import os
from pathlib import Path

from embeddings import EmbeddingSettings, VertexEmbeddingFunction, build_embedding_function

# Repo root, found from this file's location (src/rag/config.py -> repo root).
# In Docker this resolves to "/", which is fine because env vars override it.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# --- Inputs (see "Data contract" in the README) ---
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", REPO_ROOT / "samples"))

# --- ChromaDB server ---
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))  # host port on a laptop

# How long to wait for ChromaDB at startup: CONNECT_ATTEMPTS tries,
# CONNECT_DELAY_SECONDS apart.
CONNECT_ATTEMPTS = 10
CONNECT_DELAY_SECONDS = 2.0

# --- Collections ---
# Each user gets their own collection named messages_<user_id>.
COLLECTION_PREFIX = "messages_"
# Cosine distance: compares the direction of two embeddings, not their length,
# which is the usual choice for text embeddings.
# Chroma's default is l2, so this must be set explicitly when creating a collection.
COLLECTION_CONFIGURATION = {"hnsw": {"space": "cosine"}}

# --- Embeddings ---
# Vertex AI text embeddings (embeddings.py, identical in the api). The model,
# project and region come from EMBEDDING_MODEL, GOOGLE_CLOUD_PROJECT and
# EMBEDDING_LOCATION; the api must use the same model (it checks).
EMBEDDING_SETTINGS = EmbeddingSettings.from_env()
EMBEDDING_MODEL = EMBEDDING_SETTINGS.model
# The longest text the model accepts, in tokens. Longer texts are rejected
# (never silently cut), so chunks are sized to stay under it.
EMBEDDING_TOKEN_LIMIT = EMBEDDING_SETTINGS.token_limit


def get_embedding_function() -> VertexEmbeddingFunction:
    """The embedding function used for indexing (and by query.py / check_retrieval.py)."""
    return build_embedding_function(EMBEDDING_SETTINGS)


# Experiments only: RAG_THREAD_CONTEXT=0 indexes one plain chunk per message
# (no reply excerpt, no thread chunks), to measure what thread context adds.
THREAD_CONTEXT = os.environ.get("RAG_THREAD_CONTEXT", "1") != "0"


# --- Chunking ---
# Chunk sizes are in characters but must respect the model's token limit.
# English averages about 4 characters per token; dates, times and EMAIL_###
# placeholders use more tokens, so assume 3 to stay safely under the limit.
CHARS_PER_TOKEN = 3
# The longest a chunk (header, reply line and body piece, or a thread window)
# may be. Longer bodies are split into overlapping pieces; longer threads
# into overlapping windows.
CHUNK_MAX_CHARS = EMBEDDING_TOKEN_LIMIT * CHARS_PER_TOKEN
# Never cut a body into pieces smaller than this, even under a long header.
MIN_BODY_CHARS = 200
# Characters repeated between neighboring body pieces, so a sentence that falls
# on a boundary still appears whole in at least one piece.
CHUNK_OVERLAP = 150
# How much of the previous message a message chunk quotes ("Replying to ...").
REPLY_EXCERPT_CHARS = 200
# How much of each message a thread chunk shows (its first lines).
THREAD_LINE_CHARS = 300
# The longest a thread chunk (one window of a thread) may be.
THREAD_WINDOW_MAX_CHARS = int(os.environ.get("RAG_THREAD_WINDOW_MAX_CHARS", CHUNK_MAX_CHARS))
# Messages shared by neighboring windows of a long thread.
THREAD_WINDOW_OVERLAP = 1

# --- Indexing ---
# Number of chunks sent to ChromaDB per upsert call (embedding requests are
# batched separately, in embeddings.py).
BATCH_SIZE = 100
