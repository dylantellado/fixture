"""Turn messages into chunks: the text to embed plus its metadata.

Two kinds of chunks go into each user's collection (metadata "chunk_type"):

- message: one per message (long bodies split into overlapping pieces). The
  text starts with the thread subject, sender and date, then a short excerpt
  of the message it replies to, then the body:

      Subject: Larkmoor Capital: Superday invitation
      From: Priya Shah
      Date: 2026-10-08T18:30:00-04:00
      Replying to Tess Navarro: Hi Priya, Congratulations! Please choose one of ...

      Hi Tess, Thank you. I'd like Friday, October 16 at 9:00 am. Best, Priya

  The excerpt is what makes a short reply ("Friday works") findable: on its
  own it says nothing about what is on Friday.

- thread: one per thread (long threads split into overlapping windows of
  messages): subject, participants, and each message's sender, date and
  first lines. A question about a whole conversation ("when is my superday?")
  matches it even when no single message says everything.

Search (message_search.py) always returns messages, never thread chunks.
"""

from datetime import datetime

import config

MESSAGE = "message"
THREAD = "thread"


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


def display_name(address: str) -> str:
    """The display name, or the raw address (e.g. "<EMAIL_005>") when there is none."""
    return sender_display_name(address) or address


def timestamp_to_epoch(timestamp: str) -> int:
    """Convert an ISO 8601 timestamp with a UTC offset to Unix seconds.

    The offset is applied, so 09:00-04:00 and 13:00+00:00 give the same number.
    Use this (not the timestamp string) for sorting and date filters.
    Returns 0 for "" (timestamp unknown). Inputs are validated beforehand.
    """
    if timestamp == "":
        return 0
    return int(datetime.fromisoformat(timestamp).timestamp())


def excerpt(text: str, limit: int) -> str:
    """The first ~limit characters of text on one line, cut at a space, with "…" if shortened."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit)
    return flat[: cut if cut > 0 else limit] + "…"


def chunk_header(message: dict) -> str:
    """The header that starts every chunk of a message: thread subject, sender, date."""
    return (
        f"Subject: {message['subject']}\n"
        f"From: {display_name(message['sender'])}\n"
        f"Date: {message['timestamp']}"
    )


def reply_line(previous: dict) -> str:
    """One line quoting the start of the message this one replies to."""
    return f"Replying to {display_name(previous['sender'])}: {excerpt(previous['body'], config.REPLY_EXCERPT_CHARS)}"


def _last_whitespace(text: str, start: int, end: int) -> int:
    """Index of the last space or newline in text[start:end], or -1."""
    return max(text.rfind(" ", start, end), text.rfind("\n", start, end))


def split_body(body: str, size: int, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
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


def chunk_message(message: dict, previous: dict | None = None) -> list[dict]:
    """Make the message chunks for one message.

    previous is the message just before it in the thread (None for the first).
    Each chunk is {"id", "text", "metadata"}. The id is
    "<message_id>-<chunk index>", so it is the same on every run. Every piece
    of a long body repeats the header and reply line, and the body pieces are
    sized so the whole chunk stays within config.CHUNK_MAX_CHARS.
    Metadata values are all strings or ints, never None (Chroma rejects None).
    """
    prefix = chunk_header(message)
    if previous is not None:
        prefix += "\n" + reply_line(previous)
    body_size = max(config.CHUNK_MAX_CHARS - len(prefix) - 2, config.MIN_BODY_CHARS)

    base_metadata = {
        "chunk_type": MESSAGE,
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
    return [
        {
            "id": f"{message['message_id']}-{index}",
            "text": f"{prefix}\n\n{piece}",
            "metadata": {**base_metadata, "chunk_index": index},
        }
        for index, piece in enumerate(split_body(message["body"], body_size))
    ]


def participants(messages: list[dict]) -> list[str]:
    """Everyone who sent or received a message in the thread, in order of first appearance."""
    names = []
    for message in messages:
        for address in [message["sender"], *message["recipients"]]:
            name = display_name(address)
            if name not in names:
                names.append(name)
    return names


def thread_windows(lines: list[str], budget: int, overlap: int = config.THREAD_WINDOW_OVERLAP) -> list[tuple[int, int]]:
    """Group consecutive lines into windows of at most `budget` characters.

    Returns (start, end) index pairs. Neighboring windows share `overlap`
    lines, so a question about two neighboring messages still finds both in
    one window. A window always holds at least one line and always moves
    forward, so this ends even if a line alone is over the budget.
    """
    windows = []
    start = 0
    while start < len(lines):
        end, size = start + 1, len(lines[start])
        while end < len(lines) and size + 1 + len(lines[end]) <= budget:
            size += 1 + len(lines[end])
            end += 1
        windows.append((start, end))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return windows


def chunk_thread_overview(messages: list[dict]) -> list[dict]:
    """Make the thread chunks for one thread (messages in thread order).

    Text: "Thread: <subject>", "Participants: ...", then one line per message:
    "- <sender>, <date>: <first lines of the body>". Threads too long for one
    chunk are split into overlapping windows of whole messages; each window
    repeats the subject and participants. Ids: "thread-<thread_id>-<window>".
    Metadata lists the window's message_ids (comma-separated, since Chroma
    metadata values can't be lists).
    """
    first = messages[0]
    header = f"Thread: {first['subject']}\nParticipants: {', '.join(participants(messages))}"
    budget = max(config.THREAD_WINDOW_MAX_CHARS - len(header) - 2, config.MIN_BODY_CHARS)
    line_chars = min(config.THREAD_LINE_CHARS, budget)
    lines = [
        f"- {display_name(m['sender'])}, {m['timestamp']}: {excerpt(m['body'], line_chars)}"
        for m in messages
    ]

    chunks = []
    for index, (start, end) in enumerate(thread_windows(lines, budget)):
        window = messages[start:end]
        chunks.append(
            {
                "id": f"thread-{first['thread_id']}-{index}",
                "text": header + "\n\n" + "\n".join(lines[start:end]),
                "metadata": {
                    "chunk_type": THREAD,
                    "user_id": first["user_id"],
                    "thread_id": first["thread_id"],
                    "subject": first["subject"],
                    "source": first["source"],
                    "message_ids": ",".join(m["message_id"] for m in window),
                    "message_count": len(window),
                    "timestamp": window[0]["timestamp"],
                    "timestamp_epoch": timestamp_to_epoch(window[0]["timestamp"]),
                    "chunk_index": index,
                },
            }
        )
    return chunks


def group_threads(messages: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group messages by (user_id, thread_id), keeping file order.

    preprocess writes each thread's messages in thread order (position 0
    first; see the Data contract), so file order is reply order.
    """
    threads: dict[tuple[str, str], list[dict]] = {}
    for message in messages:
        threads.setdefault((message["user_id"], message["thread_id"]), []).append(message)
    return threads


def chunk_thread(messages: list[dict]) -> list[dict]:
    """All chunks for one thread: each message's chunks, then the thread chunks."""
    chunks = []
    for position, message in enumerate(messages):
        chunks.extend(chunk_message(message, previous=messages[position - 1] if position else None))
    return chunks + chunk_thread_overview(messages)
