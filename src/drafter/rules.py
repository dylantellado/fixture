"""The user's scheduling rules: defaults, plus per-user overrides.

Every time the drafter offers or accepts must follow these rules (slots.py and
checker.py enforce them in code; the model only picks among allowed times).

Where rules come from, later ones winning:
  1. rules/default_rules.json            the defaults for everyone (versioned)
  2. RulesStore.overrides_for(user)      per-user settings (none stored yet)
  3. the request's "rules" field         overrides for one draft (tests, what-ifs)

SWAP LATER: a settings page will save per-user overrides. It only needs to
provide a RulesStore (e.g. one backed by the web app's database) and pass it to
the drafter; nothing else changes. Today NoStoredRules is used: everyone gets
the defaults.

One rule is not a setting: busy calendar events are never offered. It is in
code (slots.check_time) and no override can turn it off.

rules_version: the defaults' version (e.g. "1.0"), plus "+" and a short hash
of the overrides when any apply (e.g. "1.0+3f9a1c2e"), so logs and responses
show exactly which rules a draft followed.
"""

import hashlib
import json
from datetime import time
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "rules" / "default_rules.json"

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # index = datetime.weekday()


class WorkingHours(BaseModel):
    """Daily window, in the user's time zone, that meetings must fit inside."""

    model_config = ConfigDict(extra="forbid")
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # "08:00"
    end: str = Field(pattern=r"^([01]\d|2[0-4]):[0-5]\d$")  # "20:00" ("24:00" = midnight)

    @model_validator(mode="after")
    def start_before_end(self):
        if self.start_minutes >= self.end_minutes:
            raise ValueError("working_hours.start must be before working_hours.end")
        return self

    @property
    def start_minutes(self) -> int:
        hours, minutes = map(int, self.start.split(":"))
        return hours * 60 + minutes

    @property
    def end_minutes(self) -> int:
        hours, minutes = map(int, self.end.split(":"))
        return hours * 60 + minutes

    def start_time(self) -> time:
        return time(self.start_minutes // 60, self.start_minutes % 60)


class Rules(BaseModel):
    """A complete, checked set of rules."""

    model_config = ConfigDict(extra="forbid")
    version: str
    working_hours: WorkingHours
    working_days: list[Weekday] = Field(min_length=1)
    min_notice_hours: float = Field(ge=0, le=24 * 14)
    buffer_minutes: int = Field(ge=0, le=180)
    default_meeting_minutes: int = Field(ge=5, le=480)
    horizon_days: int = Field(ge=1, le=60)
    slot_step_minutes: int = Field(ge=5, le=120)

    @field_validator("working_days")
    @classmethod
    def no_duplicate_days(cls, days):
        if len(set(days)) != len(days):
            raise ValueError("working_days lists a day twice")
        return days


class RuleOverrides(BaseModel):
    """What a user (or a request) may change. Unknown names are an error, not ignored."""

    model_config = ConfigDict(extra="forbid")
    working_hours: WorkingHours | None = None
    working_days: list[Weekday] | None = None
    min_notice_hours: float | None = None
    buffer_minutes: int | None = None
    default_meeting_minutes: int | None = None
    horizon_days: int | None = None
    slot_step_minutes: int | None = None

    def as_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class RulesStore(Protocol):
    """Where per-user overrides are kept. A settings page will provide a real one."""

    def overrides_for(self, user_email: str) -> dict: ...


class NoStoredRules:
    """Today: nobody has saved settings, so everyone gets the defaults."""

    def overrides_for(self, user_email: str) -> dict:
        return {}


class InMemoryRulesStore:
    """Overrides by email address, kept in memory. Used by tests and scenarios."""

    def __init__(self, overrides: dict[str, dict] | None = None):
        self._overrides = {k.lower(): v for k, v in (overrides or {}).items()}

    def overrides_for(self, user_email: str) -> dict:
        return dict(self._overrides.get(user_email.lower(), {}))


def load_defaults(path: Path = DEFAULT_RULES_PATH) -> dict:
    """The default rules file as a dict (its "notes" are documentation only)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.pop("notes", None)
    Rules(**data)  # fail at startup if the file itself is invalid
    return data


DEFAULTS = load_defaults()


def overrides_hash(overrides: dict) -> str:
    canonical = json.dumps(overrides, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def rules_for(user_email: str, request_overrides: dict | None = None, store: RulesStore | None = None,
              defaults: dict | None = None) -> Rules:
    """The rules for one draft: defaults, then the user's stored overrides, then the request's.

    Raises ValueError (pydantic's ValidationError is one) if an override is unknown or invalid.
    """
    base = dict(defaults or DEFAULTS)
    applied: dict = {}
    for source in ((store or NoStoredRules()).overrides_for(user_email or ""), request_overrides or {}):
        applied.update(RuleOverrides(**source).as_dict())
    merged = {**base, **applied}
    if applied:
        merged["version"] = f"{base['version']}+{overrides_hash(applied)}"
    return Rules(**merged)


def describe(rules: Rules) -> str:
    """One line for the prompt and the UI, e.g. '8:00 AM-8:00 PM every day, 24 h notice, 15 min buffer'."""
    days = "every day" if len(rules.working_days) == 7 else ", ".join(d.capitalize() for d in rules.working_days)

    def clock(minutes: int) -> str:
        hour, minute = divmod(minutes % (24 * 60), 60)
        return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"

    hours = f"{clock(rules.working_hours.start_minutes)}-{clock(rules.working_hours.end_minutes)}"
    notice = f"{rules.min_notice_hours:g} h notice"
    return f"{hours} {days}, {notice}, {rules.buffer_minutes} min buffer around busy events, " \
           f"up to {rules.horizon_days} days ahead"
