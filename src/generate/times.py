"""Meeting slots and the exact words used to write them.

The sampler picks real datetimes first, then renders each one in a sampled
style ("Tue 11/17 at 3pm ET", "Wednesday afternoon", "17/11 at 15:00", ...).
The writer must use that phrase word for word, so the ground-truth time and
the email text can't drift apart.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import format_datetime
from zoneinfo import ZoneInfo

ZONE_NAMES = {
    "America/New_York": "ET", "America/Chicago": "CT", "America/Denver": "MT",
    "America/Los_Angeles": "PT", "Europe/Madrid": "CET",
}


@dataclass
class Slot:
    kind: str  # "exact" (start and end), "window" (a range the meeting fits in), "vague" (no times)
    start: datetime | None
    end: datetime | None
    phrase: str  # the words the writer must use when offering it
    pick_phrase: str = ""  # the words used when someone picks it (a time inside a window)
    picked: dict = field(default_factory=dict)  # set when a window is narrowed to one time

    def as_state(self) -> dict:
        return {"kind": self.kind, "start": iso(self.start), "end": iso(self.end), "quote": self.phrase}


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def header_date(moment: datetime) -> str:
    """Email Date header format, e.g. 'Tue, 13 Oct 2026 09:12:00 -0400' (the Data contract's format)."""
    return format_datetime(moment)


def _hour(moment: datetime) -> str:
    """'3pm', '3:30pm', 'noon'."""
    if moment.hour == 12 and moment.minute == 0:
        return "noon"
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}{suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d}{suffix}"


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def render(start: datetime, after: datetime, style: str) -> str:
    """Words for an exact start time. `after` is when the email is sent (for 'tomorrow')."""
    zone = ZONE_NAMES.get(str(start.tzinfo), "")
    weekday, short_day = start.strftime("%A"), start.strftime("%a")
    if style == "exact":
        return f"{short_day} {start.month}/{start.day} at {_hour(start)} {zone}".strip()
    if style == "ordinal":
        return f"{weekday} the {_ordinal(start.day)} at {_hour(start)}"
    if style == "day_first":
        return f"{start.day:02d}/{start.month:02d} at {start.hour:02d}:{start.minute:02d}"
    if style == "relative" and (start.date() - after.date()).days == 1:
        return f"tomorrow at {_hour(start)}"
    # "weekday" (and the fallback): only safe within the coming week, which the sampler ensures.
    return f"{weekday} at {_hour(start)}"


def make_slots(rng: random.Random, sent: datetime, tz: str, count: int, styles: list[str],
               duration: int) -> list[Slot]:
    """`count` slots on different days 1 to 6 days after `sent`, 9am to 5pm in `tz`."""
    zone = ZoneInfo(tz)
    local_sent = sent.astimezone(zone)
    days = rng.sample(range(1, 7), k=min(count, 6))
    slots = []
    for day in sorted(days):
        date = (local_sent + timedelta(days=day)).date()
        style = rng.choice(styles)
        if style in ("window", "range"):
            if style == "window":
                part, (first, last) = rng.choice([("morning", (9, 12)), ("afternoon", (13, 17))])
                phrase = f"{date.strftime('%A')} {part}"
            else:
                first = rng.choice([9, 13, 14])  # "9-11am", "1-3pm", "2-4pm"
                last = first + 2
                phrase = f"{date.strftime('%A')} {_hour(datetime(2000, 1, 1, first)).rstrip('apm')}-{_hour(datetime(2000, 1, 1, last))}"
            start = datetime(date.year, date.month, date.day, first, tzinfo=zone)
            end = datetime(date.year, date.month, date.day, last, tzinfo=zone)
            pick = start + timedelta(hours=1)
            slot = Slot("window", start, end, phrase, pick_phrase=render(pick, sent, "weekday"))
            slot.picked = {"start": pick, "end": pick + timedelta(minutes=duration)}
        else:
            start = datetime(date.year, date.month, date.day, rng.choice(range(9, 17)), rng.choice([0, 30]),
                             tzinfo=zone)
            phrase = render(start, sent, style)
            slot = Slot("exact", start, start + timedelta(minutes=duration), phrase,
                        pick_phrase=render(start, sent, "weekday"))
        slots.append(slot)
    return slots


def confirmed_from(slot: Slot) -> dict:
    """The confirmed meeting when `slot` is picked (a window narrows to one time)."""
    if slot.kind == "window":
        return {"start": iso(slot.picked["start"]), "end": iso(slot.picked["end"]), "quote": slot.pick_phrase}
    return {"start": iso(slot.start), "end": iso(slot.end), "quote": slot.pick_phrase}
