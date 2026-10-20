"""Optional: index the samples with the real MiniLM model and check one search.

Skipped when the model can't be downloaded (e.g. offline). The first run
downloads about 80 MB to ~/.cache/chroma; later runs reuse it.
"""

import pytest

import config
import main
from helpers import SAMPLES_DIR
from index import search


@pytest.fixture(scope="module")
def real_ef():
    embedding_function = config.get_embedding_function()
    try:
        embedding_function(["warm up"])  # triggers the download if needed
    except Exception as e:
        pytest.skip(f"embedding model unavailable: {e}")
    return embedding_function


def test_real_model_finds_the_interview_confirmation(chroma_client, real_ef, data_dir):
    main.run(lambda: chroma_client, real_ef, data_dir=data_dir, samples_dir=SAMPLES_DIR)
    collection = chroma_client.get_collection("messages_user_01", embedding_function=real_ef)

    results = search(collection, "When is my Northbridge interview?", k=3)

    # All top results come from the Northbridge interview thread.
    assert [r["metadata"]["thread_id"] for r in results] == ["t001"] * 3
    assert all(0 < r["score"] <= 1 for r in results)
