"""Request and response shapes for POST /draft (see README "API")."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Label = Literal["new_request", "proposed_times", "acceptance", "reschedule", "assistant_handoff", "none"]
Status = Literal["drafted", "no_reply_needed", "no_free_time", "error"]


class Message(BaseModel):
    """One email. "from" is a Python keyword, so the field is from_ and accepts "from" in JSON."""

    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(default="", max_length=200)  # optional: e.g. the Gmail message id
    from_: str = Field(default="", alias="from", max_length=1000)
    to: str = Field(default="", max_length=5000)
    date: str = Field(default="", max_length=200)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=50_000)
    from_user: bool = False  # sent by the mailbox owner

    def as_dict(self) -> dict:
        return {"id": self.id, "from": self.from_, "to": self.to, "date": self.date, "subject": self.subject,
                "body": self.body, "from_user": self.from_user}


class PastMessage(Message):
    """A message exchanged with the sender in another thread. Needs an id, so the response can cite it."""

    id: str = Field(min_length=1, max_length=200)
    thread_id: str = Field(default="", max_length=200)


class User(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    timezone: str = Field(max_length=64)  # IANA name, e.g. "America/New_York"

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown time zone; use an IANA name such as America/New_York")
        return value


class Classification(BaseModel):
    label: Label
    needs_response: bool
    reason: str = Field(default="", max_length=1000)


class TimeRange(BaseModel):
    start: AwareDatetime
    end: AwareDatetime


class DraftRequest(BaseModel):
    thread: list[Message] = Field(min_length=1, max_length=100)
    target_index: int = Field(ge=0)
    user: User
    classification: Classification | None = None  # missing: the drafter asks the classifier
    busy: list[TimeRange] = Field(default_factory=list, max_length=5000)
    busy_until: AwareDatetime | None = None  # end of the period `busy` covers; nothing later is offered
    past_messages: list[PastMessage] = Field(default_factory=list, max_length=100)
    now: AwareDatetime | None = None  # default: the server's clock
    rules: dict | None = None  # overrides for this draft only (see rules.py)
    regenerate: bool = False  # a "try again" click: a bit more variety
    message_id: str = Field(default="", max_length=200)  # only used in logs

    @model_validator(mode="after")
    def target_in_thread(self):
        if self.target_index >= len(self.thread):
            raise ValueError("target_index is outside the thread")
        return self


class TimeOut(BaseModel):
    start: str  # ISO 8601 in the user's time zone
    end: str
    label: str  # e.g. "Tue, Nov 17, 2:00–2:30 PM EST"


class CheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class ContextOut(BaseModel):
    id: str
    why: str
    score: float | None  # similarity to the thread; None if picked by date
    cited: bool  # the model says it used this email


class DraftResponse(BaseModel):
    status: Status
    draft_text: str = ""
    action: str | None = None
    offered_times: list[TimeOut] = []
    accepted_time: TimeOut | None = None
    confirmed_time: TimeOut | None = None  # an existing meeting the draft confirms (it's on the calendar)
    checks: list[CheckOut] = []
    context_used: list[ContextOut] = []
    warnings: list[str] = []
    error: str | None = None  # a short, safe description when status is "error"
    error_type: str | None = None
    label: str | None = None
    needs_response: bool | None = None
    meeting_minutes: int | None = None
    model: str
    rules_version: str
    attempts: int = 0
    latency_ms: int
    usage: dict = {}
