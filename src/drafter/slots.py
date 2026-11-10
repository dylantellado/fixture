"""Free time, computed in code (no LLM): which meeting times follow the user's rules.

The one rule that decides everything is check_time(): a meeting from start to end
is allowed only if it
  - doesn't overlap a busy calendar event (never; this can't be turned off),
  - isn't within buffer_minutes of a busy event,
  - fits inside the working hours, on a working day, in the user's time zone,
  - starts at least min_notice_hours from now,
  - ends inside the horizon (horizon_days from now, and never after the end of
    the period the busy times cover).
free_slots() lists candidate meetings by stepping through each working day and
keeping the ones check_time() allows, so the two can't disagree. checker.py uses
check_time() again on whatever the model offered or accepted.

Time zones: all arithmetic and comparisons are on UTC datetimes. The user's time
zone (an IANA name such as "America/New_York") is only used to build each day's
working window and to format times, so days with a daylight-saving change still
get 8:00-20:00 local time.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from rules import WEEKDAYS, Rules

UTC = timezone.utc


@dataclass(frozen=True, order=True)
class Interval:
    """A time range. start and end are timezone-aware (UTC inside this module)."""

    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return round((self.end - self.start).total_seconds() / 60)

    def overlaps(self, other: "Interval") -> bool:
        """True if they share any time. Touching (one ends when the other starts) isn't overlapping."""
        return self.start < other.end and other.start < self.end


def to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("times must include a UTC offset")
    return moment.astimezone(UTC)


def merge_busy(busy: list[tuple[datetime, datetime]]) -> list[Interval]:
    """Busy intervals in UTC, sorted, with overlapping or touching ones merged. Empty ones are dropped."""
    intervals = sorted(Interval(to_utc(s), to_utc(e)) for s, e in busy if to_utc(e) > to_utc(s))
    merged: list[Interval] = []
    for interval in intervals:
        if merged and interval.start <= merged[-1].end:
            if interval.end > merged[-1].end:
                merged[-1] = Interval(merged[-1].start, interval.end)
        else:
            merged.append(interval)
    return merged


@dataclass(frozen=True)
class Calendar:
    """Everything the rules need to judge a time: busy intervals, rules, now, time zone, horizon."""

    busy: list[Interval]
    rules: Rules
    now: datetime
    tz: ZoneInfo
    busy_until: datetime | None = None  # end of the period the busy list covers, if known

    @property
    def earliest(self) -> datetime:
        return to_utc(self.now) + timedelta(hours=self.rules.min_notice_hours)

    @property
    def horizon_end(self) -> datetime:
        end = to_utc(self.now) + timedelta(days=self.rules.horizon_days)
        # Never offer a time we don't have busy data for.
        return min(end, to_utc(self.busy_until)) if self.busy_until else end

    def working_window(self, day: date) -> Interval | None:
        """The working hours on this local date, in UTC, or None if it isn't a working day."""
        if WEEKDAYS[day.weekday()] not in self.rules.working_days:
            return None
        hours = self.rules.working_hours
        start = datetime.combine(day, hours.start_time(), tzinfo=self.tz)
        # end_minutes can be 24:00, so build the end from midnight plus minutes (wall-clock).
        midnight = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
        end_wall = midnight.replace(tzinfo=None) + timedelta(minutes=hours.end_minutes)
        end = end_wall.replace(tzinfo=self.tz)
        return Interval(to_utc(start), to_utc(end))

    def local_days(self) -> list[date]:
        """Every local date from today through the horizon's last day."""
        first = to_utc(self.now).astimezone(self.tz).date()
        last = self.horizon_end.astimezone(self.tz).date()
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def check_time(start: datetime, end: datetime, cal: Calendar) -> list[str]:
    """Why this meeting time breaks the rules; an empty list means it's allowed."""
    start, end = to_utc(start), to_utc(end)
    rules = cal.rules
    if end <= start:
        return ["it ends before it starts"]
    meeting = Interval(start, end)
    problems = []
    if any(meeting.overlaps(b) for b in cal.busy):
        problems.append("it overlaps a busy calendar event")
    else:
        buffer = timedelta(minutes=rules.buffer_minutes)
        if any(meeting.overlaps(Interval(b.start - buffer, b.end + buffer)) for b in cal.busy):
            problems.append(f"it is within {rules.buffer_minutes} minutes of a busy calendar event")
    local_day = start.astimezone(cal.tz).date()
    window = cal.working_window(local_day)
    if window is None:
        problems.append("it is not on a working day")
    elif not (window.start <= start and end <= window.end):
        problems.append("it is outside working hours")
    if start < cal.earliest:
        problems.append(f"it starts less than {rules.min_notice_hours:g} hours from now")
    if end > cal.horizon_end:
        problems.append(f"it ends more than {rules.horizon_days} days ahead (or after the known calendar)")
    return problems


def is_allowed(start: datetime, end: datetime, cal: Calendar) -> bool:
    return not check_time(start, end, cal)


def on_calendar(start: datetime, end: datetime, cal: Calendar) -> bool:
    """True if a busy event on the calendar overlaps this time (used to confirm existing meetings)."""
    meeting = Interval(to_utc(start), to_utc(end))
    return any(meeting.overlaps(b) for b in cal.busy)


def free_slots(cal: Calendar, minutes: int) -> list[Interval]:
    """Every allowed meeting of this length, starting on the slot step inside each working window."""
    step = timedelta(minutes=cal.rules.slot_step_minutes)
    length = timedelta(minutes=minutes)
    slots = []
    for day in cal.local_days():
        window = cal.working_window(day)
        if window is None:
            continue
        start = window.start
        while start + length <= window.end:
            if is_allowed(start, start + length, cal):
                slots.append(Interval(start, start + length))
            start += step
    return slots


def free_windows(cal: Calendar, minutes: int) -> list[Interval]:
    """Maximal stretches of allowed time at least `minutes` long (for judging the sender's proposals).

    Each is a working window, cut by the notice period, the horizon, and busy
    events plus their buffer. Any meeting of that length entirely inside one is
    allowed by check_time().
    """
    buffer = timedelta(minutes=cal.rules.buffer_minutes)
    blocked = [Interval(b.start - buffer, b.end + buffer) for b in cal.busy]
    windows = []
    for day in cal.local_days():
        window = cal.working_window(day)
        if window is None:
            continue
        pieces = [Interval(max(window.start, cal.earliest), min(window.end, cal.horizon_end))]
        for block in blocked:
            next_pieces = []
            for piece in pieces:
                if not piece.overlaps(block):
                    next_pieces.append(piece)
                    continue
                if piece.start < block.start:
                    next_pieces.append(Interval(piece.start, block.start))
                if block.end < piece.end:
                    next_pieces.append(Interval(block.end, piece.end))
            pieces = next_pieces
        windows += [p for p in pieces if p.end - p.start >= timedelta(minutes=minutes)]
    return windows


def pick_candidates(slots: list[Interval], tz: ZoneInfo, max_days: int = 6) -> list[Interval]:
    """A short, spread-out list for the model to offer from: up to two a day (one
    morning, one afternoon) on the first max_days days that have free time.

    Prefers mid-morning (10:00 or later) and mid-afternoon (14:00 or later) starts,
    and falls back to the earliest free slot in that half of the day.
    """
    by_day: dict[date, list[Interval]] = {}
    for slot in slots:
        by_day.setdefault(slot.start.astimezone(tz).date(), []).append(slot)
    picked = []
    for day in sorted(by_day)[:max_days]:
        day_slots = by_day[day]
        for half, preferred_hour in ((range(0, 12), 10), (range(12, 24), 14)):
            in_half = [s for s in day_slots if s.start.astimezone(tz).hour in half]
            if in_half:
                preferred = [s for s in in_half if s.start.astimezone(tz).hour >= preferred_hour]
                picked.append((preferred or in_half)[0])
    return picked


# --- Meeting length ----------------------------------------------------------------

# "45 minutes", "a 20-min call", "15 mins"
_MINUTES = re.compile(r"\b(\d{1,3}) ?-?(?:minutes?|mins?)\b", re.IGNORECASE)
# "an hour", "one hour", "1 hour", "1.5 hours", "2 hrs", "hour-long", "half an hour"
_HOURS = re.compile(r"\b(?:(an|one|a full)|([1-3](?:\.5)?)) ?-?(?:hours?|hrs?)\b|\bhour-long\b", re.IGNORECASE)
_HALF_HOUR = re.compile(r"\bhalf (?:an )?hour\b|\bhalf-hour\b", re.IGNORECASE)


def meeting_minutes(texts: list[str], default: int) -> tuple[int, str]:
    """Meeting length asked for in the email, else the default. Returns (minutes, "email" or "default").

    texts are message bodies, most recent first; the first one that names a
    length wins. Only plausible meeting lengths (10 to 180 minutes) count, so
    "running 5 minutes late" or "within 24 hours" are ignored.
    """
    for text in texts:
        candidates = []  # (position in text, minutes); the earliest mention wins
        half_hours = [match.span() for match in _HALF_HOUR.finditer(text)]
        candidates += [(start, 30) for start, _ in half_hours]
        for match in _MINUTES.finditer(text):
            value = int(match.group(1))
            if 10 <= value <= 180:
                candidates.append((match.start(), value))
        for match in _HOURS.finditer(text):
            # "half an hour" contains "an hour"; that part was already counted as 30 minutes.
            if any(start <= match.start() < end for start, end in half_hours):
                continue
            value = 60 if not match.group(2) else round(float(match.group(2)) * 60)
            candidates.append((match.start(), value))
        if candidates:
            return min(candidates)[1], "email"
    return default, "default"


# --- Formatting --------------------------------------------------------------------


def clock(moment: datetime) -> str:
    """'2:00 PM'."""
    return f"{moment.hour % 12 or 12}:{moment:%M} {moment:%p}"


def format_interval(interval: Interval, tz: ZoneInfo) -> str:
    """'Tue, Nov 17, 2:00–2:30 PM EST' (or '11:30 AM–12:00 PM EST' across noon), in the user's zone."""
    start, end = interval.start.astimezone(tz), interval.end.astimezone(tz)
    day = f"{start:%a}, {start:%b} {start.day}"
    if start.strftime("%p") == end.strftime("%p"):
        times = f"{clock(start)[:-3]}–{clock(end)}"
    else:
        times = f"{clock(start)}–{clock(end)}"
    return f"{day}, {times} {end.tzname()}"


def iso_local(moment: datetime, tz: ZoneInfo) -> str:
    """ISO 8601 in the user's zone, to the minute: '2026-11-17T14:00:00-05:00'."""
    return moment.astimezone(tz).replace(microsecond=0).isoformat()
