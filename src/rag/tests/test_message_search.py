"""The shared message search (message_search.py): thread expansion, scores, dedupe.

Uses an in-memory Chroma collection with hand-placed vectors, so each test
controls exactly how similar every chunk is to the query.
"""

import math
from pathlib import Path

import pytest

import message_search
from message_search import cosine_similarity, message_filter, search_messages

QUERY = [1.0, 0.0, 0.0]


def toward(similarity: float) -> list[float]:
    """A unit vector whose cosine similarity with QUERY is `similarity`."""
    return [similarity, math.sqrt(1 - similarity**2), 0.0]


def message_chunk(chunk_id, message_id, thread_id, similarity, label="acceptance"):
    return {
        "id": chunk_id,
        "embedding": toward(similarity),
        "document": f"text of {chunk_id}",
        "metadata": {"chunk_type": "message", "message_id": message_id, "thread_id": thread_id,
                     "user_id": "user_01", "label": label},
    }


def thread_chunk(thread_id, message_ids, similarity, window=0):
    return {
        "id": f"thread-{thread_id}-{window}",
        "embedding": toward(similarity),
        "document": f"thread {thread_id}",
        "metadata": {"chunk_type": "thread", "thread_id": thread_id, "user_id": "user_01",
                     "message_ids": ",".join(message_ids)},
    }


@pytest.fixture
def make_collection(chroma_client):
    def make(chunks):
        collection = chroma_client.create_collection(
            "messages_user_01", embedding_function=None, configuration={"hnsw": {"space": "cosine"}}
        )
        collection.add(
            ids=[c["id"] for c in chunks],
            embeddings=[c["embedding"] for c in chunks],
            documents=[c["document"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
        )
        return collection
    return make


def ids(results):
    return [r["metadata"]["message_id"] for r in results]


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity(QUERY, toward(0.3)) == pytest.approx(0.3)
    assert cosine_similarity([0, 0], [1, 0]) == 0.0  # no direction, no similarity


def test_message_filter():
    assert message_filter() == {"chunk_type": "message"}
    assert message_filter("reschedule") == {"$and": [{"chunk_type": "message"}, {"label": "reschedule"}]}
    assert message_filter(None, ["t1"]) == {"$and": [{"chunk_type": "message"}, {"thread_id": {"$in": ["t1"]}}]}


def test_short_reply_in_matching_thread_is_found_through_its_thread(make_collection):
    """The reply's own text barely matches (0.2), so it isn't a direct hit:
    five other messages are closer. Its thread matches strongly (0.95), which
    makes it a candidate and lifts its score above the unrelated messages."""
    chunks = [message_chunk(f"d{i}-0", f"d{i}", f"other{i}", 0.6) for i in range(5)]
    chunks += [thread_chunk(f"other{i}", [f"d{i}"], 0.1) for i in range(5)]
    chunks += [
        message_chunk("reply-0", "reply", "t1", 0.2),
        message_chunk("invite-0", "invite", "t1", 0.5),
        thread_chunk("t1", ["invite", "reply"], 0.95),
    ]
    collection = make_collection(chunks)

    results = search_messages(collection, QUERY, k=1)  # direct hits: only 3 candidates
    assert ids(results) == ["invite"]  # best of the matching thread first

    results = search_messages(collection, QUERY, k=3)
    assert ids(results)[:2] == ["invite", "reply"]
    # score = half own similarity, half thread similarity.
    assert results[1]["score"] == pytest.approx(0.5 * 0.2 + 0.5 * 0.95, abs=1e-4)


def test_with_no_thread_weight_only_own_similarity_counts(make_collection):
    chunks = [
        message_chunk("a-0", "a", "t1", 0.7),
        message_chunk("b-0", "b", "t2", 0.4),
        thread_chunk("t1", ["a"], 0.1),
        thread_chunk("t2", ["b"], 0.99),
    ]
    collection = make_collection(chunks)
    results = search_messages(collection, QUERY, k=2, thread_weight=0)
    assert ids(results) == ["a", "b"]
    assert [r["score"] for r in results] == pytest.approx([0.7, 0.4], abs=1e-4)


def test_results_are_messages_never_threads(make_collection):
    chunks = [
        message_chunk("a-0", "a", "t1", 0.3),
        thread_chunk("t1", ["a"], 0.99),
        thread_chunk("t2", ["x", "y"], 0.98),  # a thread whose messages aren't indexed
    ]
    collection = make_collection(chunks)
    results = search_messages(collection, QUERY, k=5)
    assert ids(results) == ["a"]
    assert all(r["metadata"]["chunk_type"] == "message" for r in results)


def test_long_message_appears_once_with_its_best_chunk(make_collection):
    chunks = [
        message_chunk("long-0", "long", "t1", 0.4),
        message_chunk("long-1", "long", "t1", 0.8),
        message_chunk("other-0", "other", "t2", 0.6),
        thread_chunk("t1", ["long"], 0.5),
        thread_chunk("t2", ["other"], 0.5),
    ]
    collection = make_collection(chunks)
    results = search_messages(collection, QUERY, k=5)
    assert ids(results) == ["long", "other"]  # deduped by message_id
    assert results[0]["id"] == "long-1"  # the better chunk


def test_message_in_two_windows_uses_the_better_window(make_collection):
    chunks = [
        message_chunk("a-0", "a", "t1", 0.5),
        thread_chunk("t1", ["a", "b"], 0.2, window=0),
        thread_chunk("t1", ["b", "a"], 0.9, window=1),
    ]
    collection = make_collection(chunks)
    [result] = search_messages(collection, QUERY, k=1)
    assert result["score"] == pytest.approx(0.5 * 0.5 + 0.5 * 0.9, abs=1e-4)


def test_label_filter_applies_to_messages_found_through_threads(make_collection):
    chunks = [
        message_chunk("a-0", "a", "t1", 0.9, label="acceptance"),
        message_chunk("b-0", "b", "t1", 0.8, label="reschedule"),
        thread_chunk("t1", ["a", "b"], 0.9),
    ]
    collection = make_collection(chunks)
    results = search_messages(collection, QUERY, k=5, label="reschedule")
    assert ids(results) == ["b"]


def test_k_limits_results_and_order_is_best_first(make_collection):
    chunks = [message_chunk(f"m{i}-0", f"m{i}", f"t{i}", 0.1 * i) for i in range(1, 9)]
    chunks += [thread_chunk(f"t{i}", [f"m{i}"], 0.1 * i) for i in range(1, 9)]
    collection = make_collection(chunks)
    results = search_messages(collection, QUERY, k=4)
    assert ids(results) == ["m8", "m7", "m6", "m5"]
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_collection_without_thread_chunks_uses_own_similarity(make_collection):
    collection = make_collection([message_chunk("a-0", "a", "t1", 0.6)])
    [result] = search_messages(collection, QUERY, k=3)
    assert result["score"] == pytest.approx(0.6, abs=1e-4)


def test_empty_collection_returns_nothing(chroma_client):
    collection = chroma_client.create_collection("messages_user_01", embedding_function=None)
    assert search_messages(collection, QUERY, k=5) == []


def test_api_copy_is_identical():
    """message_search.py is copied into src/api; the two must never drift."""
    api_copy = Path(message_search.__file__).resolve().parent.parent / "api" / "message_search.py"
    if not api_copy.exists():
        pytest.skip("src/api is not next to this service (e.g. inside a container)")
    assert api_copy.read_text() == Path(message_search.__file__).read_text()
