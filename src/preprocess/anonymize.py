"""Replace email addresses and phone numbers with placeholders (EMAIL_001, PHONE_001).

There is ONE placeholder map for all users (Data contract rule), so the same
address always becomes the same placeholder, in every inbox. Display names
are kept, because search by contact depends on them.

Use it in two passes:
    anonymizer = Anonymizer()
    anonymizer.collect(text)          # for every piece of text first
    anonymizer.finalize()             # number everything, in sorted order
    anonymizer.replace(text)          # then replace

Numbering in sorted order (not "first seen") means the result doesn't depend
on which file or user happens to be read first.
"""

import re
from email.utils import parseaddr

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A digit, then digits / spaces / ( ) . - , ending in a digit. Filtered by
# digit count below, so dates ("2026-10-13") and times aren't caught.
PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d ().-]{7,}\d(?![\w-])")
MIN_PHONE_DIGITS, MAX_PHONE_DIGITS = 10, 13


def normalize_phone(text: str) -> str | None:
    """One canonical form per number, or None if it isn't a phone number.

    "(617) 555-0142", "617.555.0142" and "+1 617 555 0142" -> "6175550142"
    "+44 20 7946 0123", "+44 (0)20 7946 0123" and "020 7946 0123" -> "02079460123"
    """
    digits = re.sub(r"\D", "", text)
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return None
    if digits.startswith("44"):  # UK: country code -> national form with a leading 0
        return "0" + digits[2:].removeprefix("0")
    if len(digits) == 11 and digits.startswith("1"):  # US/Canada with country code
        return digits[1:]
    return digits


class Anonymizer:
    def __init__(self):
        self.emails = set()
        self.phones = set()
        self.email_map = {}  # lowercase address -> "EMAIL_001"
        self.phone_map = {}  # canonical number -> "PHONE_001"

    # --- pass 1 ---

    def collect(self, text: str) -> None:
        for address in EMAIL.findall(text):
            self.emails.add(address.lower())
        for candidate in PHONE.findall(text):
            canonical = normalize_phone(candidate)
            if canonical:
                self.phones.add(canonical)

    def finalize(self) -> None:
        # Three digits as agreed; wider automatically past 999 (Dylan treats them as opaque).
        width = max(3, len(str(max(len(self.emails), len(self.phones), 1))))
        self.email_map = {a: f"EMAIL_{i:0{width}d}" for i, a in enumerate(sorted(self.emails), start=1)}
        self.phone_map = {p: f"PHONE_{i:0{width}d}" for i, p in enumerate(sorted(self.phones), start=1)}

    # --- pass 2 ---

    def replace(self, text: str) -> str:
        """Swap every address and phone number in free text for its placeholder."""
        text = EMAIL.sub(lambda m: self.email_map[m.group(0).lower()], text)

        def phone(match: re.Match) -> str:
            canonical = normalize_phone(match.group(0))
            return self.phone_map[canonical] if canonical else match.group(0)

        return PHONE.sub(phone, text)

    def person(self, value: str) -> str:
        """'Jordan Lee <jordan.lee@larkmoor.example>' -> 'Jordan Lee <EMAIL_003>'."""
        name, address = parseaddr(value)
        placeholder = self.email_map[address.lower()]
        return f"{name} <{placeholder}>" if name else f"<{placeholder}>"
