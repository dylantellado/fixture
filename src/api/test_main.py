"""Tests for the API, using FastAPI's in-process test client.

No ChromaDB server is needed: each test swaps in its own MessageStore through
app.dependency_overrides, backed by a fake client or Chroma's in-memory client.
"""

import socket
from pathlib import Path

import chromadb
import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.errors import NotFoundError
from fastapi.testclient import TestClient

import chroma_store
from chroma_store import MessageStore
from embeddings import EmbeddingError, VertexEmbeddingFunction
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
    """Stands in for a Chroma collection in tests that only need its name and metadata."""

    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata


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

    Stands in for Vertex AI (no network in tests); it only needs to make
    related texts land close together. `queries` records every query embedded.
    """

    KEYWORDS = ["interview", "coffee", "reschedule", "dentist"]
    model = "keyword-test"

    def __init__(self):
        self.queries = []

    def embed_query(self, input):
        self.queries.extend(input)
        return self(input)

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


def add_mailbox(chroma, user_id, messages, model="keyword-test"):
    """Index a tiny mailbox the way rag does: one chunk per message
    (chunk_type "message") and one chunk per thread (chunk_type "thread"),
    with vectors computed up front and the model recorded in the metadata.

    messages: (message_id, thread_id, label, text) tuples.
    """
    embed = KeywordEmbedding()
    collection = chroma.create_collection(
        f"messages_{user_id}",
        embedding_function=None,  # like rag: Chroma never embeds by itself
        configuration={"hnsw": {"space": "cosine"}},  # same distance as rag
        metadata={"user_name": user_id, "indexed_at": "2026-10-20T00:00:00+00:00", "embedding_model": model},
    )
    threads = {}
    for mid, tid, _, text in messages:
        threads.setdefault(tid, []).append((mid, text))
    chunks = [
        (f"{mid}-0", text, {"chunk_type": "message", "message_id": mid, "thread_id": tid, "user_id": user_id, "label": label})
        for mid, tid, label, text in messages
    ] + [
        (f"thread-{tid}-0", " ".join(text for _, text in items),
         {"chunk_type": "thread", "thread_id": tid, "user_id": user_id, "message_ids": ",".join(mid for mid, _ in items)})
        for tid, items in threads.items()
    ]
    collection.add(
        ids=[c[0] for c in chunks],
        documents=[c[1] for c in chunks],
        embeddings=embed([c[1] for c in chunks]),
        metadatas=[c[2] for c in chunks],
    )
    return collection


@pytest.fixture
def chroma():
    """An empty in-memory ChromaDB (in-memory clients share data within one process)."""
    client = chromadb.EphemeralClient()
    for c in client.list_collections():
        client.delete_collection(c.name)
    yield client
    for c in client.list_collections():
        client.delete_collection(c.name)


def in_memory_store(chroma) -> MessageStore:
    return MessageStore(client_factory=lambda: chroma, embedding_function=KeywordEmbedding())


def test_search_response_shape_and_best_first_order(chroma):
    add_mailbox(chroma, "user_01", [
        ("m1", "t1", "new_request", "Interview next week?"),
        ("m2", "t2", "none", "Dentist reminder"),
        ("m3", "t3", "reschedule", "Can we reschedule the interview?"),
    ])
    use_store(in_memory_store(chroma))

    response = client.post("/search", json={"user_id": "user_01", "query": "reschedule my interview", "k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user_01"
    assert body["query"] == "reschedule my interview"
    results = body["results"]
    assert [set(r) for r in results] == [{"text", "score", "metadata"}] * 3
    assert results[0]["metadata"]["message_id"] == "m3"  # matches both keywords
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)  # best first
    assert all(round(s, 3) == s for s in scores)  # rounded to 3 places


def test_results_are_messages_never_threads(chroma):
    add_mailbox(chroma, "user_01", [
        ("m1", "t1", "proposed_times", "Interview options: Tuesday or Friday"),
        ("m2", "t1", "acceptance", "Friday works"),
    ])
    use_store(in_memory_store(chroma))

    results = client.post("/search", json={"user_id": "user_01", "query": "interview", "k": 20}).json()["results"]

    assert sorted(r["metadata"]["message_id"] for r in results) == ["m1", "m2"]  # each message once
    assert all(r["metadata"]["chunk_type"] == "message" for r in results)


def test_label_filter_limits_results(chroma):
    add_mailbox(chroma, "user_01", [
        ("m1", "t1", "new_request", "Interview next week?"),
        ("m2", "t1", "reschedule", "Can we reschedule the interview?"),
    ])
    use_store(in_memory_store(chroma))

    response = client.post("/search", json={"user_id": "user_01", "query": "interview", "label": "reschedule"})

    assert [r["metadata"]["message_id"] for r in response.json()["results"]] == ["m2"]


def test_default_k_is_5(chroma):
    add_mailbox(chroma, "user_01", [(f"m{i}", f"t{i}", "none", f"interview {i}") for i in range(8)])
    use_store(in_memory_store(chroma))

    response = client.post("/search", json={"user_id": "user_01", "query": "interview"})

    assert len(response.json()["results"]) == 5


def test_index_built_with_another_model_is_refused(chroma):
    add_mailbox(chroma, "user_01", [("m1", "t1", "none", "interview")], model="all-MiniLM-L6-v2")
    embedding = KeywordEmbedding()
    use_store(MessageStore(client_factory=lambda: chroma, embedding_function=embedding))

    response = client.post("/search", json={"user_id": "user_01", "query": "interview"})

    assert response.status_code == 503
    assert "all-MiniLM-L6-v2" in response.json()["detail"]
    assert "Rerun rag" in response.json()["detail"]
    assert embedding.queries == []  # refused before the query was sent anywhere


def test_vertex_failure_returns_503(chroma):
    add_mailbox(chroma, "user_01", [("m1", "t1", "none", "interview")])

    class Unavailable(KeywordEmbedding):
        def embed_query(self, input):
            raise EmbeddingError("Couldn't embed 1 text(s) with keyword-test: Vertex AI returned 429")

    use_store(MessageStore(client_factory=lambda: chroma, embedding_function=Unavailable()))

    response = client.post("/search", json={"user_id": "user_01", "query": "interview"})

    assert response.status_code == 503
    assert "429" in response.json()["detail"]
    assert client.get("/health").status_code == 200  # the API itself stays up


def test_unknown_user_never_reaches_vertex(chroma):
    embedding = KeywordEmbedding()
    use_store(MessageStore(client_factory=lambda: chroma, embedding_function=embedding))
    assert client.post("/search", json={"user_id": "user_42", "query": "interview"}).status_code == 400
    assert embedding.queries == []


def test_query_is_embedded_once_as_a_query(chroma):
    add_mailbox(chroma, "user_01", [("m1", "t1", "none", "interview")])
    embedding = KeywordEmbedding()
    use_store(MessageStore(client_factory=lambda: chroma, embedding_function=embedding))
    client.post("/search", json={"user_id": "user_01", "query": "interview tips"})
    assert embedding.queries == ["interview tips"]


def test_default_store_uses_vertex_without_connecting_at_startup():
    store = MessageStore()
    assert isinstance(store.embedding_function, VertexEmbeddingFunction)
    assert store.embedding_function._client is None  # created on first search, not at startup


def test_search_opens_only_the_requested_collection():
    store, fake = fake_store(FakeCollection("messages_user_01"), FakeCollection("messages_user_02"))
    use_store(store)
    client.post("/search", json={"user_id": "user_03", "query": "interview"})
    assert fake.opened == ["messages_user_03"]


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
def two_user_chroma(chroma):
    """Two users who both email the same contact, Jordan Lee, about an interview."""
    add_mailbox(chroma, "user_01", [
        ("u1m1", "t001", "none", "Jordan Lee: interview Tuesday at 2:30 for Priya"),
        ("u1m2", "t002", "none", "Dentist reminder for Priya"),
    ])
    add_mailbox(chroma, "user_02", [
        ("u2m1", "t001", "none", "Jordan Lee: interview Friday at 10:00 for Marcus"),
        ("u2m2", "t002", "none", "Coffee chat with Marcus's mentor"),
    ])
    return chroma


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
        assert all(r["metadata"]["message_id"].startswith(user_id.replace("user_0", "u")) for r in results)
        assert all(first_name in r["text"] for r in results)
        # The shared-contact interview message is still the top hit.
        assert "interview" in results[0]["text"]


def test_message_search_matches_the_rag_copy():
    """message_search.py is copied from src/rag; the two must never drift."""
    here = Path(__file__).resolve().parent
    rag_copy = here.parent / "rag" / "message_search.py"
    if not rag_copy.exists():
        pytest.skip("src/rag is not next to this service (e.g. inside a container)")
    assert (here / "message_search.py").read_text() == rag_copy.read_text()


def test_embeddings_matches_the_rag_copy():
    """embeddings.py is copied from src/rag; the two must never drift."""
    here = Path(__file__).resolve().parent
    rag_copy = here.parent / "rag" / "embeddings.py"
    if not rag_copy.exists():
        pytest.skip("src/rag is not next to this service (e.g. inside a container)")
    assert (here / "embeddings.py").read_text() == rag_copy.read_text()


def test_no_code_uses_chromas_default_onnx_embedder():
    """Vertex AI is the only embedder: no api source file may use Chroma's
    default embedding function (the local all-MiniLM-L6-v2 ONNX model)."""
    here = Path(__file__).resolve().parent
    for path in here.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text()
        for banned in ("DefaultEmbeddingFunction", "ONNXMiniLM", "onnx", "MiniLM"):
            assert banned not in text, f"{path.name} mentions {banned}"
