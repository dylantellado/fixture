"""Fetch read-only Calendar and Gmail data and format it for display.

The fetch_* functions call Google. The format_* helpers are plain
functions with no network calls, so they are easy to test.
"""

import base64
import html
import re
from datetime import date, datetime, timezone
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Words and phrases that suggest an email is about scheduling a meeting.
# Matching is case-insensitive and on whole words. Edit this list to tune the detector.
SCHEDULING_KEYWORDS = [
    "availability",
    "available",
    "schedule",
    "reschedule",
    "meeting",
    "meet",
    "coffee chat",
    "call",
    "interview",
    "invitation",
    "calendar invite",
    "time to connect",
    "catch up",
    "time slot",
    "free to",
    "zoom",
]


def fetch_profile(creds: Credentials) -> dict:
    """Return the signed-in user's name, email, and picture URL."""
    info = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
    return {
        "name": info.get("name") or info.get("email", ""),
        "email": info.get("email", ""),
        "picture": info.get("picture"),
    }


def fetch_events(creds: Credentials, limit: int = 10) -> dict:
    """Return the next upcoming events across every calendar the user has checked.

    "Checked" means ticked in Google Calendar's sidebar (My calendars and
    Other calendars); the API reports that as selected=True.

    Returns {"items": [...], "calendars": [...], "skipped": [...]}, where
    calendars are the ones shown and skipped are names we couldn't read.
    """
    service = build("calendar", "v3", credentials=creds)
    calendars = [c for c in service.calendarList().list().execute().get("items", []) if c.get("selected")]

    now = datetime.now(timezone.utc).isoformat()
    events, shown, skipped = [], [], []
    for cal in calendars:
        info = {
            "name": "Primary" if cal.get("primary") else cal.get("summaryOverride") or cal.get("summary", ""),
            "color": cal.get("backgroundColor", "#888888"),
        }
        # Free/busy-only calendars share busy times but no event details.
        if cal.get("accessRole") == "freeBusyReader":
            skipped.append(info["name"])
            continue
        try:
            result = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=now,
                    maxResults=limit,
                    singleEvents=True,  # expand recurring events into individual ones
                    orderBy="startTime",
                )
                .execute()
            )
        except HttpError:
            skipped.append(info["name"])
            continue
        shown.append(info)
        events += [(e, info) for e in result.get("items", [])]

    # Merge all calendars by start time, dropping events that appear on more than one.
    events.sort(key=lambda pair: event_start(pair[0]))
    seen, items = set(), []
    for event, info in events:
        key = (event.get("iCalUID", event.get("id")), event_start(event))
        if key in seen:
            continue
        seen.add(key)
        items.append(format_event(event, info))
        if len(items) == limit:
            break

    return {"items": items, "calendars": shown, "skipped": skipped}


def fetch_emails(creds: Credentials, limit: int = 20) -> list[dict]:
    """Return the most recent inbox messages (headers and Gmail's short snippet, no bodies)."""
    service = build("gmail", "v1", credentials=creds)
    listing = (
        service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=limit).execute()
    )

    emails = []
    for item in listing.get("messages", []):
        # "metadata" format returns headers only, never the email body.
        message = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject"])
            .execute()
        )
        emails.append(format_email(message))
    return emails


def fetch_thread(creds: Credentials, thread_id: str) -> list[dict]:
    """Return every message in a Gmail thread, oldest first, with its plain-text body.

    Read-only (gmail.readonly). Drafts are skipped. Used only to send the thread
    to the classifier; the text is never logged or saved.

    Builds its own Gmail client, because the web app calls this from several
    threads at once and a client must not be shared between threads.
    """
    service = build("gmail", "v1", credentials=creds)
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    return [format_thread_message(m) for m in thread.get("messages", []) if "DRAFT" not in m.get("labelIds", [])]


def event_start(event: dict) -> datetime:
    """Start time of an event as a timezone-aware datetime, for sorting.

    All-day events count as starting at local midnight.
    """
    start = event.get("start", {})
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"])
    return datetime.fromisoformat(start["date"]).astimezone()


def format_event(event: dict, calendar: dict | None = None) -> dict:
    """Turn a Calendar API event into the fields the dashboard shows.

    calendar is {"name", "color"} for the calendar the event came from.
    """
    start = event.get("start", {})
    end = event.get("end", {})
    attendees = [a["email"] for a in event.get("attendees", []) if "email" in a]

    # All-day events only have "date"; timed events have "dateTime".
    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"])
        end_dt = datetime.fromisoformat(end["dateTime"])
        day = format_day(start_dt.date())
        time = f"{format_time(start_dt)} – {format_time(end_dt)}"
    else:
        day = format_day(date.fromisoformat(start["date"]))
        time = "All day"

    return {
        "title": event.get("summary") or "(no title)",
        "day": day,
        "time": time,
        "attendees": attendees,
        "calendar": calendar,
    }


def format_email(message: dict) -> dict:
    """Turn a Gmail API message (metadata format) into the fields the dashboard shows."""
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    name, address = parseaddr(headers.get("from", ""))

    # internalDate is when Gmail received the message, in milliseconds since 1970.
    received = datetime.fromtimestamp(int(message.get("internalDate", 0)) / 1000).astimezone()

    subject = headers.get("subject") or "(no subject)"
    # Gmail's snippet is a short plain-text preview, with HTML entities like &#39;.
    snippet = html.unescape(message.get("snippet", ""))

    return {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "sender": name or address or "(unknown sender)",
        "address": address,
        "subject": subject,
        "date": format_day(received.date()),
        "unread": "UNREAD" in message.get("labelIds", []),
        "snippet": snippet,
        "scheduling_match": find_scheduling_keyword(f"{subject} {snippet}"),
    }


def find_scheduling_keyword(text: str) -> str | None:
    """Return the first scheduling keyword found in text, or None.

    Returning the matched word (not just True/False) lets the dashboard
    show why an email was tagged.
    """
    for keyword in SCHEDULING_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            return keyword
    return None


def format_thread_message(message: dict) -> dict:
    """Turn a Gmail API message (full format) into what the classifier needs."""
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    name, address = parseaddr(headers.get("from", ""))
    recipients = getaddresses([headers.get("to", ""), headers.get("cc", "")])
    return {
        "id": message.get("id", ""),
        "from": headers.get("from", ""),
        "sender_name": name,
        "address": address.lower(),
        "to": ", ".join(addr for _, addr in recipients if addr),
        "date": headers.get("date", ""),
        "subject": headers.get("subject", ""),
        "body": message_text(message.get("payload", {})) or html.unescape(message.get("snippet", "")),
        "sent": "SENT" in message.get("labelIds", []),
    }


def message_text(payload: dict) -> str:
    """The plain-text body of a Gmail message payload.

    Uses the first text/plain part; if there is none, the first text/html part
    converted to text. Attachments are skipped.
    """
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return _decode(plain)
    rich = _find_part(payload, "text/html")
    return html_to_text(_decode(rich)) if rich is not None else ""


def _find_part(part: dict, mime_type: str) -> dict | None:
    """Depth-first search of a MIME tree for a non-attachment part of this type."""
    if part.get("mimeType") == mime_type and not part.get("filename") and part.get("body", {}).get("data"):
        return part
    for child in part.get("parts", []):
        found = _find_part(child, mime_type)
        if found is not None:
            return found
    return None


def _decode(part: dict) -> str:
    """Gmail sends part bodies as URL-safe base64. Use the part's charset if it names one."""
    data = part["body"]["data"]
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    charset = re.search(r'charset="?([\w-]+)', headers.get("content-type", ""), re.IGNORECASE)
    try:
        return raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:  # an unknown charset name
        return raw.decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    """Collects the visible text of an HTML email, with line breaks at block tags."""

    BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "blockquote", "table"}
    SKIP_TAGS = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__()
        self.parts, self.skipping = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skipping += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Visible text of an HTML email (entities decoded, scripts and styles dropped)."""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def format_day(d: date) -> str:
    """Example: 'Fri, Oct 9'."""
    return f"{d:%a}, {d:%b} {d.day}"


def format_time(dt: datetime) -> str:
    """Example: '9:30 PM'."""
    return f"{dt.hour % 12 or 12}:{dt:%M} {dt:%p}"
