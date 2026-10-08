"""Tests for the formatting helpers in google_data.py (no network calls)."""

from datetime import datetime

from google_data import event_start, find_scheduling_keyword, format_email, format_event


def test_timed_event():
    event = {
        "summary": "Coffee chat",
        "start": {"dateTime": "2026-10-09T21:30:00-04:00"},
        "end": {"dateTime": "2026-10-09T22:30:00-04:00"},
        "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
    }
    assert format_event(event) == {
        "title": "Coffee chat",
        "day": "Fri, Oct 9",
        "time": "9:30 PM – 10:30 PM",
        "attendees": ["a@example.com", "b@example.com"],
        "calendar": None,
    }


def test_all_day_event_without_title_or_attendees():
    event = {"start": {"date": "2026-10-25"}, "end": {"date": "2026-10-26"}}
    result = format_event(event)
    assert result["title"] == "(no title)"
    assert result["day"] == "Sun, Oct 25"
    assert result["time"] == "All day"
    assert result["attendees"] == []


def test_email_with_display_name():
    received = datetime(2026, 10, 7, 12, 0).astimezone()
    message = {
        "internalDate": str(int(received.timestamp() * 1000)),
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Jane Recruiter <jane@example.com>"},
                {"name": "Subject", "value": "Interview times"},
            ]
        },
    }
    assert format_email(message) == {
        "sender": "Jane Recruiter",
        "address": "jane@example.com",
        "subject": "Interview times",
        "date": "Wed, Oct 7",
        "unread": True,
        "snippet": "",
        "scheduling_match": "interview",
    }


def test_email_missing_headers():
    message = {"internalDate": "0", "labelIds": ["INBOX"], "payload": {"headers": []}}
    result = format_email(message)
    assert result["sender"] == "(unknown sender)"
    assert result["subject"] == "(no subject)"
    assert result["unread"] is False


def test_email_snippet_is_unescaped_and_tagged():
    message = {
        "internalDate": "0",
        "snippet": "Hi Dylan, what&#39;s your availability next week?",
        "payload": {"headers": [{"name": "Subject", "value": "Following up"}]},
    }
    result = format_email(message)
    assert result["snippet"] == "Hi Dylan, what's your availability next week?"
    assert result["scheduling_match"] == "availability"


def test_scheduling_keywords_match_whole_words_only():
    assert find_scheduling_keyword("Coffee Chat on Friday?") == "coffee chat"
    assert find_scheduling_keyword("Can we set up a call?") == "call"
    # "meet" inside "meetup" or "call" inside "recall" should not count.
    assert find_scheduling_keyword("Product recall notice for the meetup") is None
    assert find_scheduling_keyword("Your receipt from the bookstore") is None


def test_event_carries_calendar_info():
    event = {"start": {"date": "2026-10-25"}, "end": {"date": "2026-10-26"}}
    calendar = {"name": "Recruiting", "color": "#16a765"}
    assert format_event(event, calendar)["calendar"] == calendar


def test_events_from_different_calendars_sort_by_start():
    # Mixed timezones and an all-day event, as happens when merging calendars.
    late_boston = {"start": {"dateTime": "2026-10-09T21:30:00-04:00"}}
    early_utc = {"start": {"dateTime": "2026-10-09T12:00:00+00:00"}}  # 8:00 AM in Boston
    all_day_next = {"start": {"date": "2026-10-11"}}  # a day later, so any local timezone works
    ordered = sorted([all_day_next, late_boston, early_utc], key=event_start)
    assert ordered == [early_utc, late_boston, all_day_next]
