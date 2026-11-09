"""Chunking: contextual message chunks, thread chunks and windows, size limits."""

import pytest

import config
from chunking import (
    chunk_header,
    chunk_message,
    chunk_thread,
    chunk_thread_overview,
    excerpt,
    group_threads,
    participants,
    reply_line,
    split_body,
    thread_windows,
)
from helpers import long_body, make_message


def reply(body="Tuesday works for me.", **overrides):
    """A reply in the same thread as make_message()."""
    defaults = {
        "message_id": "bbbbbbbbbbbbbbbb",
        "sender": "Priya Shah <EMAIL_001>",
        "recipients": ["Jordan Lee <EMAIL_003>"],
        "timestamp": "2026-10-13T10:00:00-04:00",
        "label": "acceptance",
    }
    return make_message(body=body, **{**defaults, **overrides})


# --- Message chunks ---------------------------------------------------------------


def test_first_message_has_header_then_body():
    chunks = chunk_message(make_message())
    assert len(chunks) == 1
    assert chunks[0]["text"] == (
        "Subject: Interview\n"
        "From: Jordan Lee\n"
        "Date: 2026-10-13T09:12:00-04:00\n"
        "\n"
        "Can we meet Tuesday at 2pm?"
    )
    assert chunks[0]["id"] == "abc123def4567890-0"
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[0]["metadata"]["chunk_type"] == "message"


def test_reply_quotes_the_previous_message():
    chunks = chunk_message(reply(), previous=make_message())
    assert chunks[0]["text"] == (
        "Subject: Interview\n"
        "From: Priya Shah\n"
        "Date: 2026-10-13T10:00:00-04:00\n"
        "Replying to Jordan Lee: Can we meet Tuesday at 2pm?\n"
        "\n"
        "Tuesday works for me."
    )


def test_reply_excerpt_is_short_and_on_one_line():
    previous = make_message(body="Line one.\n\n" + long_body(200))
    line = reply_line(previous)
    quoted = line.removeprefix("Replying to Jordan Lee: ")
    assert "\n" not in line
    assert quoted.startswith("Line one. word0 word1")
    assert quoted.endswith("…")
    assert len(quoted) <= config.REPLY_EXCERPT_CHARS + 1  # plus the "…"


def test_excerpt_cuts_at_a_space():
    assert excerpt("short text", 50) == "short text"
    assert excerpt("alpha beta gamma", 12) == "alpha beta…"
    assert excerpt("a\n\nb   c", 50) == "a b c"


def test_header_falls_back_to_raw_sender_without_display_name():
    chunks = chunk_message(make_message(sender="<EMAIL_005>"))
    assert "\nFrom: <EMAIL_005>\n" in chunks[0]["text"]
    chunks = chunk_message(reply(), previous=make_message(sender="<EMAIL_005>"))
    assert "Replying to <EMAIL_005>: " in chunks[0]["text"]


def test_long_body_pieces_repeat_the_prefix_and_fit_the_limit():
    previous = make_message()
    chunks = chunk_message(reply(body=long_body(600)), previous=previous)
    prefix = chunk_header(reply()) + "\n" + reply_line(previous) + "\n\n"

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["text"].startswith(prefix)
        assert len(chunk["text"]) <= config.CHUNK_MAX_CHARS
    # No words are lost: every word of the body appears in some piece.
    words = {w for c in chunks for w in c["text"][len(prefix):].split()}
    assert words == set(long_body(600).split())


def test_chunk_ids_are_stable_and_numbered():
    message = make_message(body=long_body(600))
    first, second = chunk_message(message), chunk_message(message)
    assert [c["id"] for c in first] == [c["id"] for c in second]
    assert [c["id"] for c in first] == [f"abc123def4567890-{i}" for i in range(len(first))]
    assert [c["metadata"]["chunk_index"] for c in first] == list(range(len(first)))


def test_empty_body_still_gets_a_chunk():
    chunks = chunk_message(make_message(body=""))
    assert len(chunks) == 1
    assert chunks[0]["text"].endswith("Date: 2026-10-13T09:12:00-04:00\n\n")


# --- split_body --------------------------------------------------------------------


def test_body_exactly_the_size_is_not_split():
    assert split_body("x" * 500, 500) == ["x" * 500]


def test_long_body_splits_into_overlapping_pieces():
    body = long_body()
    pieces = split_body(body, 1000)

    assert len(pieces) > 1
    for piece in pieces:
        assert len(piece) <= 1000
    for earlier, later in zip(pieces, pieces[1:]):
        # The next piece starts inside the previous one (the overlap)...
        first_word = later.split()[0]
        assert first_word in earlier.split()
        # ...and the overlap is roughly CHUNK_OVERLAP characters, not the whole piece.
        overlap = earlier[earlier.index(f" {first_word} ") + 1 :]
        assert 0.5 * config.CHUNK_OVERLAP <= len(overlap) <= config.CHUNK_OVERLAP
    # No words are lost or broken.
    assert set(word for piece in pieces for word in piece.split()) == set(body.split())
    for piece in pieces:
        assert all(word.startswith("word") and word[4:].isdigit() for word in piece.split())


def test_split_handles_text_without_spaces():
    # No whitespace to cut at, so it falls back to fixed-size cuts.
    pieces = split_body("a" * 2500, 1000)
    assert all(len(p) <= 1000 for p in pieces)
    assert len(pieces) == 3


# --- Thread chunks -------------------------------------------------------------------


def test_thread_chunk_lists_subject_participants_and_each_message():
    thread = [make_message(), reply()]
    chunks = chunk_thread_overview(thread)

    assert len(chunks) == 1
    assert chunks[0]["id"] == "thread-t001-0"
    assert chunks[0]["text"] == (
        "Thread: Interview\n"
        "Participants: Jordan Lee, Priya Shah\n"
        "\n"
        "- Jordan Lee, 2026-10-13T09:12:00-04:00: Can we meet Tuesday at 2pm?\n"
        "- Priya Shah, 2026-10-13T10:00:00-04:00: Tuesday works for me."
    )
    metadata = chunks[0]["metadata"]
    assert metadata["chunk_type"] == "thread"
    assert metadata["thread_id"] == "t001"
    assert metadata["message_ids"] == "abc123def4567890,bbbbbbbbbbbbbbbb"
    assert metadata["message_count"] == 2
    assert all(value is not None for value in metadata.values())


def test_participants_include_recipients_once_in_order():
    thread = [
        make_message(recipients=["Priya Shah <EMAIL_001>", "Tess Navarro <EMAIL_009>"]),
        reply(recipients=["Jordan Lee <EMAIL_003>", "<EMAIL_010>"]),
    ]
    assert participants(thread) == ["Jordan Lee", "Priya Shah", "Tess Navarro", "<EMAIL_010>"]


def test_thread_lines_show_only_the_first_lines_of_each_message():
    chunks = chunk_thread_overview([make_message(body=long_body(400))])
    line = chunks[0]["text"].split("\n")[-1]
    assert line.endswith("…")
    assert len(line) < config.THREAD_LINE_CHARS + 60  # sender and date come first


def test_thread_windows_overlap_by_one_and_cover_everything():
    lines = ["x" * 30] * 10
    windows = thread_windows(lines, budget=100, overlap=1)
    # 3 lines of 30 characters (plus newlines) fit in 100.
    assert windows == [(0, 3), (2, 5), (4, 7), (6, 9), (8, 10)]


def test_thread_windows_always_move_forward():
    # Every line alone is over the budget: one line per window, no endless loop.
    assert thread_windows(["x" * 50] * 3, budget=10, overlap=1) == [(0, 1), (1, 2), (2, 3)]


def test_long_thread_is_split_into_windows_within_the_limit():
    thread = [
        make_message(message_id=f"{i:016x}", body=long_body(100), timestamp=f"2026-10-13T{9 + i:02d}:00:00-04:00")
        for i in range(12)
    ]
    chunks = chunk_thread_overview(thread)

    assert len(chunks) > 1
    assert [c["id"] for c in chunks] == [f"thread-t001-{i}" for i in range(len(chunks))]
    covered = []
    for chunk in chunks:
        assert len(chunk["text"]) <= config.CHUNK_MAX_CHARS
        assert chunk["text"].startswith("Thread: Interview\nParticipants: ")  # header on every window
        covered += chunk["metadata"]["message_ids"].split(",")
    # Every message is in some window; neighbors share one message.
    assert set(covered) == {m["message_id"] for m in thread}
    for earlier, later in zip(chunks, chunks[1:]):
        assert earlier["metadata"]["message_ids"].split(",")[-1] == later["metadata"]["message_ids"].split(",")[0]


# --- Whole threads ---------------------------------------------------------------------


def test_chunk_thread_gives_message_chunks_with_context_then_thread_chunks():
    first, second = make_message(), reply()
    chunks = chunk_thread([first, second])

    assert [c["id"] for c in chunks] == ["abc123def4567890-0", "bbbbbbbbbbbbbbbb-0", "thread-t001-0"]
    assert "Replying to" not in chunks[0]["text"]  # the first message replies to nothing
    assert "Replying to Jordan Lee: Can we meet" in chunks[1]["text"]


def test_group_threads_keeps_file_order_per_thread():
    messages = [
        make_message(message_id="1" * 16, thread_id="t001"),
        make_message(message_id="2" * 16, thread_id="t002"),
        make_message(message_id="3" * 16, thread_id="t001"),
        make_message(message_id="4" * 16, thread_id="t001", user_id="user_02"),
    ]
    groups = group_threads(messages)
    assert [m["message_id"] for m in groups[("user_01", "t001")]] == ["1" * 16, "3" * 16]
    assert [m["message_id"] for m in groups[("user_01", "t002")]] == ["2" * 16]
    # Same thread_id, different user: a different thread.
    assert [m["message_id"] for m in groups[("user_02", "t001")]] == ["4" * 16]


@pytest.mark.parametrize("body_words", [0, 5, 600])
def test_every_chunk_fits_the_limit(body_words):
    thread = [make_message(body=long_body(body_words)), reply(body=long_body(body_words))]
    for chunk in chunk_thread(thread):
        assert len(chunk["text"]) <= config.CHUNK_MAX_CHARS
