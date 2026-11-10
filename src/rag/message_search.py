"""Search one user's collection and return MESSAGES, using thread context.

KEEP IN SYNC: src/rag/message_search.py and src/api/message_search.py are
identical copies, because services don't import from each other. rag's
check_retrieval.py scores this code and the api serves it, so they must not
drift. Change both together; a test in each service fails if they differ.

A collection holds two kinds of chunks (metadata "chunk_type", built by
rag's chunking.py):
  message  one email (long ones split), with its thread's subject, sender,
           date and the start of the message it replies to
  thread   a whole thread (long ones split into overlapping windows):
           subject, participants and each message's first lines

How a search works:
  1. Direct hits: the message chunks closest to the query.
  2. Thread hits: the THREAD_HITS thread chunks closest to the query. Every
     message in those threads becomes a candidate too, so a short reply
     ("Friday at 9 works") in the right thread is considered even when its
     own text says little.
  3. Every candidate gets two similarities (1 - cosine distance): its own
     (its best message chunk) and its thread's (the best thread chunk that
     contains it).
  4. score = (1 - THREAD_WEIGHT) * own + THREAD_WEIGHT * thread. Within a
     thread, messages keep the order of their own similarity; across
     threads, a message in a thread that matches the question moves up.
  5. One result per message (its best chunk), best first, top k.
Results are always messages, never thread chunks.

PRIVACY: everything here reads the one collection it is given. The caller
picks that collection from the requested user_id.
"""

import math

MESSAGE = "message"
THREAD = "thread"

# How many thread chunks can pull their messages in as candidates.
THREAD_HITS = 3
# How much the thread's similarity counts in a message's score (0 = only the
# message's own similarity, which makes thread chunks unable to change the
# ranking; see docs/evidence/rag_experiments.md for the dev comparison).
THREAD_WEIGHT = 0.5
# Direct hits to fetch per requested result, so messages just below the top k
# can still move up when their thread matches.
CANDIDATES_PER_RESULT = 3


def cosine_similarity(a, b) -> float:
    """1 - cosine distance, computed the same way Chroma's "cosine" space does."""
    dot = sum(x * y for x, y in zip(a, b))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


def message_filter(label: str | None = None, thread_ids: list[str] | None = None) -> dict:
    """Chroma `where` filter for message chunks, optionally by label and threads."""
    conditions = [{"chunk_type": MESSAGE}]
    if label:
        conditions.append({"label": label})
    if thread_ids is not None:
        conditions.append({"thread_id": {"$in": thread_ids}})
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def nearest(collection, query_embedding, n: int, where: dict) -> list[dict]:
    """The n chunks closest to the query (approximate nearest neighbors), best first."""
    found = collection.query(
        query_embeddings=[query_embedding],
        n_results=n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    # Chroma returns one list per query embedding; we sent one, so take [0].
    return [
        {"id": chunk_id, "text": text, "metadata": metadata, "similarity": 1 - distance}
        for chunk_id, text, metadata, distance in zip(
            found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0]
        )
    ]


def every_match(collection, query_embedding, where: dict) -> list[dict]:
    """All chunks matching the filter, each with its similarity to the query (exact, no limit)."""
    found = collection.get(where=where, include=["documents", "metadatas", "embeddings"])
    return [
        {"id": chunk_id, "text": text, "metadata": metadata, "similarity": cosine_similarity(query_embedding, embedding)}
        for chunk_id, text, metadata, embedding in zip(
            found["ids"], found["documents"], found["metadatas"], found["embeddings"]
        )
    ]


def search_messages(collection, query_embedding, k: int, label: str | None = None,
                    thread_weight: float = THREAD_WEIGHT) -> list[dict]:
    """The k messages that best answer the query, best first.

    query_embedding: the query's vector, from the same model the collection
        was built with (the caller checks that).
    label: if given, only messages with this label are returned.
    Each result is {"id", "text", "score", "metadata"} for the message's best
    chunk; score is described in the module docstring (higher is closer).
    """
    # 1. Direct hits.
    candidates = nearest(collection, query_embedding, k * CANDIDATES_PER_RESULT, message_filter(label))

    # 2. Thread hits: every message in a matching thread is a candidate too.
    top_threads = nearest(collection, query_embedding, THREAD_HITS, {"chunk_type": THREAD})
    matched = sorted({chunk["metadata"]["thread_id"] for chunk in top_threads})
    if matched:
        candidates += every_match(collection, query_embedding, message_filter(label, matched))

    # One entry per message: its best chunk (long messages have several).
    best: dict[str, dict] = {}
    for chunk in candidates:
        message_id = chunk["metadata"]["message_id"]
        if message_id not in best or chunk["similarity"] > best[message_id]["similarity"]:
            best[message_id] = chunk
    if not best:
        return []

    # 3. Each candidate's thread similarity: the best thread chunk that contains it.
    thread_ids = sorted({chunk["metadata"]["thread_id"] for chunk in best.values()})
    thread_similarity: dict[str, float] = {}
    windows = every_match(collection, query_embedding, {"$and": [{"chunk_type": THREAD}, {"thread_id": {"$in": thread_ids}}]})
    for window in windows:
        for message_id in window["metadata"]["message_ids"].split(","):
            thread_similarity[message_id] = max(thread_similarity.get(message_id, -1.0), window["similarity"])

    # 4. Combine, then 5. best first (ties broken by id so the order is stable).
    results = []
    for message_id, chunk in best.items():
        own = chunk["similarity"]
        thread = thread_similarity.get(message_id, own)  # no thread chunk: own similarity only
        results.append({
            "id": chunk["id"],
            "text": chunk["text"],
            "score": (1 - thread_weight) * own + thread_weight * thread,
            "metadata": chunk["metadata"],
        })
    results.sort(key=lambda r: (-r["score"], r["metadata"]["message_id"]))
    return results[:k]
