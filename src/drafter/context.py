"""Pick the past emails with this sender that matter for the current thread.

get_relevant_context() is the only entry point. Today the caller (the web app)
sends recent messages exchanged with the sender, and this ranks them by
embedding similarity to the current thread and keeps the top k (5).

SWAP LATER: a persistent per-user inbox index (like rag's per-user ChromaDB
collections, built by a Gmail watcher) will replace the sender search. Then
past_messages can be empty and this function queries the user's index instead,
with the same signature and the same ContextResult, so pipeline.py and the
prompt don't change. The user argument is here for that.

If embedding fails, the most recent messages are used instead, with a
warning: a draft without perfect context is still useful, and the checker
doesn't depend on context.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

from embeddings import TASK_DOCUMENT, TASK_QUERY, EmbeddingError

DEFAULT_K = 5
MAX_DOC_CHARS = 3000  # per past email sent to the embedding model and the prompt
MAX_QUERY_CHARS = 3000


@dataclass
class ContextItem:
    message: dict  # {id, from, to, date, subject, body, ...} as received
    score: float | None  # cosine similarity to the thread; None if ranked by date
    rank: int  # 1 = most relevant


@dataclass
class ContextResult:
    items: list[ContextItem] = field(default_factory=list)
    method: str = "none"  # "similarity", "recent" (embedding failed) or "none" (no past emails)
    candidates: int = 0  # how many past emails were considered
    warnings: list[str] = field(default_factory=list)
    embedding_tokens: int = 0


def document_text(message: dict) -> str:
    text = f"Subject: {message.get('subject', '')}\nFrom: {message.get('from', '')}\n" \
           f"Date: {message.get('date', '')}\n\n{message.get('body', '')}"
    return text[:MAX_DOC_CHARS]


def query_text(thread: list[dict], target_index: int) -> str:
    """The target email, then the one before it: what the reply is about."""
    target = thread[target_index]
    parts = [f"Subject: {target.get('subject', '')}", target.get("body", "")]
    if target_index > 0:
        parts.append(thread[target_index - 1].get("body", ""))
    return "\n\n".join(parts)[:MAX_QUERY_CHARS]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def sent_at(message: dict) -> datetime | None:
    """Parse an email Date header or an ISO time; None if neither works."""
    value = message.get("date", "")
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            parsed = parse(value)
            if parsed.tzinfo is not None:
                return parsed
        except (TypeError, ValueError, IndexError):
            continue
    return None


def most_recent(messages: list[dict], k: int) -> list[dict]:
    """Newest first; messages without a parseable date keep their order, after dated ones."""
    dated = [(sent_at(m), i, m) for i, m in enumerate(messages)]
    dated.sort(key=lambda d: (d[0] is None, -(d[0].timestamp()) if d[0] else 0, d[1]))
    return [m for _, _, m in dated[:k]]


def get_relevant_context(user: dict, thread: list[dict], target_index: int, past_messages: list[dict],
                         embedder, k: int = DEFAULT_K) -> ContextResult:
    """The k past emails most relevant to thread[target_index]. See the module docstring."""
    thread_ids = {m.get("id") for m in thread if m.get("id")}
    seen, candidates = set(), []
    for message in past_messages:
        key = message.get("id")
        if key in seen or key in thread_ids or not message.get("body", "").strip():
            continue
        seen.add(key)
        candidates.append(message)
    if not candidates:
        return ContextResult(method="none")

    try:
        doc_vectors, doc_tokens = embedder.embed([document_text(m) for m in candidates], TASK_DOCUMENT)
        [query_vector], query_tokens = embedder.embed([query_text(thread, target_index)], TASK_QUERY)
    except EmbeddingError:
        recent = most_recent(candidates, k)
        return ContextResult(
            items=[ContextItem(m, None, i + 1) for i, m in enumerate(recent)], method="recent",
            candidates=len(candidates),
            warnings=["Past emails were picked by date, not relevance: the embedding call failed."])

    scored = sorted(((cosine(query_vector, v), i) for i, v in enumerate(doc_vectors)), key=lambda s: (-s[0], s[1]))
    items = [ContextItem(candidates[i], round(score, 3), rank + 1) for rank, (score, i) in enumerate(scored[:k])]
    return ContextResult(items=items, method="similarity", candidates=len(candidates),
                         embedding_tokens=doc_tokens + query_tokens)
