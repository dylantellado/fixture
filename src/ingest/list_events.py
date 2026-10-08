"""Print your next 10 upcoming events from your primary Google Calendar."""

from datetime import datetime, timezone

from googleapiclient.discovery import build

from google_auth import get_credentials


def main() -> None:
    service = build("calendar", "v3", credentials=get_credentials())

    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
            singleEvents=True,  # expand recurring events into individual ones
            orderBy="startTime",
        )
        .execute()
    )
    events = result.get("items", [])

    if not events:
        print("No upcoming events found.")
        return

    for event in events:
        # Timed events use "dateTime"; all-day events only have "date".
        start = event["start"].get("dateTime", event["start"].get("date"))
        end = event["end"].get("dateTime", event["end"].get("date"))
        attendees = [a["email"] for a in event.get("attendees", [])]

        print(event.get("summary", "(no title)"))
        print(f"  Start:     {start}")
        print(f"  End:       {end}")
        print(f"  Attendees: {', '.join(attendees) if attendees else 'none'}")
        print()


if __name__ == "__main__":
    main()
