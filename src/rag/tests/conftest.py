"""Shared test helpers: sample paths, a fake embedding function, an in-memory Chroma."""

import hashlib
import json
import math

import chromadb
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings

from helpers import SAMPLES_DIR


class FakeEmbeddingFunction(EmbeddingFunction[Documents]):
    """A tiny, deterministic stand-in for MiniLM so tests run fast and offline.

    Each word is hashed into one of 64 slots and counted (a "bag of words"),
    then the vector is scaled to length 1. Texts that share words point in
    similar directions, which is enough to test search behavior.
    """

    DIMENSIONS = 64

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = [0.0] * self.DIMENSIONS
            for word in text.lower().replace("\n", " ").split():
                word = word.strip(".,!?:;()<>\"'")
                if word:
                    # md5, not hash(), because hash() changes between Python runs.
                    slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.DIMENSIONS
                    vector[slot] += 1.0
            length = math.sqrt(sum(x * x for x in vector)) or 1.0
            vectors.append([x / length for x in vector])
        return vectors

    # Chroma 1.x stores the embedding function's name and config with the collection.
    @staticmethod
    def name() -> str:
        return "fake_bag_of_words"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "FakeEmbeddingFunction":
        return FakeEmbeddingFunction()


@pytest.fixture
def fake_ef():
    return FakeEmbeddingFunction()


@pytest.fixture
def chroma_client():
    """An in-memory Chroma client, emptied before each test.

    Ephemeral clients in one process share the same store, so reset() keeps
    tests from seeing each other's collections.
    """
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))
    client.reset()
    yield client
    client.reset()


@pytest.fixture
def sample_messages():
    with open(SAMPLES_DIR / "messages_sample.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
def sample_users():
    return json.loads((SAMPLES_DIR / "users.json").read_text(encoding="utf-8"))


@pytest.fixture
def data_dir(tmp_path):
    """An empty DATA_DIR (no processed messages), so the job falls back to samples."""
    path = tmp_path / "data"
    path.mkdir()
    return path
