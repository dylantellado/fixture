"""Check thread files from the command line.

Usage (from src/ingest):
    uv run python validate.py FILE [FILE ...] --users ../../data/source/users.json [--generated]

Runs the Data contract checks from validation.py on every thread. With
--generated it also applies the fake-corpus rules from
docs/data/generation/corpus_plan.md (fictional domains, date window, time
zones, thread id format). Prints every problem and a label count, and exits
with code 1 if any errors were found.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from validation import address_of, parse_timestamp, validate_thread

# --- Fake-corpus rules (corpus_plan.md) ---

THREAD_ID_PATTERN = re.compile(r"^t\d{3}$")
# "Tue, 13 Oct 2026 09:12:00 -0400"
DATE_HEADER_PATTERN = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$")
ALLOWED_OFFSETS = {"-0400", "-0500", "-0700", "+0100", "+0200", "+0530"}
FIRST_DAY = datetime(2026, 9, 1, tzinfo=timezone.utc)
LAST_DAY = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)  # Oct 18 in every zone used

# Phone numbers the plan allows: US 555-01xx, UK 020 7946 0xxx, UK mobile 07700 900xxx.
PHONE_LIKE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{7,}\d(?![\w-])")
FICTIONAL_PHONE = re.compile(r"555[ .-]?01\d\d|7946[ .-]?0\d{3}|7700[ .-]?900\d{3}")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")


def is_fictional_address(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1]
    return domain == "example.com" or domain.endswith(".example")


def generated_corpus_errors(thread: dict) -> tuple[list[str], list[str]]:
    """Extra rules for the fake corpus. Returns (errors, warnings)."""
    where = f"{thread['user_id']}/{thread['thread_id']}"
    errors, warnings = [], []

    if not THREAD_ID_PATTERN.match(thread["thread_id"]):
        errors.append(f"{where}: thread_id should look like t001")

    for person in thread["participants"]:
        if not is_fictional_address(address_of(person)):
            errors.append(f"{where}: {person!r} is not a fictional (.example) address")

    for position, message in enumerate(thread["messages"]):
        message_where = f"{where} msg {position}"
        stamp = message["timestamp"]
        if not DATE_HEADER_PATTERN.match(stamp):
            errors.append(f"{message_where}: timestamp {stamp!r} is not 'Ddd, DD Mon YYYY HH:MM:SS +HHMM'")
        elif stamp[-5:] not in ALLOWED_OFFSETS:
            errors.append(f"{message_where}: offset {stamp[-5:]} is not one the plan uses")
        else:
            sent = parse_timestamp(stamp)
            if sent.strftime("%a") != stamp[:3]:
                errors.append(f"{message_where}: {stamp[:3]} is the wrong weekday for that date")
            if not FIRST_DAY <= sent <= LAST_DAY:
                errors.append(f"{message_where}: sent outside Sep 1 to Oct 18, 2026")

        # Addresses written inside the body must be fictional too.
        for address in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", message["body"]):
            if not is_fictional_address(address.lower()):
                errors.append(f"{message_where}: body address {address!r} is not fictional")

        # Phone-looking numbers should come from the fictional ranges. This is
        # only a warning, since dates and order numbers can look like phones.
        for candidate in PHONE_LIKE.findall(message["body"]):
            digits = re.sub(r"\D", "", candidate)
            if len(digits) >= 10 and not FICTIONAL_PHONE.search(candidate) and not DATE_LIKE.match(candidate.strip()):
                warnings.append(f"{message_where}: {candidate!r} looks like a non-fictional phone number")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate thread JSONL files.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--users", type=Path, required=True, help="path to users.json")
    parser.add_argument("--generated", action="store_true", help="also apply the fake-corpus rules")
    args = parser.parse_args()

    users = json.loads(args.users.read_text())
    known_user_ids = {user["user_id"] for user in users}

    errors, warnings = [], []
    labels = Counter()
    seen_ids = Counter()
    thread_count = 0

    for path in args.files:
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                thread = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(f"{path.name} line {line_number}: invalid JSON ({error})")
                continue

            thread_errors = validate_thread(thread, known_user_ids)
            errors.extend(f"{path.name}: {e}" for e in thread_errors)
            if thread_errors:
                continue

            thread_count += 1
            seen_ids[(thread["user_id"], thread["thread_id"])] += 1
            labels.update(message["label"] for message in thread["messages"])

            if args.generated:
                corpus_errors, corpus_warnings = generated_corpus_errors(thread)
                errors.extend(f"{path.name}: {e}" for e in corpus_errors)
                warnings.extend(f"{path.name}: {w}" for w in corpus_warnings)

    for (user_id, thread_id), count in seen_ids.items():
        if count > 1:
            errors.append(f"{user_id}/{thread_id}: appears {count} times")

    for warning in warnings:
        print(f"WARNING {warning}")
    for error in errors:
        print(f"ERROR   {error}")

    print(f"\n{thread_count} valid threads, {sum(labels.values())} messages")
    for label, count in labels.most_common():
        print(f"  {label:18} {count}")
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
