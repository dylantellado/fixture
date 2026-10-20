"""The query tool's output formats and argument checks."""

import pytest

import query

RESULT = {
    "id": "0ed574b41b112de0-0",
    "text": "From: Jordan Lee\nSubject: Re: Interview\nDate: 2026-10-13T15:05:00-04:00\n\nTuesday at 2:30 pm.",
    "score": 0.8123,
    "metadata": {
        "message_id": "0ed574b41b112de0",
        "user_id": "user_01",
        "thread_id": "t001",
        "sender": "Jordan Lee <EMAIL_003>",
        "sender_name": "Jordan Lee",
        "timestamp": "2026-10-13T15:05:00-04:00",
        "timestamp_epoch": 1792004700,
        "source": "generated",
        "subject": "Re: Interview",
        "label": "acceptance",
        "chunk_index": 0,
    },
}

COLLECTION_METADATA = {
    "user_name": "Priya Shah",
    "embedding_model": "all-MiniLM-L6-v2",
    "input_path": "/samples/messages_sample.jsonl",
    "input_sha256": "abc",
    "indexed_at": "2026-10-19T14:00:00+00:00",
    "used_sample_data": True,
}


def test_markdown_lists_query_user_and_each_result():
    text = query.format_markdown("When is my interview?", "user_01", COLLECTION_METADATA, [RESULT], 5, None)
    assert "**Query:** When is my interview?" in text
    assert "`user_01` (Priya Shah)" in text
    assert "## 1. Re: Interview (score 0.812)" in text
    assert "| `Jordan Lee <EMAIL_003>` | 2026-10-13T15:05:00-04:00 | `acceptance` |" in text
    assert "Tuesday at 2:30 pm." in text
    assert "sample data" in text


def test_plain_output_shows_score_sender_and_text():
    text = query.format_plain([RESULT])
    assert "score 0.812" in text and "[acceptance]" in text and "Jordan Lee <EMAIL_003>" in text
    assert "| Tuesday at 2:30 pm." in text
    assert query.format_plain([]) == "No results."


def test_rejects_bad_user_and_label():
    with pytest.raises(SystemExit, match="Invalid --user"):
        query.main(["--user", "User-01", "hello"])
    with pytest.raises(SystemExit):
        query.parse_args(["--user", "user_01", "hello", "--label", "meeting"])
