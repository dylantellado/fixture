"""embeddings.py with the Vertex AI call mocked: no network in tests."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

import embeddings
from embeddings import (
    EmbeddingError,
    EmbeddingModelMismatch,
    EmbeddingSettings,
    VertexEmbeddingFunction,
    batches,
    build_embedding_function,
    check_collection_model,
    with_retries,
)


def api_error(code: int) -> errors.APIError:
    status = {429: "RESOURCE_EXHAUSTED", 400: "INVALID_ARGUMENT", 503: "UNAVAILABLE"}.get(code, "")
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": "details", "status": status}})


class FakeModels:
    """Stands in for client.models: returns one 3-number vector per text and
    records every call. `failures` are raised (in order) before answering."""

    def __init__(self, failures=(), merge=False):
        self.calls = []
        self.failures = list(failures)
        self.merge = merge  # behave like a model that returns one vector for a whole list

    def embed_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "task_type": config.task_type,
                           "auto_truncate": config.auto_truncate})
        if self.failures:
            raise self.failures.pop(0)
        texts = [" ".join(contents)] if self.merge else contents
        return SimpleNamespace(embeddings=[
            SimpleNamespace(values=[float(len(t)), 1.0, 0.0], statistics=SimpleNamespace(token_count=float(len(t.split()))))
            for t in texts
        ])


def make_ef(**fake_options):
    models = FakeModels(**fake_options)
    sleeps = []
    ef = VertexEmbeddingFunction(EmbeddingSettings(), client=SimpleNamespace(models=models), sleep=sleeps.append)
    return ef, models, sleeps


# --- Settings -------------------------------------------------------------------------


def test_settings_default_to_our_project(monkeypatch):
    for name in ("EMBEDDING_MODEL", "GOOGLE_CLOUD_PROJECT", "EMBEDDING_LOCATION"):
        monkeypatch.delenv(name, raising=False)
    settings = EmbeddingSettings.from_env()
    assert settings == EmbeddingSettings("gemini-embedding-001", "fixture-ac215-96dhbm", "us-central1")
    assert settings.token_limit == 2048


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-005")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "other-project")
    monkeypatch.setenv("EMBEDDING_LOCATION", "global")
    ef = build_embedding_function()
    assert (ef.model, ef.settings.project, ef.settings.location) == ("text-embedding-005", "other-project", "global")


def test_building_the_function_makes_no_network_call():
    # The client is created on first use, so services start without credentials.
    ef = build_embedding_function(EmbeddingSettings())
    assert ef._client is None


# --- Task types, vectors and token counts ------------------------------------------------


def test_documents_and_queries_use_their_task_types():
    ef, models, _ = make_ef()
    vectors, tokens = ef.embed_documents(["one two", "three"])
    assert vectors == [[7.0, 1.0, 0.0], [5.0, 1.0, 0.0]]
    assert tokens == [2, 1]
    ef.embed_query(["when is it?"])
    assert [c["task_type"] for c in models.calls] == ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
    assert all(c["model"] == "gemini-embedding-001" for c in models.calls)
    # Never cut a long text silently: Vertex AI must reject it instead.
    assert all(c["auto_truncate"] is False for c in models.calls)


def test_chroma_interface_embeds_documents():
    ef, models, _ = make_ef()
    assert [list(map(float, v)) for v in ef(["abc"])] == [[3.0, 1.0, 0.0]]
    assert models.calls[0]["task_type"] == "RETRIEVAL_DOCUMENT"


def test_collection_metadata_records_model_dimension_and_tasks():
    ef, _, _ = make_ef()
    assert ef.collection_metadata(3072) == {
        "embedding_model": "gemini-embedding-001",
        "embedding_dimension": 3072,
        "embedding_task_document": "RETRIEVAL_DOCUMENT",
        "embedding_task_query": "RETRIEVAL_QUERY",
        "embedding_token_limit": 2048,
    }


def test_a_merged_answer_is_an_error():
    """Some models return one vector for a whole list; that must never pass silently."""
    ef, _, _ = make_ef(merge=True)
    with pytest.raises(EmbeddingError, match="1 embeddings for 2 texts"):
        ef.embed_documents(["a", "b"])


# --- Batching ---------------------------------------------------------------------------


def test_batches_respect_count_and_size():
    assert batches(["a"] * 5, max_texts=2, max_chars=100) == [(0, 2), (2, 4), (4, 5)]
    assert batches(["x" * 40] * 3, max_texts=10, max_chars=100) == [(0, 2), (2, 3)]
    assert batches([], max_texts=2, max_chars=100) == []


def test_a_text_over_the_size_gets_its_own_batch():
    assert batches(["x" * 500, "y"], max_texts=10, max_chars=100) == [(0, 1), (1, 2)]


def test_many_texts_are_sent_in_batches_and_keep_their_order(monkeypatch):
    monkeypatch.setattr(embeddings, "BATCH_MAX_TEXTS", 3)
    ef, models, _ = make_ef()
    texts = [f"text {'x' * i}" for i in range(8)]
    vectors, _ = ef.embed_documents(texts)
    assert [len(c["contents"]) for c in models.calls] == [3, 3, 2]
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]


# --- Retries and errors -------------------------------------------------------------------


def test_rate_limits_are_retried_with_growing_waits():
    ef, models, sleeps = make_ef(failures=[api_error(429), api_error(503), httpx.ConnectError("down")])
    vectors, _ = ef.embed_documents(["hello"])
    assert len(vectors) == 1
    assert len(models.calls) == 4
    # About 1, 2, 4 s, plus up to 0.5 s of jitter each.
    assert [int(s) for s in sleeps] == [1, 2, 4]


def test_retries_give_up_with_a_clear_error():
    ef, models, sleeps = make_ef(failures=[api_error(429)] * embeddings.MAX_ATTEMPTS)
    with pytest.raises(EmbeddingError, match="429.*rate limited"):
        ef.embed_documents(["hello"])
    assert len(models.calls) == embeddings.MAX_ATTEMPTS
    assert len(sleeps) == embeddings.MAX_ATTEMPTS - 1


def test_permanent_errors_are_not_retried():
    ef, models, sleeps = make_ef(failures=[api_error(400)])
    with pytest.raises(EmbeddingError, match="400.*token limit"):
        ef.embed_documents(["hello"])
    assert len(models.calls) == 1
    assert sleeps == []


def test_error_messages_never_contain_the_text():
    ef, _, _ = make_ef(failures=[api_error(400)])
    with pytest.raises(EmbeddingError) as excinfo:
        ef.embed_documents(["Dear Priya, my phone number is PHONE_001"])
    assert "Priya" not in str(excinfo.value)


def test_with_retries_reraises_unexpected_errors_at_once():
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("bug")

    with pytest.raises(ValueError):
        with_retries(boom, sleep=lambda s: None)
    assert calls == [1]


def test_missing_credentials_is_a_clear_error(monkeypatch):
    def no_credentials(**kwargs):
        raise RuntimeError("default credentials not found")

    monkeypatch.setattr(embeddings.genai, "Client", no_credentials)
    ef = VertexEmbeddingFunction(EmbeddingSettings())
    with pytest.raises(EmbeddingError, match="gcloud auth application-default login"):
        ef.embed_documents(["hello"])


# --- Model mismatch ----------------------------------------------------------------------


def test_matching_model_is_accepted():
    check_collection_model("messages_user_01", {"embedding_model": "gemini-embedding-001"}, "gemini-embedding-001")


@pytest.mark.parametrize("metadata", [{"embedding_model": "all-MiniLM-L6-v2"}, {}, None])
def test_other_or_unknown_model_is_refused(metadata):
    with pytest.raises(EmbeddingModelMismatch, match="Rerun rag") as excinfo:
        check_collection_model("messages_user_01", metadata, "gemini-embedding-001")
    assert "messages_user_01" in str(excinfo.value)


def test_api_copy_is_identical():
    """embeddings.py is copied into src/api; the two must never drift."""
    api_copy = Path(embeddings.__file__).resolve().parent.parent / "api" / "embeddings.py"
    if not api_copy.exists():
        pytest.skip("src/api is not next to this service (e.g. inside a container)")
    assert api_copy.read_text() == Path(embeddings.__file__).read_text()
