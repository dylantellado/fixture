"""Ranking past emails with the sender (embeddings faked)."""

from context import MAX_DOC_CHARS, get_relevant_context, most_recent
from conftest import FakeEmbedder

THREAD = [{"id": "t1", "subject": "Coffee chat?", "body": "Want to grab coffee next week? Mornings are best."}]


def past(i, body, date="Mon, 02 Nov 2026 09:00:00 -0500", subject="Hello"):
    return {"id": f"p{i}", "from": "Jordan <j@example.com>", "to": "sam@example.edu", "date": date,
            "subject": subject, "body": body}


def test_most_similar_past_emails_come_first_and_only_k_are_kept():
    messages = [past(1, "lab meeting notes"), past(2, "coffee coffee in the morning"), past(3, "thesis draft"),
                past(4, "coffee?"), past(5, "zoom link"), past(6, "lab lab"), past(7, "team call")]
    embedder = FakeEmbedder()
    result = get_relevant_context({}, THREAD, 0, messages, embedder, k=5)
    assert result.method == "similarity" and result.candidates == 7
    assert [i.message["id"] for i in result.items][:2] == ["p2", "p4"]
    assert len(result.items) == 5 and [i.rank for i in result.items] == [1, 2, 3, 4, 5]
    assert result.items[0].score >= result.items[1].score >= result.items[-1].score
    assert result.embedding_tokens == 7 * 8  # 7 documents + 1 query


def test_documents_and_query_use_the_retrieval_task_types():
    embedder = FakeEmbedder()
    get_relevant_context({}, THREAD, 0, [past(1, "coffee")], embedder)
    assert [task for _, task in embedder.calls] == ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
    assert "Mornings are best" in embedder.calls[1][0][0]


def test_long_past_emails_are_cut():
    embedder = FakeEmbedder()
    get_relevant_context({}, THREAD, 0, [past(1, "x" * 10_000)], embedder)
    assert len(embedder.calls[0][0][0]) == MAX_DOC_CHARS


def test_duplicates_empty_bodies_and_the_current_thread_are_skipped():
    messages = [past(1, "coffee"), past(1, "coffee again"), past(2, "  "), {**past(3, "coffee"), "id": "t1"}]
    result = get_relevant_context({}, THREAD, 0, messages, FakeEmbedder())
    assert [i.message["id"] for i in result.items] == ["p1"]


def test_no_past_emails_means_no_embedding_call():
    embedder = FakeEmbedder()
    result = get_relevant_context({}, THREAD, 0, [], embedder)
    assert result.items == [] and result.method == "none" and embedder.calls == []


def test_embedding_failure_falls_back_to_the_most_recent():
    messages = [past(1, "a", "Mon, 02 Nov 2026 09:00:00 -0500"), past(2, "b", "Wed, 04 Nov 2026 09:00:00 -0500"),
                past(3, "c", "not a date"), past(4, "d", "2026-11-03T09:00:00-05:00")]
    result = get_relevant_context({}, THREAD, 0, messages, FakeEmbedder(error=True), k=3)
    assert result.method == "recent"
    assert [i.message["id"] for i in result.items] == ["p2", "p4", "p1"]
    assert all(i.score is None for i in result.items)
    assert "embedding call failed" in result.warnings[0]


def test_most_recent_keeps_undated_ones_last():
    assert [m["id"] for m in most_recent([past(1, "a", "?"), past(2, "b")], 2)] == ["p2", "p1"]
