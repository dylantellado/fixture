"""Shared test helpers. Gemini, embeddings and the classifier are never called:
every test uses the fakes below and made-up emails (example.com addresses)."""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import slots
from embeddings import EmbeddingError
from rules import rules_for

NY = "America/New_York"
NOW = "2026-11-09T10:00:00-05:00"  # a Monday


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def make_cal(busy=(), now=NOW, tz=NY, busy_until=None, **overrides) -> slots.Calendar:
    """A Calendar with the default rules (or overrides) and busy times given as ISO strings."""
    return slots.Calendar(
        busy=slots.merge_busy([(dt(s), dt(e)) for s, e in busy]),
        rules=rules_for("", overrides or None),
        now=dt(now),
        tz=ZoneInfo(tz),
        busy_until=dt(busy_until) if busy_until else None,
    )


def interval(start: str, end: str) -> slots.Interval:
    return slots.Interval(slots.to_utc(dt(start)), slots.to_utc(dt(end)))


class FakeGemini:
    """Returns the given answers in order (the last one repeats) and records every call."""

    def __init__(self, *answers, error=None):
        self.answers = list(answers)
        self.error = error
        self.calls = []

    def generate_json(self, system, user, schema, temperature):
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        if self.error:
            raise self.error
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        return copy.deepcopy(answer), {"attempts": 1, "input_tokens": 1000, "output_tokens": 100,
                                       "thinking_tokens": 10}


class FakeEmbedder:
    """Embeds by counting words: each vector has one number per word in VOCAB."""

    VOCAB = ["coffee", "interview", "analyst", "morning", "phone", "zoom", "lab", "thesis", "call", "team"]

    def __init__(self, error=False):
        self.error = error
        self.calls = []

    def embed(self, texts, task_type):
        self.calls.append((list(texts), task_type))
        if self.error:
            raise EmbeddingError("Vertex AI embedding failed (503)")
        vectors = [[text.lower().count(word) + 0.01 for word in self.VOCAB] for text in texts]
        return vectors, 7 * len(texts)


class FakeClassifier:
    def __init__(self, answer=None, error=None):
        self.answer = answer or {"label": "new_request", "needs_response": True, "reason": "D1."}
        self.error = error
        self.calls = []

    def classify(self, thread, target_index, message_id=""):
        self.calls.append({"thread": thread, "target_index": target_index, "message_id": message_id})
        if self.error:
            raise self.error
        return dict(self.answer)


def base_request(**changes) -> dict:
    """A valid /draft request: a recruiter asks for a 30-minute call."""
    request = {
        "message_id": "test-message",
        "now": NOW,
        "user": {"name": "Sam Rivera", "email": "sam.rivera@example.edu", "timezone": NY},
        "thread": [{
            "id": "m1", "from": "Jordan Lee <jordan.lee@example.com>", "to": "sam.rivera@example.edu",
            "date": "Mon, 09 Nov 2026 08:41:00 -0500", "subject": "Quick call?",
            "body": "Hi Sam, could we set up a 30-minute call about the analyst role next week?",
        }],
        "target_index": 0,
        "classification": {"label": "new_request", "needs_response": True, "reason": "D1: asks to meet."},
        "busy": [{"start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T17:00:00-05:00"}],
        "busy_until": "2026-11-23T10:00:00-05:00",
        "past_messages": [],
    }
    request.update(changes)
    return request


def offer_answer(*slot_ids, text=None, labels=None) -> dict:
    """A model answer offering these slot ids. text defaults to the slot labels on their own lines."""
    body = text if text is not None else "Hi Jordan,\n\nHere are a few times:\n" + "\n".join(
        f"- {label}" for label in (labels or [])) + "\n\nBest,\nSam"
    return {"action": "offer_times", "offered_slot_ids": list(slot_ids), "accepted_time": None,
            "confirmed_time": None, "context_used": [], "draft_text": body}


@pytest.fixture
def fake_gemini():
    return FakeGemini()
