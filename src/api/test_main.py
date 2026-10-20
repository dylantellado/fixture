"""Tests for the API, using FastAPI's in-process test client.

No ChromaDB server is needed: each test swaps in its own MessageStore through
app.dependency_overrides, backed by a fake client or Chroma's in-memory client.
"""

import socket

import chromadb
import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.errors import NotFoundError
from fastapi.testclient import TestClient

import chroma_store
from chroma_store import MessageStore
from main import app, get_store

client = TestClient(app)


def use_store(store: MessageStore) -> None:
    """Make the API use this store for the rest of the test."""
    app.dependency_overrides[get_store] = lambda: store


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


# --- Fakes -----------------------------------------------------------------


class FakeCollection:
    """Stands in for a Chroma collection. query() returns canned results,
    deliberately NOT in best-first order, and remembers what it was asked."""

    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata
        self.last_query = None

    def query(self, **kwargs):
        self.last_query = kwargs
        return {
            "documents": [["far", "close", "middle"]],
            "metadatas": [[{"message_id": "a"}, {"message_id": "b"}, {"message_id": "c"}]],
            "distances": [[0.9, 0.12345, 0.5]],
        }


class FakeClient:
    """Stands in for a Chroma client holding a few named collections."""

    def __init__(self, collections):
        self.collections = {c.name: c for c in collections}
        self.opened = []  # every collection name get_collection was asked for

    def list_collections(self):
        return list(self.collections.values())

    def get_collection(self, name, embedding_function=None):
        self.opened.append(name)
        if name not in self.collections:
            raise NotFoundError(f"Collection {name} does not exist.")
        return self.collections[name]


class KeywordEmbedding(EmbeddingFunction):
    """A tiny, deterministic embedding for tests: one dimension per keyword.

    Avoids downloading the real model; it only needs to make related texts
    land close together.
    """

    KEYWORDS = ["interview", "coffee", "reschedule", "dentist"]

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        # The trailing 1.0 keeps every vector non-zero (cosine needs a length).
        return [[float(word in text.lower()) for word in self.KEYWORDS] + [1.0] for text in input]

    @staticmethod
    def name() -> str:
        return "keyword-test"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config):
        return KeywordEmbedding()


def fake_store(*collections) -> tuple[MessageStore, FakeClient]:
    fake = FakeClient(collections)
    return MessageStore(client_factory=lambda: fake, embedding_function=KeywordEmbedding()), fake


# --- Health ------------------------------------------------------------------


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": "user_01", "query": "   "},  # blank query
        {"user_id": "user_01", "query": ""},  # empty query
        {"user_id": "user_01", "query": "hi", "k": 0},  # k too small
        {"user_id": "user_01", "query": "hi", "k": 21},  # k too large
        {"user_id": "user_01", "query": "hi", "label": "urgent"},  # not a contract label
        {"user_id": "user_01"},  # query missing
    ],
)
def test_invalid_requests_return_422(body):
    store, _ = fake_store(FakeCollection("messages_user_01"))
    use_store(store)
    assert client.post("/search", json=body).status_code == 422


@pytest.mark.parametrize("user_id", ["user_99", "User_01", "user-01", "../user_01", "", "user_01 user_02"])
def test_unknown_or_malformed_user_returns_400(user_id):
    store, fake = fake_store(FakeCollection("messages_user_01"))
    use_store(store)
    response = client.post("/search", json={"user_id": user_id, "query": "interview"})
    assert response.status_code == 400
    assert response.json() == {"detail": "unknown user"}
    # A malformed id is rejected before any collection is opened.
    if not chroma_store.USER_ID_PATTERN.match(user_id):
        assert fake.opened == []


# --- Search results ----------------------------------------------------------------


def test_search_response_shape_and_best_first_order():
    collection = FakeCollection("messages_user_01")
    store, fake = fake_store(collection)
    use_store(store)

    response = client.post("/search", json={"user_id": "user_01", "query": "interview", "k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user_01"
    assert body["query"] == "interview"
    # score = 1 - distance, rounded to 3 places, best first.
    assert body["results"] == [
        {"text": "close", "score": 0.877, "metadata": {"message_id": "b"}},
        {"text": "middle", "score": 0.5, "metadata": {"message_id": "c"}},
        {"text": "far", "score": 0.1, "metadata": {"message_id": "a"}},
    ]
    # Only the requested user's collection was opened, and k was passed through.
    assert fake.opened == ["messages_user_01"]
    assert collection.last_query["n_results"] == 3
    assert collection.last_query["where"] is None


def test_label_filter_is_passed_to_chroma():
    collection = FakeCollection("messages_user_01")
    store, _ = fake_store(collection)
    use_store(store)

    client.post("/search", json={"user_id": "user_01", "query": "x", "label": "reschedule"})

    assert collection.last_query["where"] == {"label": "reschedule"}


def test_default_k_is_5():
    collection = FakeCollection("messages_user_01")
    store, _ = fake_store(collection)
    use_store(store)

    client.post("/search", json={"user_id": "user_01", "query": "x"})

    assert collection.last_query["n_results"] == 5


# --- Users ---------------------------------------------------------------------


def test_users_lists_only_message_collections():
    store, _ = fake_store(
        FakeCollection("messages_user_02", {"user_name": "Marcus Bell", "indexed_at": "2026-10-20T01:20:48+00:00"}),
        FakeCollection("messages_user_01", {"user_name": "Priya Shah", "indexed_at": "2026-10-20T01:20:48+00:00"}),
        FakeCollection("something_else", {"user_name": "Not a user"}),
        FakeCollection("messages_no_metadata", None),
    )
    use_store(store)

    response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == [
        {"user_id": "no_metadata", "name": "", "indexed_at": ""},
        {"user_id": "user_01", "name": "Priya Shah", "indexed_at": "2026-10-20T01:20:48+00:00"},
        {"user_id": "user_02", "name": "Marcus Bell", "indexed_at": "2026-10-20T01:20:48+00:00"},
    ]


# --- ChromaDB down ----------------------------------------------------------------


def unused_port() -> int:
    """A local port with nothing listening on it."""
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def test_chroma_down_returns_503(monkeypatch):
    # The real connection code, pointed at a port where nothing is running.
    monkeypatch.setattr(chroma_store, "CHROMA_PORT", unused_port())
    use_store(MessageStore(embedding_function=KeywordEmbedding(), attempts=2, delay_seconds=0))

    for response in [
        client.post("/search", json={"user_id": "user_01", "query": "interview"}),
        client.get("/users"),
    ]:
        assert response.status_code == 503
        assert "ChromaDB" in response.json()["detail"]

    # The API itself stays up.
    assert client.get("/health").status_code == 200


# --- Isolation, with a real (in-memory) ChromaDB -------------------------------------------


@pytest.fixture
def two_user_chroma():
    """An in-memory ChromaDB with two users who both email the same contact,
    Jordan Lee, about an interview."""
    chroma = chromadb.EphemeralClient()
    # In-memory clients share data within one process, so start clean.
    for c in chroma.list_collections():
        chroma.delete_collection(c.name)

    mailboxes = {
        "user_01": ["Jordan Lee: interview Tuesday at 2:30 for Priya", "Dentist reminder for Priya"],
        "user_02": ["Jordan Lee: interview Friday at 10:00 for Marcus", "Coffee chat with Marcus's mentor"],
    }
    for user_id, texts in mailboxes.items():
        collection = chroma.create_collection(
            f"messages_{user_id}",
            embedding_function=KeywordEmbedding(),
            configuration={"hnsw": {"space": "cosine"}},  # same distance as rag
            metadata={"user_name": user_id, "indexed_at": "2026-10-20T00:00:00+00:00"},
        )
        collection.add(
            ids=[f"{user_id}-{i}" for i in range(len(texts))],
            documents=texts,
            metadatas=[{"user_id": user_id, "sender_name": "Jordan Lee", "label": "none"} for _ in texts],
        )
    yield chroma
    for c in chroma.list_collections():
        chroma.delete_collection(c.name)


def test_search_never_returns_another_users_messages(two_user_chroma):
    use_store(MessageStore(client_factory=lambda: two_user_chroma, embedding_function=KeywordEmbedding()))

    first_names = {"user_01": "Priya", "user_02": "Marcus"}
    for user_id, first_name in first_names.items():
        # Ask for more results than exist, about the contact both users share.
        response = client.post(
            "/search", json={"user_id": user_id, "query": "Jordan Lee interview", "k": 20}
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2  # only this user's two messages, nothing else
        assert all(r["metadata"]["user_id"] == user_id for r in results)
        assert all(first_name in r["text"] for r in results)
        # The shared-contact interview message is still the top hit.
        assert "interview" in results[0]["text"]
