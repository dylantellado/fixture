"""Turn a raw email body into clean text: no quoted replies, signatures or footers.

clean_body() runs the steps below in order. Each step is a small function
so it can be tested and explained on its own. The rules are based on the
patterns in our corpus (see docs/data/generation/corpus_plan.md, "Cleanup
features"); real email will need more of them over time.
"""

import re

# --- Forwards -----------------------------------------------------------------

# "---------- Forwarded message ---------" followed by From/Date/Subject/To lines.
FORWARD_HEADER = re.compile(
    r"^-{2,}\s*Forwarded message\s*-{2,}\s*\n"  # the marker line
    r"((?:(?:From|Date|Sent|Subject|To|Cc):[^\n]*\n)+)",  # the header lines
    re.IGNORECASE | re.MULTILINE,
)


def simplify_forwards(text: str) -> str:
    """Keep forwarded text (it is often the real content), but shrink its header to one line."""

    def one_line(match: re.Match) -> str:
        sender = re.search(r"^From:\s*(.*)$", match.group(1), re.MULTILINE)
        # Keep just the display name ("Tidewell <updates@...>" -> "Tidewell").
        name = re.sub(r"\s*<[^>]*>", "", sender.group(1)).strip() if sender else ""
        return f"Forwarded message from {name}:\n" if name else "Forwarded message:\n"

    return FORWARD_HEADER.sub(one_line, text)


# --- Quoted replies -----------------------------------------------------------

# Where the earlier messages start. Everything from the first match onward is cut.
QUOTE_STARTS = [
    re.compile(r"^On .{5,200}wrote:\s*$", re.MULTILINE | re.DOTALL),  # Gmail / Apple Mail (may wrap onto 2 lines)
    re.compile(r"^-{3,}\s*Original Message\s*-{3,}\s*$", re.MULTILINE | re.IGNORECASE),  # older Outlook
    re.compile(r"^_{8,}\s*\n(?=From:)", re.MULTILINE),  # Outlook: a line of underscores, then From:
    re.compile(r"^From: [^\n]+\n(?:Sent|Date): ", re.MULTILINE),  # Outlook header block without the line
]


def cut_quoted_history(text: str) -> str:
    """Remove the quoted earlier messages at the bottom of a reply, and any '>' lines."""
    starts = [m.start() for pattern in QUOTE_STARTS if (m := pattern.search(text))]
    if starts:
        text = text[: min(starts)]
    # Inline quotes ("> earlier text") anywhere else.
    return "\n".join(line for line in text.split("\n") if not line.lstrip().startswith(">"))


# --- Footers ------------------------------------------------------------------

MOBILE_FOOTER = re.compile(r"^\s*(Sent from my \w+.*|Get Outlook for \w+.*|Sent from \w+ Mail.*)$", re.IGNORECASE)
# Paragraphs that are boilerplate, not something a person wrote.
BOILERPLATE = re.compile(
    r"confidential|intended (solely|only) for|received this (e-?mail|message) in error"
    r"|unsubscribe|you(?:'re| are) (getting|receiving) this",
    re.IGNORECASE,
)


def remove_footers(text: str) -> str:
    """Drop mobile footers, everything after a '--' signature marker, and boilerplate paragraphs."""
    lines = [line for line in text.split("\n") if not MOBILE_FOOTER.match(line)]
    # "-- " on its own line is the standard signature separator.
    for index, line in enumerate(lines):
        if line.strip() in ("--", "-- "):
            lines = lines[:index]
            break
    paragraphs = "\n".join(lines).split("\n\n")
    return "\n\n".join(p for p in paragraphs if not BOILERPLATE.search(p))


# --- Signatures ---------------------------------------------------------------

# Closing lines seen in the corpus. Matched against a whole line, so "Thanks
# for your help." in the middle of an email doesn't count.
SIGN_OFF = re.compile(
    r"^((with )?(kind|warm|warmest|best) regards|regards|best( wishes)?|all the best|warmly|sincerely|love"
    r"|(many )?thanks( so much| again)?|thank you( so much| again)?|cheers|take care|good luck|safe travels"
    r"|talk soon|speak soon|see you( then| soon| there)?|viele gr(ü|ue)(ß|ss)e|liebe gr(ü|ue)(ß|ss)e)[,.!]?$",
    re.IGNORECASE,
)


def remove_signature(text: str, sender_name: str) -> str:
    """Keep the sign-off and name ("Best,\\nDana"), drop the title/phone lines after them.

    Two rules:
      1. A short final paragraph whose first line has the sender's name is a
         signature block ("Rohan Mehta\\nAssociate...\\n+44..."): drop it.
      2. After the last sign-off line ("Best regards,"), keep one more line
         (the name) and drop the rest.
    """
    paragraphs = text.rstrip().split("\n\n")
    last_block = paragraphs[-1].strip().split("\n")
    if (
        len(paragraphs) > 1
        and sender_name
        and sender_name.lower() in last_block[0].lower()  # "The Graduate Career Office" counts too
        and len(last_block) <= 6
    ):
        paragraphs = paragraphs[:-1]
    lines = "\n\n".join(paragraphs).split("\n")

    # Only look for a sign-off near the end, so "Thanks!" in the middle is safe.
    for index in range(len(lines) - 1, max(len(lines) - 8, -1), -1):
        if SIGN_OFF.match(lines[index].strip()):
            return "\n".join(lines[: index + 2])
    return "\n".join(lines)


# --- Whitespace ---------------------------------------------------------------


def normalize_whitespace(text: str) -> str:
    """Trim lines, squash repeated spaces, and keep at most one blank line in a row."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_body(body: str, sender_name: str = "") -> str:
    """All cleaning steps, in order. `sender_name` is the display name of the sender."""
    text = normalize_whitespace(body)
    text = simplify_forwards(text)
    text = cut_quoted_history(text)
    text = remove_footers(text)
    text = remove_signature(text, sender_name)
    return normalize_whitespace(text)
