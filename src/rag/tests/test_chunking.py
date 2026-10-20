"""Chunking: one chunk per message, long bodies split with overlap, header on each piece."""

import config
from chunking import chunk_header, chunk_message, split_body
from helpers import long_body, make_message


def test_short_body_is_one_chunk_with_header():
    chunks = chunk_message(make_message())
    assert len(chunks) == 1
    assert chunks[0]["text"] == (
        "From: Jordan Lee\n"
        "Subject: Interview\n"
        "Date: 2026-10-13T09:12:00-04:00\n"
        "\n"
        "Can we meet Tuesday at 2pm?"
    )
    assert chunks[0]["id"] == "abc123def4567890-0"
    assert chunks[0]["metadata"]["chunk_index"] == 0


def test_body_exactly_chunk_size_is_not_split():
    assert split_body("x" * config.CHUNK_SIZE) == ["x" * config.CHUNK_SIZE]


def test_long_body_splits_into_overlapping_pieces():
    body = long_body()
    pieces = split_body(body)

    assert len(pieces) > 1
    for piece in pieces:
        assert len(piece) <= config.CHUNK_SIZE

    for earlier, later in zip(pieces, pieces[1:]):
        # The next piece starts inside the previous one (the overlap)...
        first_word = later.split()[0]
        assert first_word in earlier.split()
        # ...and the overlap is roughly CHUNK_OVERLAP characters, not the whole piece.
        overlap = earlier[earlier.index(f" {first_word} ") + 1 :]
        assert 0.5 * config.CHUNK_OVERLAP <= len(overlap) <= config.CHUNK_OVERLAP

    # No words are lost or broken: every word appears whole in some piece.
    all_words = set(word for piece in pieces for word in piece.split())
    assert all_words == set(body.split())


def test_split_never_breaks_words():
    pieces = split_body(long_body())
    for piece in pieces:
        for word in piece.split():
            assert word.startswith("word") and word[4:].isdigit()


def test_split_handles_text_without_spaces():
    # No whitespace to cut at, so it falls back to fixed-size cuts.
    pieces = split_body("a" * 2500)
    assert all(len(p) <= config.CHUNK_SIZE for p in pieces)
    assert len(pieces) == 3


def test_header_is_repeated_on_every_piece():
    message = make_message(body=long_body())
    chunks = chunk_message(message)
    header = chunk_header(message)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["text"].startswith(header + "\n\n")


def test_chunk_ids_are_stable_and_numbered():
    message = make_message(body=long_body())
    first = chunk_message(message)
    second = chunk_message(message)

    assert [c["id"] for c in first] == [c["id"] for c in second]
    assert [c["id"] for c in first] == [f"abc123def4567890-{i}" for i in range(len(first))]
    assert [c["metadata"]["chunk_index"] for c in first] == list(range(len(first)))


def test_header_falls_back_to_raw_sender_without_display_name():
    chunks = chunk_message(make_message(sender="<EMAIL_005>"))
    assert chunks[0]["text"].startswith("From: <EMAIL_005>\n")


def test_empty_body_still_gets_a_chunk():
    chunks = chunk_message(make_message(body=""))
    assert len(chunks) == 1
    assert chunks[0]["text"].endswith("Date: 2026-10-13T09:12:00-04:00\n\n")
