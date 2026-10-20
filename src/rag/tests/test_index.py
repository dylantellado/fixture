"""Indexing into an in-memory Chroma with a fake embedding function (fast, offline)."""

import copy

import pytest

import config
import main
from helpers import SAMPLES_DIR, long_body, make_message, write_pipeline_data
from index import collection_name, search
from inputs import InputError, sha256_file


def index(client, ef, data_dir):
    """Run the whole job against the in-memory client."""
    return main.run(lambda: client, ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)


def test_sample_gives_one_collection_per_user(chroma_client, fake_ef, data_dir, sample_messages, sample_users):
    sizes = index(chroma_client, fake_ef, data_dir)

    # Every user in users.json gets a collection, even one with no sample
    # messages yet (its collection is empty). Expectations come from the
    # sample files, so this stays right if samples gain users or messages.
    # All sample bodies are short, so each message is exactly one chunk.
    user_ids = [u["user_id"] for u in sample_users]
    expected = {collection_name(u): sum(m["user_id"] == u for m in sample_messages) for u in user_ids}
    assert sizes == expected
    assert sorted(c.name for c in chroma_client.list_collections()) == sorted(expected)

    # Each collection holds exactly that user's messages.
    for user_id in user_ids:
        stored = chroma_client.get_collection(collection_name(user_id)).get(include=["metadatas"])
        expected_ids = {f"{m['message_id']}-0" for m in sample_messages if m["user_id"] == user_id}
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
    assert metadata["embedding_model"] == "all-MiniLM-L6-v2"
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

    assert sizes["messages_user_01"] == 9
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
    assert sizes == {"messages_user_01": 1, "messages_user_03": 0}


def test_long_message_is_stored_as_several_chunks(chroma_client, fake_ef, data_dir):
    users = [{"user_id": "user_01", "name": "Priya Shah"}]
    write_pipeline_data(data_dir, [make_message(body=long_body())], users)
    sizes = index(chroma_client, fake_ef, data_dir)

    stored = chroma_client.get_collection("messages_user_01").get(include=["metadatas"])
    assert sizes["messages_user_01"] == len(stored["ids"]) > 1
    assert {meta["message_id"] for meta in stored["metadatas"]} == {"abc123def4567890"}


def test_invalid_input_leaves_existing_index_alone(chroma_client, fake_ef, data_dir, sample_users):
    index(chroma_client, fake_ef, data_dir)  # a good index from the samples

    write_pipeline_data(data_dir, [make_message(label="not_a_label")], sample_users)
    connected = []
    with pytest.raises(InputError):
        main.run(lambda: connected.append(True) or chroma_client, fake_ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)

    assert connected == []  # never connected to Chroma
    assert chroma_client.get_collection("messages_user_01").count() == 10


def test_main_exits_nonzero_on_invalid_input(monkeypatch):
    def fail(*args, **kwargs):
        raise InputError("bad data")

    monkeypatch.setattr(main, "run", fail)
    monkeypatch.setattr(main.config, "get_embedding_function", lambda: None)
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
    results = search(collection, "Jordan Lee Northbridge Capital interview", k=10)

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

    results = search(collection, "move the interview", k=5)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)  # best first
    assert all(-1.0 <= s <= 1.0 for s in scores)

    filtered = search(collection, "move the interview", k=5, label="reschedule")
    assert len(filtered) == 1
    assert filtered[0]["metadata"]["label"] == "reschedule"


def test_shared_configuration_is_not_modified(chroma_client, fake_ef, data_dir):
    # Regression: Chroma writes the embedding function into the configuration
    # dict it receives. If that were our shared constant, the next run would
    # silently reuse this run's embedding function.
    before = copy.deepcopy(config.COLLECTION_CONFIGURATION)
    index(chroma_client, fake_ef, data_dir)
    assert config.COLLECTION_CONFIGURATION == before
