"""Indexing into an in-memory Chroma with a fake embedding function (fast, offline)."""

import copy
import json

import pytest

import config
import main
from helpers import SAMPLES_DIR, long_body, make_message, write_pipeline_data
from embeddings import EmbeddingError, EmbeddingModelMismatch
from index import collection_name, open_collection, search
from inputs import InputError, sha256_file


def json_lines(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def index_size(messages, user_id):
    """Chunks expected for a user whose messages are all short: one per message, one per thread."""
    own = [m for m in messages if m["user_id"] == user_id]
    return len(own) + len({m["thread_id"] for m in own})


def index(client, ef, data_dir):
    """Run the whole job against the in-memory client."""
    return main.run(lambda: client, ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)


def test_sample_gives_one_collection_per_user(chroma_client, fake_ef, data_dir, sample_messages, sample_users):
    sizes = index(chroma_client, fake_ef, data_dir)

    # Every user in users.json gets a collection, even one with no sample
    # messages yet (its collection is empty). Expectations come from the
    # sample files, so this stays right if samples gain users or messages.
    # All sample bodies are short, so each message is exactly one chunk, and
    # each thread adds one thread chunk.
    user_ids = [u["user_id"] for u in sample_users]

    def own(user_id):
        return [m for m in sample_messages if m["user_id"] == user_id]

    expected = {collection_name(u): len(own(u)) + len({m["thread_id"] for m in own(u)}) for u in user_ids}
    assert sizes == expected
    assert sorted(c.name for c in chroma_client.list_collections()) == sorted(expected)

    # Each collection holds exactly that user's messages and threads.
    for user_id in user_ids:
        stored = chroma_client.get_collection(collection_name(user_id)).get(include=["metadatas"])
        expected_ids = {f"{m['message_id']}-0" for m in own(user_id)}
        expected_ids |= {f"thread-{m['thread_id']}-0" for m in own(user_id)}
        assert set(stored["ids"]) == expected_ids
        assert all(meta["user_id"] == user_id for meta in stored["metadatas"])


def test_collection_metadata_records_the_data_version(chroma_client, fake_ef, data_dir):
    index(chroma_client, fake_ef, data_dir)
    collection = chroma_client.get_collection("messages_user_01")

    metadata = collection.metadata
    assert metadata["user_id"] == "user_01"
    assert metadata["user_name"] == "Priya Shah"
    assert metadata["input_path"] == str(SAMPLES_DIR / "messages_sample.jsonl")
    assert metadata["input_sha256"] == sha256_file(SAMPLES_DIR / "messages_sample.jsonl")
    assert metadata["used_sample_data"] is True
    assert metadata["embedding_model"] == "fake-bag-of-words"
    assert metadata["embedding_dimension"] == 64
    assert metadata["embedding_task_document"] == "RETRIEVAL_DOCUMENT"
    assert metadata["embedding_task_query"] == "RETRIEVAL_QUERY"
    assert metadata["embedding_token_limit"] == 2048
    assert metadata["chunking"] == "message+thread"
    assert metadata["indexed_at"]  # set to the run time
    assert metadata["manifest_git_commit"] == ""  # samples have no manifest

    # Cosine distance, not Chroma's default (l2).
    assert collection.configuration["hnsw"]["space"] == "cosine"


def test_manifest_values_are_stored(chroma_client, fake_ef, data_dir):
    users = [{"user_id": "user_01", "name": "Priya Shah"}]
    manifest = {"git_commit": "eed41cd", "created_at": "2026-10-19T14:00:00Z"}
    write_pipeline_data(data_dir, [make_message()], users, manifest=manifest)
    index(chroma_client, fake_ef, data_dir)

    metadata = chroma_client.get_collection("messages_user_01").metadata
    assert metadata["manifest_git_commit"] == "eed41cd"
    assert metadata["manifest_created_at"] == "2026-10-19T14:00:00Z"
    assert metadata["used_sample_data"] is False


def test_rerun_does_not_duplicate(chroma_client, fake_ef, data_dir):
    first = index(chroma_client, fake_ef, data_dir)
    ids_before = set(chroma_client.get_collection("messages_user_01").get()["ids"])

    second = index(chroma_client, fake_ef, data_dir)
    ids_after = set(chroma_client.get_collection("messages_user_01").get()["ids"])

    assert first == second
    assert ids_before == ids_after
    assert len(chroma_client.list_collections()) == len(first)  # one per user, no extras


def test_removed_message_disappears_after_rebuild(chroma_client, fake_ef, data_dir, sample_messages, sample_users):
    index(chroma_client, fake_ef, data_dir)  # samples
    removed = sample_messages[0]
    assert chroma_client.get_collection("messages_user_01").get(ids=[f"{removed['message_id']}-0"])["ids"]

    # Same data without the first message, written where preprocess would put it.
    write_pipeline_data(data_dir, sample_messages[1:], sample_users)
    sizes = index(chroma_client, fake_ef, data_dir)

    assert sizes["messages_user_01"] == index_size(sample_messages[1:], "user_01")
    assert chroma_client.get_collection("messages_user_01").get(ids=[f"{removed['message_id']}-0"])["ids"] == []


def test_user_removed_from_data_loses_their_collection(chroma_client, fake_ef, data_dir, sample_messages, sample_users):
    index(chroma_client, fake_ef, data_dir)
    # A collection that isn't ours must never be deleted.
    chroma_client.create_collection("not_fixture_messages", embedding_function=fake_ef)

    only_user_01 = [m for m in sample_messages if m["user_id"] == "user_01"]
    write_pipeline_data(data_dir, only_user_01, [u for u in sample_users if u["user_id"] == "user_01"])
    index(chroma_client, fake_ef, data_dir)

    names = sorted(c.name for c in chroma_client.list_collections())
    assert names == ["messages_user_01", "not_fixture_messages"]


def test_user_without_messages_gets_an_empty_collection(chroma_client, fake_ef, data_dir):
    users = [{"user_id": "user_01", "name": "Priya Shah"}, {"user_id": "user_03", "name": "Ana Ruiz"}]
    write_pipeline_data(data_dir, [make_message()], users)
    sizes = index(chroma_client, fake_ef, data_dir)
    assert sizes == {"messages_user_01": 2, "messages_user_03": 0}  # one message chunk, one thread chunk


def test_long_message_is_stored_as_several_chunks(chroma_client, fake_ef, data_dir):
    users = [{"user_id": "user_01", "name": "Priya Shah"}]
    write_pipeline_data(data_dir, [make_message(body=long_body(2000))], users)  # well over CHUNK_MAX_CHARS
    sizes = index(chroma_client, fake_ef, data_dir)

    stored = chroma_client.get_collection("messages_user_01").get(where={"chunk_type": "message"}, include=["metadatas"])
    assert len(stored["ids"]) > 1
    assert {meta["message_id"] for meta in stored["metadatas"]} == {"abc123def4567890"}


def test_invalid_input_leaves_existing_index_alone(chroma_client, fake_ef, data_dir, sample_users):
    index(chroma_client, fake_ef, data_dir)  # a good index from the samples

    write_pipeline_data(data_dir, [make_message(label="not_a_label")], sample_users)
    connected = []
    with pytest.raises(InputError):
        main.run(lambda: connected.append(True) or chroma_client, fake_ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)

    assert connected == []  # never connected to Chroma
    assert chroma_client.get_collection("messages_user_01").count() == index_size(
        [m for m in json_lines(SAMPLES_DIR / "messages_sample.jsonl")], "user_01")


def test_main_exits_nonzero_on_invalid_input(monkeypatch):
    def fail(*args, **kwargs):
        raise InputError("bad data")

    monkeypatch.setattr(main, "run", fail)
    monkeypatch.setattr(main.config, "get_embedding_function", lambda: None)  # never call Vertex AI
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


def test_search_only_returns_the_users_own_messages(chroma_client, fake_ef, data_dir, sample_messages):
    """Isolation: Jordan Lee (Northbridge) emails both users. Searching as
    user_01 must never return user_02's copy of that conversation."""
    index(chroma_client, fake_ef, data_dir)
    user_01_ids = {m["message_id"] for m in sample_messages if m["user_id"] == "user_01"}
    user_02_ids = {m["message_id"] for m in sample_messages if m["user_id"] == "user_02"}

    collection = chroma_client.get_collection("messages_user_01", embedding_function=fake_ef)
    results = search(collection, "Jordan Lee Northbridge Capital interview", k=10, embedding_function=fake_ef)

    assert len(results) == 10  # every user_01 message, and nothing else
    returned_ids = {r["metadata"]["message_id"] for r in results}
    assert returned_ids == user_01_ids
    assert returned_ids.isdisjoint(user_02_ids)
    assert all(r["metadata"]["user_id"] == "user_01" for r in results)
    # The best match is from Jordan Lee, so the header made the name searchable.
    assert results[0]["metadata"]["sender_name"] == "Jordan Lee"


def test_search_scores_and_label_filter(chroma_client, fake_ef, data_dir):
    index(chroma_client, fake_ef, data_dir)
    collection = chroma_client.get_collection("messages_user_02", embedding_function=fake_ef)

    results = search(collection, "move the interview", k=5, embedding_function=fake_ef)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)  # best first
    assert all(-1.0 <= s <= 1.0 for s in scores)

    filtered = search(collection, "move the interview", k=5, label="reschedule", embedding_function=fake_ef)
    assert len(filtered) == 1
    assert filtered[0]["metadata"]["label"] == "reschedule"


def test_token_counts_are_recorded(chroma_client, fake_ef, data_dir):
    users = [{"user_id": "user_01", "name": "Priya Shah"}, {"user_id": "user_02", "name": "Marcus Bell"}]
    messages = [
        make_message(body="short"),
        make_message(message_id="b" * 16, body=long_body(300)),
        make_message(message_id="c" * 16, user_id="user_02", body=long_body(300)),
    ]
    write_pipeline_data(data_dir, messages, users)
    main.run(lambda: chroma_client, fake_ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)

    for user_id in ("user_01", "user_02"):
        collection = chroma_client.get_collection(collection_name(user_id))
        stored = collection.get(include=["metadatas", "documents"])
        for metadata, text in zip(stored["metadatas"], stored["documents"]):
            assert metadata["token_count"] == len(text.split())  # what the embedding call reported
        assert collection.metadata["chunks_over_token_limit"] == 0


def test_chunks_over_the_limit_are_counted_per_user():
    chunks = [{"metadata": {"token_count": n}} for n in (10, 2048, 2049, 5000)]
    assert main.chunks_over_limit(chunks, 2048) == 2


def test_stored_vectors_are_the_embedding_functions(chroma_client, fake_ef, data_dir):
    index(chroma_client, fake_ef, data_dir)
    stored = chroma_client.get_collection("messages_user_01").get(include=["documents", "embeddings"])
    for text, vector in zip(stored["documents"], stored["embeddings"]):
        assert list(vector) == pytest.approx(fake_ef([text])[0], abs=1e-6)


def test_failed_embedding_leaves_existing_index_alone(chroma_client, fake_ef, data_dir):
    index(chroma_client, fake_ef, data_dir)  # a good index from the samples
    before = chroma_client.get_collection("messages_user_01").count()

    class FailingEmbedding(type(fake_ef)):
        def embed_documents(self, texts):
            raise EmbeddingError("Vertex AI returned 429 (rate limited)")

    connected = []
    with pytest.raises(EmbeddingError):
        main.run(lambda: connected.append(True) or chroma_client, FailingEmbedding(), data_dir=data_dir, samples_dir=SAMPLES_DIR)
    assert connected == []  # never touched ChromaDB
    assert chroma_client.get_collection("messages_user_01").count() == before


def test_collections_have_no_chroma_embedding_function(chroma_client, fake_ef, data_dir):
    """Chroma never embeds by itself (no default ONNX model): rag passes vectors."""
    index(chroma_client, fake_ef, data_dir)
    assert chroma_client.get_collection("messages_user_01").configuration.get("embedding_function") is None


def test_plain_chunking_for_experiments(chroma_client, fake_ef, data_dir, sample_messages):
    sizes = main.run(lambda: chroma_client, fake_ef, data_dir=data_dir, samples_dir=SAMPLES_DIR, thread_context=False)
    assert sizes["messages_user_01"] == sum(m["user_id"] == "user_01" for m in sample_messages)
    stored = chroma_client.get_collection("messages_user_01").get(include=["metadatas"])
    assert {m["chunk_type"] for m in stored["metadatas"]} == {"message"}
    assert chroma_client.get_collection("messages_user_01").metadata["chunking"] == "message"


def test_open_collection_refuses_another_model(chroma_client, fake_ef, data_dir):
    index(chroma_client, fake_ef, data_dir)
    assert open_collection(chroma_client, "user_01", model="fake-bag-of-words").name == "messages_user_01"
    with pytest.raises(EmbeddingModelMismatch, match="Rerun rag"):
        open_collection(chroma_client, "user_01", model="gemini-embedding-001")


def test_shared_configuration_is_not_modified(chroma_client, fake_ef, data_dir):
    # Regression: Chroma writes the embedding function into the configuration
    # dict it receives. If that were our shared constant, the next run would
    # silently reuse this run's embedding function.
    before = copy.deepcopy(config.COLLECTION_CONFIGURATION)
    index(chroma_client, fake_ef, data_dir)
    assert config.COLLECTION_CONFIGURATION == before
