"""Find the dates and times written in a draft, in code (no LLM), for checker.py.

A draft may only mention the times it offers, accepts or confirms. This module
reads the draft text and returns every date/time mention it finds, so the
checker can flag the ones that match none of those times.

What counts as a mention:
  days:   weekday names (Tuesday, Tue, Tues.), month dates (Nov 17, 17 November,
          11/17, 2026-11-17), "the 17th", today / tonight / tomorrow
  times:  2pm, 2:30 PM, 2.30pm, 14:00, noon, midnight, "at 2", ranges
          (2-2:30pm, 2:00–2:30 PM, 11:30 to 12 PM), each with an optional
          zone (EST, PT, GMT, ...)
Vague words (morning, next week, soon) are not mentions.

Nearby day and time tokens in the same sentence are joined into one mention:
"Tue, Nov 17, 2:00–2:30 PM EST" is one mention with a day and a time;
"Tuesday at 2 or 4pm" is two mentions (Tuesday 2, Tuesday 4pm).

Matching (matches()): a mention matches a meeting time if its day (if any)
is that meeting's local date and its time (if any) is the meeting's start or
end (a range must match both). Times without am/pm try both readings. Times
with a zone are compared in that zone; otherwise in the user's zone.

This is deliberately strict: when unsure, a mention doesn't match, the check
fails, and the draft is rewritten or refused. It never lets a time through
because it couldn't parse it... except times written in words ("two o'clock"),
which the prompt tells the model not to use.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from slots import Interval

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
WEEKDAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# Common zone abbreviations. EST and EDT both mean New York time, as people write them.
ZONES = {
    "ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
    "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
    "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver",
    "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "GMT": "UTC", "UTC": "UTC", "BST": "Europe/London", "CET": "Europe/Paris", "CEST": "Europe/Paris",
}

_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
          r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
_ORD = r"(?:st|nd|rd|th)?"

# Day patterns: (regex, kind). Month and short weekday names must be capitalized,
# so "may", "sat" or "sun" in ordinary sentences don't count.
DAY_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(rf"\b{_MONTH}\s+(\d{{1,2}}){_ORD}\b"), "month_day"),
    (re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MONTH}(?![a-z])"), "day_month"),
    (re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])"), "numeric"),
    (re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE), "ordinal"),
    (re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", re.IGNORECASE), "weekday"),
    (re.compile(r"\b(Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\b\.?"), "weekday"),
    (re.compile(r"\b(today|tonight|tomorrow)\b", re.IGNORECASE), "relative"),
]

_MER = r"([ap])\.?\s?m\b\.?"  # am, pm, a.m., p.m., a m
_HM = r"(\d{1,2})(?:[:.](\d{2}))?"
_DASH = r"\s*(?:-|–|—|to|until|till)\s*"
TIME_PATTERNS = [
    # 2-2:30pm, 2:00–2:30 PM, 11:30 am to 12:15 pm (the end needs am/pm)
    (re.compile(rf"\b{_HM}\s*(?:{_MER})?{_DASH}{_HM}\s*{_MER}", re.IGNORECASE), "range"),
    # 14:00-14:30 or 2:00-2:30 (no am/pm)
    (re.compile(rf"\b(\d{{1,2}}):(\d{{2}}){_DASH}(\d{{1,2}}):(\d{{2}})\b"), "range_clock"),
    # 2pm, 2:30 PM, 2.30pm
    (re.compile(rf"\b{_HM}\s*{_MER}", re.IGNORECASE), "single"),
    # 14:00, 2:30 (no am/pm)
    (re.compile(r"\b(\d{1,2}):(\d{2})\b"), "clock"),
    (re.compile(r"\b(noon|midday|midnight)\b", re.IGNORECASE), "named"),
    # "at 2" (but not "at 2:30", "at 2 people", "at 20%")
    (re.compile(r"\bat\s+(\d{1,2})\b(?![:.]\d)(?!\s*(?:%|percent|people|minutes?|mins?|hours?|hrs?|[ap]\.?\s?m\b))",
                re.IGNORECASE), "bare"),
]
ZONE_AFTER = re.compile(r"\s*\(?\b(" + "|".join(ZONES) + r")\b\)?")

# Between two tokens of one mention: short, on one line, and no sentence break.
MAX_GAP = 30
_BREAK = re.compile(r"[\n.!?;]")


@dataclass
class DaySpec:
    weekday: int | None = None
    month: int | None = None
    day: int | None = None
    year: int | None = None
    relative: int | None = None  # 0 = today/tonight, 1 = tomorrow
    inherited: bool = False  # copied from the previous mention ("Tuesday at 2 or 4pm")

    def kinds(self) -> set[str]:
        kinds = set()
        if self.weekday is not None:
            kinds.add("weekday")
        if self.day is not None:
            kinds.add("date")
        if self.relative is not None:
            kinds.add("relative")
        return kinds


@dataclass
class TimeSpec:
    starts: set[int]  # possible start times, minutes after local midnight
    ends: set[int] | None = None  # for ranges
    zone: str | None = None  # an abbreviation from ZONES


@dataclass
class Mention:
    text: str
    start: int
    end: int
    day: DaySpec | None = None
    time: TimeSpec | None = None


@dataclass
class _Token:
    start: int
    end: int
    day: DaySpec | None = None
    time: TimeSpec | None = None
    kinds: set[str] = field(default_factory=set)


def _hour(hour: int, minute: int, meridiem: str | None) -> set[int]:
    """Possible minutes-after-midnight for a clock reading. Empty if it isn't a valid time."""
    if minute > 59:
        return set()
    if meridiem:
        if not 1 <= hour <= 12:
            return set()
        hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
        return {hour * 60 + minute}
    if hour > 23:
        return set()
    if hour == 0 or hour > 12:
        return {hour * 60 + minute}
    # 2:30 could be 2:30 AM or PM; 12:30 could be 12:30 PM or 12:30 AM.
    return {(hour % 12) * 60 + minute, (hour % 12 + 12) * 60 + minute}


def _day_token(match: re.Match, kind: str) -> DaySpec | None:
    g = match.groups()
    if kind == "iso":
        return DaySpec(year=int(g[0]), month=int(g[1]), day=int(g[2]))
    if kind == "month_day":
        return DaySpec(month=MONTHS[g[0][:3].lower()], day=int(g[1]))
    if kind == "day_month":
        return DaySpec(month=MONTHS[g[1][:3].lower()], day=int(g[0]))
    if kind == "numeric":
        first, second = int(g[0]), int(g[1])
        year = int(g[2]) if g[2] else None
        if year is not None and year < 100:
            year += 2000
        # US style (11/17) first; if that isn't a date, day/month (17/11).
        if 1 <= first <= 12 and 1 <= second <= 31:
            return DaySpec(month=first, day=second, year=year)
        if 1 <= second <= 12 and 1 <= first <= 31:
            return DaySpec(month=second, day=first, year=year)
        return None
    if kind == "ordinal":
        return DaySpec(day=int(g[0])) if 1 <= int(g[0]) <= 31 else None
    if kind == "weekday":
        return DaySpec(weekday=WEEKDAY_NAMES[g[0][:3].lower()])
    if kind == "relative":
        return DaySpec(relative=1 if g[0].lower() == "tomorrow" else 0)
    return None


def _time_token(match: re.Match, kind: str) -> TimeSpec | None:
    g = match.groups()
    if kind == "range":
        h1, m1, mer1, h2, m2, mer2 = int(g[0]), int(g[1] or 0), g[2], int(g[3]), int(g[4] or 0), g[5]
        ends = _hour(h2, m2, mer2)
        if not ends:
            return None
        if mer1:
            starts = _hour(h1, m1, mer1)
        else:
            # "2-2:30pm": the start shares the end's am/pm, unless that puts it after the end
            # ("11:30-12:30 PM" means 11:30 AM).
            starts = _hour(h1, m1, mer2)
            if starts and min(starts) >= min(ends):
                starts = _hour(h1, m1, "a" if mer2.lower() == "p" else "p")
        return TimeSpec(starts=starts, ends=ends) if starts else None
    if kind == "range_clock":
        starts, ends = _hour(int(g[0]), int(g[1]), None), _hour(int(g[2]), int(g[3]), None)
        return TimeSpec(starts=starts, ends=ends) if starts and ends else None
    if kind == "single":
        starts = _hour(int(g[0]), int(g[1] or 0), g[2])
        return TimeSpec(starts=starts) if starts else None
    if kind == "clock":
        starts = _hour(int(g[0]), int(g[1]), None)
        return TimeSpec(starts=starts) if starts else None
    if kind == "named":
        return TimeSpec(starts={0} if g[0].lower() == "midnight" else {12 * 60})
    if kind == "bare":
        starts = _hour(int(g[0]), 0, None)
        return TimeSpec(starts=starts) if starts else None
    return None


def _non_overlapping(found: list[tuple[int, int, object]]) -> list[tuple[int, int, object]]:
    """Keep the longest match where matches overlap (a range wins over the times inside it)."""
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    kept: list[tuple[int, int, object]] = []
    for item in found:
        if kept and item[0] < kept[-1][1]:
            continue
        kept.append(item)
    return kept


def _tokens(text: str) -> list[_Token]:
    times = []
    for pattern, kind in TIME_PATTERNS:
        for match in pattern.finditer(text):
            spec = _time_token(match, kind)
            if spec:
                times.append((match.start(), match.end(), spec))
    tokens = []
    for start, end, spec in _non_overlapping(times):
        zone = ZONE_AFTER.match(text, end)
        if zone:
            spec.zone, end = zone.group(1), zone.end()
        tokens.append(_Token(start, end, time=spec))
    days = []
    for pattern, kind in DAY_PATTERNS:
        for match in pattern.finditer(text):
            spec = _day_token(match, kind)
            if spec:
                days.append((match.start(), match.end(), spec))
    for start, end, spec in _non_overlapping(days):
        # A day pattern can't sit inside a time ("11/17" never does, but be safe).
        if any(t.start <= start < t.end for t in tokens if t.time):
            continue
        tokens.append(_Token(start, end, day=spec, kinds=spec.kinds()))
    return sorted(tokens, key=lambda t: t.start)


def find_mentions(text: str) -> list[Mention]:
    """Every date/time mention in the text, in order."""
    mentions: list[Mention] = []
    current: Mention | None = None
    for token in _tokens(text):
        near = current is not None and _near(text[current.end:token.start])
        if token.day:
            # A day joins the mention before it if that mention has no day of its own yet
            # ("2pm on Tuesday"), or has only a day of another kind and no time yet
            # ("Tuesday, Nov 17"). Otherwise it starts a new mention ("..., or Wednesday").
            joinable = near and (
                current.day is None
                or current.day.inherited
                or (current.time is None and not (current.day.kinds() & token.kinds))
            )
            if joinable:
                if current.day is None or current.day.inherited:
                    current.day = token.day
                else:  # e.g. "Tuesday" + "Nov 17"
                    _merge_day(current.day, token.day)
                current.end = token.end
            else:
                current = Mention("", token.start, token.end, day=token.day)
                mentions.append(current)
        else:
            if near and current.time is None:
                current.time = token.time
                current.end = token.end
            else:
                inherited = replace(current.day, inherited=True) if near and current.day else None
                current = Mention("", token.start, token.end, day=inherited, time=token.time)
                mentions.append(current)
    for mention in mentions:
        mention.text = text[mention.start:mention.end]
    return mentions


def _near(gap: str) -> bool:
    return len(gap) <= MAX_GAP and not _BREAK.search(gap)


def _merge_day(target: DaySpec, extra: DaySpec) -> None:
    for name in ("weekday", "month", "day", "year", "relative"):
        if getattr(target, name) is None and getattr(extra, name) is not None:
            setattr(target, name, getattr(extra, name))


# --- Matching ---------------------------------------------------------------------


def _zone(mention: Mention, interval: Interval, user_tz: ZoneInfo) -> ZoneInfo:
    """The zone a mention is written in: its abbreviation, or the user's zone."""
    abbreviation = mention.time.zone if mention.time else None
    if not abbreviation:
        return user_tz
    # The user's own zone's abbreviation (e.g. "MST" for Phoenix) means the user's zone.
    if interval.start.astimezone(user_tz).tzname() == abbreviation:
        return user_tz
    return ZoneInfo(ZONES[abbreviation])


def day_matches(spec: DaySpec, day: date, today: date) -> bool:
    if spec.weekday is not None and spec.weekday != day.weekday():
        return False
    if spec.month is not None and spec.month != day.month:
        return False
    if spec.day is not None and spec.day != day.day:
        return False
    if spec.year is not None and spec.year != day.year:
        return False
    if spec.relative is not None and (day - today).days != spec.relative:
        return False
    return True


def matches(mention: Mention, interval: Interval, user_tz: ZoneInfo, now: datetime) -> bool:
    """Does this mention refer to this meeting time? (See the module docstring.)"""
    tz = _zone(mention, interval, user_tz)
    start, end = interval.start.astimezone(tz), interval.end.astimezone(tz)
    if mention.day and not day_matches(mention.day, start.date(), now.astimezone(tz).date()):
        return False
    if mention.time:
        start_minutes = start.hour * 60 + start.minute
        end_minutes = end.hour * 60 + end.minute
        if mention.time.ends is not None:
            return start_minutes in mention.time.starts and end_minutes in mention.time.ends
        return start_minutes in mention.time.starts or end_minutes in mention.time.starts
    return True
