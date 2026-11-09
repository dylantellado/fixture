"""Settings for the rag service, all in one place.

Paths and the ChromaDB address come from environment variables, so the same
code runs on a laptop (defaults below) and in Docker (docker-compose.yml sets
DATA_DIR=/data, SAMPLES_DIR=/samples, CHROMA_HOST=chromadb, CHROMA_PORT=8000).
"""

import os
from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

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
# which is the usual choice for sentence embeddings like MiniLM.
# Chroma's default is l2, so this must be set explicitly when creating a collection.
COLLECTION_CONFIGURATION = {"hnsw": {"space": "cosine"}}

# --- Embeddings ---
# The model behind Chroma's built-in default embedding function. It runs
# locally with ONNX (no API key) and downloads once to ~/.cache/chroma.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def get_embedding_function():
    """Return the embedding function used for both indexing and search.

    The api must use exactly this, chromadb's DefaultEmbeddingFunction
    (all-MiniLM-L6-v2), or its query vectors won't match the stored ones.
    Changing the model means changing it here and in the api together.
    """
    return DefaultEmbeddingFunction()


# MiniLM reads at most this many tokens (word pieces, counting the two special
# tokens it adds) and silently ignores the rest.
EMBEDDING_TOKEN_LIMIT = 256


def count_tokens(texts: list[str]) -> list[int]:
    """How many MiniLM tokens each text has, without cutting at the limit.

    Used to record how many chunks are longer than EMBEDDING_TOKEN_LIMIT.
    Loads the tokenizer that ships with the model (downloaded on first use).
    """
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    from tokenizers import Tokenizer

    model = ONNXMiniLM_L6_V2()
    model._download_model_if_not_exists()
    tokenizer = Tokenizer.from_file(str(model.DOWNLOAD_PATH / model.EXTRACTED_FOLDER_NAME / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return [len(encoding.ids) for encoding in tokenizer.encode_batch(texts)]


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
# Messages shared by neighboring windows of a long thread.
THREAD_WINDOW_OVERLAP = 1

# --- Indexing ---
# Number of chunks sent to ChromaDB per upsert call.
BATCH_SIZE = 100
