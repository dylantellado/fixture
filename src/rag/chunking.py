"""Turn messages into chunks: the text to embed plus its metadata.

One chunk per message. Each chunk's text starts with a short header (sender,
subject, date) so a question that names a contact or topic matches that
contact's emails even when the body doesn't repeat the name. Long bodies are
split into overlapping pieces, and every piece gets the same header.
"""

from datetime import datetime

import config


def sender_display_name(sender: str) -> str:
    """Return the display name from "Display Name <placeholder>", or "".

    "Jordan Lee <EMAIL_003>" -> "Jordan Lee"
    "<EMAIL_005>"            -> ""
    The placeholder inside <...> is treated as opaque text and never parsed.
    """
    if "<" not in sender:
        return ""
    name = sender[: sender.rfind("<")]
    return name.strip().strip('"').strip()


def timestamp_to_epoch(timestamp: str) -> int:
    """Convert an ISO 8601 timestamp with a UTC offset to Unix seconds.

    The offset is applied, so 09:00-04:00 and 13:00+00:00 give the same number.
    Use this (not the timestamp string) for sorting and date filters.
    Returns 0 for "" (timestamp unknown). Inputs are validated beforehand.
    """
    if timestamp == "":
        return 0
    return int(datetime.fromisoformat(timestamp).timestamp())


def chunk_header(message: dict) -> str:
    """The header that starts every chunk of a message."""
    # Fall back to the raw sender (e.g. "<EMAIL_005>") when there is no display name.
    sender = sender_display_name(message["sender"]) or message["sender"]
    return f"From: {sender}\nSubject: {message['subject']}\nDate: {message['timestamp']}"


def _last_whitespace(text: str, start: int, end: int) -> int:
    """Index of the last space or newline in text[start:end], or -1."""
    return max(text.rfind(" ", start, end), text.rfind("\n", start, end))


def split_body(body: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Split a body into pieces of at most `size` characters.

    Neighboring pieces share about `overlap` characters. Cuts happen at
    whitespace when possible so words aren't broken in half. A body that
    already fits is returned as a single piece.
    """
    if len(body) <= size:
        return [body]

    pieces = []
    start = 0
    while True:
        end = min(start + size, len(body))
        if end < len(body):
            # Back up to a space, but keep the piece longer than the overlap
            # so the next piece always starts further along (no endless loop).
            cut = _last_whitespace(body, start + overlap + 1, end)
            if cut != -1:
                end = cut
        pieces.append(body[start:end].strip())
        if end >= len(body):
            break
        # Start the next piece `overlap` characters before this one ended,
        # moved forward to the next word boundary if it lands mid-word.
        start = end - overlap
        if not body[start - 1].isspace():
            space = body.find(" ", start, end)
            if space != -1:
                start = space + 1
    return pieces


def chunk_message(message: dict) -> list[dict]:
    """Make the chunks for one message.

    Each chunk is {"id", "text", "metadata"}. The id is
    "<message_id>-<chunk index>", so it is the same on every run.
    Metadata values are all strings or ints, never None (Chroma rejects None).
    """
    header = chunk_header(message)
    base_metadata = {
        "message_id": message["message_id"],
        "user_id": message["user_id"],
        "thread_id": message["thread_id"],
        "sender": message["sender"],
        "sender_name": sender_display_name(message["sender"]),
        "timestamp": message["timestamp"],
        "timestamp_epoch": timestamp_to_epoch(message["timestamp"]),
        "source": message["source"],
        "subject": message["subject"],
        "label": message["label"],
    }

    chunks = []
    for index, piece in enumerate(split_body(message["body"])):
        chunks.append(
            {
                "id": f"{message['message_id']}-{index}",
                "text": f"{header}\n\n{piece}",
                "metadata": {**base_metadata, "chunk_index": index},
            }
        )
    return chunks
