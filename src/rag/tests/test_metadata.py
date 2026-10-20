"""Chunk metadata: every field present, no None values, correct epoch seconds."""

from datetime import datetime, timezone

import pytest

from chunking import chunk_message, sender_display_name, timestamp_to_epoch
from helpers import long_body, make_message

EXPECTED_KEYS = {
    "message_id",
    "user_id",
    "thread_id",
    "sender",
    "sender_name",
    "timestamp",
    "timestamp_epoch",
    "source",
    "subject",
    "label",
    "chunk_index",
}


def test_metadata_has_every_field_and_no_none(sample_messages):
    for message in sample_messages + [make_message(body=long_body())]:
        for chunk in chunk_message(message):
            metadata = chunk["metadata"]
            assert set(metadata) == EXPECTED_KEYS
            for key, value in metadata.items():
                assert value is not None, key
                # Chroma metadata must be scalars.
                assert isinstance(value, (str, int, float, bool)), key
            assert isinstance(metadata["timestamp_epoch"], int)
            assert isinstance(metadata["chunk_index"], int)


def test_metadata_copies_message_fields():
    metadata = chunk_message(make_message())[0]["metadata"]
    assert metadata["message_id"] == "abc123def4567890"
    assert metadata["user_id"] == "user_01"
    assert metadata["thread_id"] == "t001"
    assert metadata["sender"] == "Jordan Lee <EMAIL_003>"
    assert metadata["sender_name"] == "Jordan Lee"
    assert metadata["subject"] == "Interview"
    assert metadata["label"] == "new_request"
    assert metadata["source"] == "generated"


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-10-13T09:12:00-04:00",  # Eastern daylight time
        "2026-10-13T13:12:00+00:00",  # UTC written as an offset
        "2026-10-13T13:12:00Z",  # UTC written as Z
        "2026-10-13T22:12:00+09:00",  # Tokyo
        "2026-10-13T18:42:00+05:30",  # India (half-hour offset)
    ],
)
def test_timestamp_epoch_applies_the_utc_offset(timestamp):
    # All of these are the same moment: 13:12 UTC on 2026-10-13.
    expected = int(datetime(2026, 10, 13, 13, 12, tzinfo=timezone.utc).timestamp())
    assert timestamp_to_epoch(timestamp) == expected


def test_timestamp_epoch_orders_by_real_time_not_string():
    # As strings, "09:00-04:00" sorts before "12:00+00:00", but it is
    # actually later (13:00 UTC vs 12:00 UTC).
    later = "2026-10-13T09:00:00-04:00"
    earlier = "2026-10-13T12:00:00+00:00"
    assert later < earlier  # string order is misleading
    assert timestamp_to_epoch(later) > timestamp_to_epoch(earlier)


def test_empty_timestamp_gives_epoch_zero():
    assert timestamp_to_epoch("") == 0
    assert chunk_message(make_message(timestamp=""))[0]["metadata"]["timestamp_epoch"] == 0


@pytest.mark.parametrize(
    "sender, expected",
    [
        ("Jordan Lee <EMAIL_003>", "Jordan Lee"),
        ("<EMAIL_005>", ""),
        ("  <EMAIL_005>", ""),
        ('"Lee, Jordan" <EMAIL_003>', "Lee, Jordan"),
        ("Career Services Office <EMAIL_1234567>", "Career Services Office"),  # any placeholder width
        ("", ""),
    ],
)
def test_sender_display_name(sender, expected):
    assert sender_display_name(sender) == expected


def test_sender_without_display_name_gives_empty_sender_name():
    metadata = chunk_message(make_message(sender="<EMAIL_005>"))[0]["metadata"]
    assert metadata["sender_name"] == ""
    assert metadata["sender"] == "<EMAIL_005>"
