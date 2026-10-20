"""Checks that email threads match the Data contract (see README).

Each check returns a list of plain-English error strings. An empty list means
the thread is valid. Ingest uses these to reject bad records, and
validate.py runs them on a file from the command line.
"""

import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime

# The six labels from the Data contract.
ALLOWED_LABELS = {
    "new_request",
    "proposed_times",
    "acceptance",
    "reschedule",
    "assistant_handoff",
    "none",
}

# user_id becomes part of a ChromaDB collection name, so keep it simple.
USER_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

THREAD_FIELDS = ["user_id", "thread_id", "subject", "participants", "messages"]
MESSAGE_FIELDS = ["sender", "recipients", "timestamp", "body", "label"]


def parse_timestamp(value: str) -> datetime:
    """Parse an email "Date" header like "Tue, 13 Oct 2026 09:12:00 -0400".

    Raises ValueError if the text can't be parsed or has no time zone.
    """
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unparseable timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no time zone: {value!r}")
    return parsed


def is_address(value: str) -> bool:
    """True for "Name <someone@domain>" or "<someone@domain>"."""
    if not isinstance(value, str):
        return False
    _name, address = parseaddr(value)
    return "@" in address and "<" in value and value.rstrip().endswith(">")


def address_of(value: str) -> str:
    """The lowercase email address inside "Name <address>"."""
    return parseaddr(value)[1].lower()


def validate_message(message: dict, where: str) -> list[str]:
    """Check one message. `where` is a prefix for error text, e.g. "user_01/t003 msg 2"."""
    if not isinstance(message, dict):
        return [f"{where}: message is not a JSON object"]

    errors = []
    for field in MESSAGE_FIELDS:
        if field not in message:
            errors.append(f"{where}: missing field '{field}'")
    if errors:
        return errors

    if not is_address(message["sender"]):
        errors.append(f"{where}: sender {message['sender']!r} is not 'Name <address>'")

    recipients = message["recipients"]
    if not isinstance(recipients, list):
        errors.append(f"{where}: recipients must be a list")
    else:
        for recipient in recipients:
            if not is_address(recipient):
                errors.append(f"{where}: recipient {recipient!r} is not 'Name <address>'")

    try:
        parse_timestamp(message["timestamp"])
    except ValueError as error:
        errors.append(f"{where}: {error}")

    if not isinstance(message["body"], str) or not message["body"].strip():
        errors.append(f"{where}: body must be non-empty text")

    if message["label"] not in ALLOWED_LABELS:
        errors.append(f"{where}: label {message['label']!r} is not one of {sorted(ALLOWED_LABELS)}")

    return errors


def validate_thread(thread: dict, known_user_ids: set[str]) -> list[str]:
    """Check one thread: required fields, known user, and every message."""
    if not isinstance(thread, dict):
        return ["record is not a JSON object"]

    user_id = thread.get("user_id", "?")
    thread_id = thread.get("thread_id", "?")
    where = f"{user_id}/{thread_id}"

    errors = []
    for field in THREAD_FIELDS:
        if field not in thread:
            errors.append(f"{where}: missing field '{field}'")
    if errors:
        return errors

    if not isinstance(user_id, str) or not USER_ID_PATTERN.match(user_id):
        errors.append(f"{where}: user_id must be lowercase letters, digits and underscores")
    elif user_id not in known_user_ids:
        errors.append(f"{where}: unknown user_id (not in users.json)")

    if not isinstance(thread_id, str) or not thread_id.strip():
        errors.append(f"{where}: thread_id must be a non-empty string")

    if not isinstance(thread["subject"], str):
        errors.append(f"{where}: subject must be a string")

    participants = thread["participants"]
    if not isinstance(participants, list) or not all(is_address(p) for p in participants):
        errors.append(f"{where}: participants must be a list of 'Name <address>'")
        participants = []

    messages = thread["messages"]
    if not isinstance(messages, list) or not messages:
        errors.append(f"{where}: messages must be a non-empty list")
        return errors

    participant_addresses = {address_of(p) for p in participants}
    previous_time = None
    for position, message in enumerate(messages):
        message_where = f"{where} msg {position}"
        message_errors = validate_message(message, message_where)
        errors.extend(message_errors)
        if message_errors:
            continue

        # Messages may repeat the thread's user_id, but it must not disagree.
        if "user_id" in message and message["user_id"] != user_id:
            errors.append(f"{message_where}: user_id {message['user_id']!r} differs from the thread's")

        # Everyone who sends or receives must be listed as a participant.
        for person in [message["sender"], *message["recipients"]]:
            if address_of(person) not in participant_addresses:
                errors.append(f"{message_where}: {person!r} is not in participants")

        # Messages must be in time order.
        sent = parse_timestamp(message["timestamp"])
        if previous_time is not None and sent < previous_time:
            errors.append(f"{message_where}: timestamp is earlier than the message before it")
        previous_time = sent

    return errors
