"""Check a draft in code (no LLM) before anyone sees it.

The model proposes; this module decides. A draft is returned only if every
check passes (pipeline.py retries once with the failures explained, then gives
up with status "error"). The checks read only the model's answer, the
calendar and the rules, plus the current thread for one check (contact details
already in the thread may be repeated), so text in an email can't talk them
into passing.

Checks, in the order returned:
  answer_well_formed          the answer parsed: known slot ids, valid times with
                              UTC offsets, non-empty draft of reasonable length
  offered_times_allowed       every offered time follows the rules (slots.check_time)
  accepted_time_allowed       an accepted time follows the rules too
  confirmed_time_on_calendar  a meeting the draft confirms overlaps a busy event
                              (the calendar shows it)
  no_other_times_in_text      every date/time written in the draft is one of the
                              offered, accepted or confirmed times (mentions.py)
  times_written_in_text       every offered and accepted time is written in the
                              draft (day and time), so the text and the
                              structured answer agree
  no_outside_contact_details  every email address, link and phone number in the
                              draft already appears in this thread (nothing from
                              other threads or made up)
"""

import re
from dataclasses import dataclass, field

import mentions
import slots
from slots import Calendar, Interval

MAX_DRAFT_CHARS = 2500


@dataclass
class Check:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class DraftAnswer:
    """The model's answer after parsing (draft.parse_answer)."""

    action: str
    draft_text: str
    offered: list[Interval] = field(default_factory=list)  # from the slot ids it chose
    offered_ids: list[str] = field(default_factory=list)
    accepted: Interval | None = None
    confirmed: Interval | None = None
    context_used: list[dict] = field(default_factory=list)  # [{"id", "why"}], ids checked
    problems: list[str] = field(default_factory=list)  # parse problems, e.g. an unknown slot id


def run_checks(answer: DraftAnswer, cal: Calendar, thread_text: str, user_email: str = "") -> list[Check]:
    """All checks for one answer. thread_text is the current thread's headers and bodies."""
    tz, now = cal.tz, cal.now
    checks = []

    # 1. The answer itself.
    problems = list(answer.problems)
    if not answer.draft_text.strip():
        problems.append("the draft is empty")
    elif len(answer.draft_text) > MAX_DRAFT_CHARS:
        problems.append(f"the draft is longer than {MAX_DRAFT_CHARS} characters")
    checks.append(Check("answer_well_formed", not problems,
                        "; ".join(problems) if problems else "The answer is complete and every time in it is valid."))

    # 2. Offered times.
    bad = [f"{slots.format_interval(t, tz)}: {', '.join(reasons)}"
           for t in answer.offered if (reasons := slots.check_time(t.start, t.end, cal))]
    if not answer.offered:
        detail = "No times offered."
    elif bad:
        detail = "Not allowed: " + "; ".join(bad)
    else:
        detail = f"All {len(answer.offered)} offered times are free and follow your rules."
    checks.append(Check("offered_times_allowed", not bad, detail))

    # 3. An accepted time.
    if answer.accepted is None:
        checks.append(Check("accepted_time_allowed", True, "No time accepted."))
    else:
        reasons = slots.check_time(answer.accepted.start, answer.accepted.end, cal)
        label = slots.format_interval(answer.accepted, tz)
        checks.append(Check("accepted_time_allowed", not reasons,
                            f"Not allowed: {label}: {', '.join(reasons)}" if reasons
                            else f"{label} is free and follows your rules."))

    # 4. A confirmed existing meeting must be on the calendar.
    if answer.confirmed is None:
        checks.append(Check("confirmed_time_on_calendar", True, "No existing meeting confirmed."))
    else:
        label = slots.format_interval(answer.confirmed, tz)
        shown = slots.on_calendar(answer.confirmed.start, answer.confirmed.end, cal)
        checks.append(Check("confirmed_time_on_calendar", shown,
                            f"Your calendar shows an event at {label}." if shown
                            else f"Your calendar shows nothing at {label}, so the draft can't confirm it."))

    # 5 and 6. Times written in the text.
    found = mentions.find_mentions(answer.draft_text)
    permitted = answer.offered + [t for t in (answer.accepted, answer.confirmed) if t]
    stray = [m.text for m in found if not any(mentions.matches(m, p, tz, now) for p in permitted)]
    checks.append(Check("no_other_times_in_text", not stray,
                        "Mentions times that aren't offered, accepted or confirmed: " + "; ".join(f'"{s}"' for s in stray)
                        if stray else f"Every date or time in the draft ({len(found)}) is one of its chosen times."))

    missing = [slots.format_interval(t, tz) for t in answer.offered + ([answer.accepted] if answer.accepted else [])
               if not any(m.day and m.time and mentions.matches(m, t, tz, now) for m in found)]
    checks.append(Check("times_written_in_text", not missing,
                        "Chosen but not written in the draft (with day and time): " + "; ".join(missing)
                        if missing else "Every offered or accepted time is written in the draft."))

    # 7. Contact details.
    outside = outside_contact_details(answer.draft_text, thread_text, user_email)
    checks.append(Check("no_outside_contact_details", not outside,
                        "Not in this thread: " + "; ".join(outside) if outside
                        else "No email addresses, links or phone numbers from outside this thread."))
    return checks


def failed(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.passed]


def warnings_for(answer: DraftAnswer, candidates: list[Interval], cal: Calendar) -> list[str]:
    """Soft problems worth showing, that don't block the draft (e.g. offering one time)."""
    warnings = []
    if answer.action == "offer_times":
        if not 2 <= len(answer.offered) <= 3 and len(candidates) >= 2:
            warnings.append(f"Offers {len(answer.offered)} times; Fixture aims for 2 or 3.")
        days = {t.start.astimezone(cal.tz).date() for t in answer.offered}
        available_days = {t.start.astimezone(cal.tz).date() for t in candidates}
        if len(days) < min(len(answer.offered), len(available_days)):
            warnings.append("Some offered times are on the same day although other days are free.")
    return warnings


# --- Contact details -----------------------------------------------------------------

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"\bhttps?://[^\s<>()\"']+|\bwww\.[^\s<>()\"']+"
                 r"|\b(?:[a-z0-9-]+\.)+(?:com|org|edu|net|io|us|co|ai|app|me|gov)(?:/[^\s<>()\"']*)?",
                 re.IGNORECASE)
PHONE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{5,}\d(?![\w-])")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _contact_details(text: str) -> tuple[set[str], set[str], set[str]]:
    """(emails, links, phone numbers) in text, normalized for comparison."""
    emails = {e.lower() for e in EMAIL.findall(text)}
    without_emails = EMAIL.sub(" ", text)
    links = {u.lower().rstrip(".,;:!?") for u in URL.findall(without_emails)}
    links = {re.sub(r"^https?://(www\.)?|^www\.", "", u).rstrip("/") for u in links}
    phones = set()
    for match in PHONE.findall(without_emails):
        digits = re.sub(r"\D", "", match)
        if 7 <= len(digits) <= 15 and not ISO_DATE.match(match.strip()):
            phones.add(digits[-10:])
    return emails, links, phones


def outside_contact_details(draft: str, thread_text: str, user_email: str = "") -> list[str]:
    """Email addresses, links and phone numbers in the draft that don't appear in the thread."""
    emails, links, phones = _contact_details(draft)
    known_emails, known_links, known_phones = _contact_details(thread_text + "\n" + user_email)
    outside = [f"email address {e}" for e in sorted(emails - known_emails)]
    # A link may repeat one from the thread, or shorten it (zoom.us/j/123 -> zoom.us), never extend it.
    outside += [f"link {u}" for u in sorted(links) if not any(k.startswith(u) for k in known_links)]
    outside += ["a phone number" for p in sorted(phones - known_phones)]
    return outside
