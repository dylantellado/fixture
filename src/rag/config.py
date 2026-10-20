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


# --- Chunking ---
# Bodies longer than this many characters are split into overlapping pieces.
# MiniLM reads at most 256 tokens (~1,000 characters of English), and longer
# text is cut off, so pieces stay near that size.
CHUNK_SIZE = 1000
# Characters repeated between neighboring pieces, so a sentence that falls on
# a boundary still appears whole in at least one piece.
CHUNK_OVERLAP = 150

# --- Indexing ---
# Number of chunks sent to ChromaDB per upsert call.
BATCH_SIZE = 100
