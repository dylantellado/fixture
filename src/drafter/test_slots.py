"""Free-time computation: rules, time zones, DST, buffers, notice, working hours, overlaps."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

import slots
from conftest import NY, dt, interval, make_cal


def allowed(cal, start, end):
    return slots.is_allowed(dt(start), dt(end), cal)


# --- check_time: one rule at a time ------------------------------------------------


def test_busy_time_is_never_allowed():
    cal = make_cal(busy=[("2026-11-12T14:00:00-05:00", "2026-11-12T15:00:00-05:00")])
    problems = slots.check_time(dt("2026-11-12T14:30:00-05:00"), dt("2026-11-12T15:00:00-05:00"), cal)
    assert problems == ["it overlaps a busy calendar event"]


def test_buffer_around_busy_events():
    cal = make_cal(busy=[("2026-11-12T14:00:00-05:00", "2026-11-12T15:00:00-05:00")])
    assert not allowed(cal, "2026-11-12T15:00:00-05:00", "2026-11-12T15:30:00-05:00")  # right after
    assert not allowed(cal, "2026-11-12T15:10:00-05:00", "2026-11-12T15:40:00-05:00")  # inside the 15 min
    assert allowed(cal, "2026-11-12T15:15:00-05:00", "2026-11-12T15:45:00-05:00")  # exactly 15 min after
    assert allowed(cal, "2026-11-12T13:15:00-05:00", "2026-11-12T13:45:00-05:00")  # exactly 15 min before
    assert not allowed(cal, "2026-11-12T13:20:00-05:00", "2026-11-12T13:50:00-05:00")
    problems = slots.check_time(dt("2026-11-12T15:00:00-05:00"), dt("2026-11-12T15:30:00-05:00"), cal)
    assert problems == ["it is within 15 minutes of a busy calendar event"]


def test_buffer_can_be_changed():
    cal = make_cal(busy=[("2026-11-12T14:00:00-05:00", "2026-11-12T15:00:00-05:00")], buffer_minutes=0)
    assert allowed(cal, "2026-11-12T15:00:00-05:00", "2026-11-12T15:30:00-05:00")


def test_minimum_notice():
    cal = make_cal()  # now is Mon Nov 9, 10:00 New York
    assert not allowed(cal, "2026-11-10T09:30:00-05:00", "2026-11-10T10:00:00-05:00")  # 23.5 h away
    assert allowed(cal, "2026-11-10T10:00:00-05:00", "2026-11-10T10:30:00-05:00")  # exactly 24 h
    assert "starts less than 24 hours from now" in slots.check_time(
        dt("2026-11-09T15:00:00-05:00"), dt("2026-11-09T15:30:00-05:00"), cal)[0]


def test_working_hours_in_the_users_zone():
    cal = make_cal()
    assert not allowed(cal, "2026-11-12T07:30:00-05:00", "2026-11-12T08:00:00-05:00")
    assert allowed(cal, "2026-11-12T08:00:00-05:00", "2026-11-12T08:30:00-05:00")
    assert allowed(cal, "2026-11-12T19:30:00-05:00", "2026-11-12T20:00:00-05:00")
    assert not allowed(cal, "2026-11-12T19:45:00-05:00", "2026-11-12T20:15:00-05:00")
    # 9 AM in Los Angeles is noon in New York: allowed for a New York user.
    assert allowed(cal, "2026-11-12T09:00:00-08:00", "2026-11-12T09:30:00-08:00")
    # 6 PM in Los Angeles is 9 PM in New York: outside the user's hours.
    assert slots.check_time(dt("2026-11-12T18:00:00-08:00"), dt("2026-11-12T18:30:00-08:00"), cal) == [
        "it is outside working hours"]


def test_working_days_can_exclude_weekends():
    cal = make_cal(working_days=["mon", "tue", "wed", "thu", "fri"])
    assert not allowed(cal, "2026-11-14T10:00:00-05:00", "2026-11-14T10:30:00-05:00")  # Saturday
    assert allowed(cal, "2026-11-13T10:00:00-05:00", "2026-11-13T10:30:00-05:00")  # Friday
    assert all(s.start.astimezone(ZoneInfo(NY)).weekday() < 5 for s in slots.free_slots(cal, 30))


def test_horizon_and_known_calendar():
    cal = make_cal()
    assert allowed(cal, "2026-11-23T09:00:00-05:00", "2026-11-23T09:30:00-05:00")
    assert not allowed(cal, "2026-11-23T10:00:00-05:00", "2026-11-23T10:30:00-05:00")  # past 14 days
    short = make_cal(busy_until="2026-11-16T10:00:00-05:00")  # busy times only known for a week
    assert not allowed(short, "2026-11-17T10:00:00-05:00", "2026-11-17T10:30:00-05:00")
    assert max(s.end for s in slots.free_slots(short, 30)) <= dt("2026-11-16T10:00:00-05:00")


def test_end_before_start():
    cal = make_cal()
    assert slots.check_time(dt("2026-11-12T10:00:00-05:00"), dt("2026-11-12T10:00:00-05:00"), cal) == [
        "it ends before it starts"]


def test_times_without_offsets_are_refused():
    with pytest.raises(ValueError):
        slots.to_utc(dt("2026-11-12T10:00:00"))


# --- Busy intervals -------------------------------------------------------------


def test_overlapping_and_touching_busy_events_are_merged():
    cal = make_cal(busy=[
        ("2026-11-12T10:00:00-05:00", "2026-11-12T11:00:00-05:00"),
        ("2026-11-12T10:30:00-05:00", "2026-11-12T12:00:00-05:00"),  # overlaps the first
        ("2026-11-12T12:00:00-05:00", "2026-11-12T12:30:00-05:00"),  # touches the second
        ("2026-11-12T16:00:00-05:00", "2026-11-12T16:00:00-05:00"),  # empty: ignored
    ])
    assert cal.busy == [interval("2026-11-12T10:00:00-05:00", "2026-11-12T12:30:00-05:00")]
    day = [s for s in slots.free_slots(cal, 30) if s.start.astimezone(ZoneInfo(NY)).day == 12]
    assert not any(s.overlaps(interval("2026-11-12T09:45:00-05:00", "2026-11-12T12:45:00-05:00")) for s in day)


def test_busy_times_in_utc_and_other_zones():
    # The same event written in UTC and in Los Angeles time blocks the same slots.
    in_utc = make_cal(busy=[("2026-11-12T19:00:00+00:00", "2026-11-12T20:00:00+00:00")])
    in_la = make_cal(busy=[("2026-11-12T11:00:00-08:00", "2026-11-12T12:00:00-08:00")])
    assert slots.free_slots(in_utc, 30) == slots.free_slots(in_la, 30)
    assert not allowed(in_utc, "2026-11-12T14:00:00-05:00", "2026-11-12T14:30:00-05:00")


# --- free_slots ------------------------------------------------------------------


def test_every_free_slot_passes_check_time():
    cal = make_cal(busy=[("2026-11-11T09:00:00-05:00", "2026-11-11T12:20:00-05:00"),
                         ("2026-11-13T13:00:00-05:00", "2026-11-13T18:00:00-05:00")])
    found = slots.free_slots(cal, 45)
    assert found and all(slots.is_allowed(s.start, s.end, cal) for s in found)
    assert all(s.minutes == 45 for s in found)
    # Starts are on the half hour in the user's zone.
    assert {s.start.astimezone(ZoneInfo(NY)).minute for s in found} <= {0, 30}


def test_fully_booked_gives_no_slots():
    cal = make_cal(busy=[("2026-11-09T00:00:00-05:00", "2026-11-24T00:00:00-05:00")])
    assert slots.free_slots(cal, 30) == []
    assert slots.free_windows(cal, 30) == []


def test_slots_across_the_fall_dst_change():
    # US daylight saving ends Sun Nov 1, 2026: 8:00 AM is 12:00 UTC before, 13:00 UTC after.
    cal = make_cal(now="2026-10-29T12:00:00-04:00")
    found = slots.free_slots(cal, 30)
    tz = ZoneInfo(NY)
    firsts = {}
    for s in found:
        firsts.setdefault(s.start.astimezone(tz).date().isoformat(), s)
    assert firsts["2026-10-31"].start.hour == 12 and firsts["2026-10-31"].start.astimezone(tz).hour == 8
    assert firsts["2026-11-01"].start.hour == 13 and firsts["2026-11-01"].start.astimezone(tz).hour == 8
    assert firsts["2026-11-02"].start.hour == 13
    # Every slot stays inside 8:00-20:00 local time on both sides of the change.
    for s in found:
        local_start, local_end = s.start.astimezone(tz), s.end.astimezone(tz)
        assert 8 * 60 <= local_start.hour * 60 + local_start.minute
        assert local_end.hour * 60 + local_end.minute <= 20 * 60
    # The DST day has the same 24 slots (8:00 to 19:30) as any other day.
    assert sum(1 for s in found if s.start.astimezone(tz).date().isoformat() == "2026-11-01") == 24


def test_slots_across_the_spring_dst_change_in_london():
    # UK clocks go forward Sun Mar 29, 2026: 8:00 AM is 08:00 UTC before, 07:00 UTC after.
    cal = make_cal(now="2026-03-26T12:00:00+00:00", tz="Europe/London")
    starts = {}
    for s in slots.free_slots(cal, 30):
        starts.setdefault(s.start.astimezone(ZoneInfo("Europe/London")).date().isoformat(), s.start)
    assert starts["2026-03-28"].hour == 8 and starts["2026-03-29"].hour == 7


def test_half_hour_offset_zone():
    # India is UTC+5:30: slots still start on the local hour and half hour.
    cal = make_cal(now="2026-11-09T10:00:00+05:30", tz="Asia/Kolkata")
    found = slots.free_slots(cal, 30)
    assert {s.start.astimezone(ZoneInfo("Asia/Kolkata")).minute for s in found} == {0, 30}
    assert min(s.start.astimezone(ZoneInfo("Asia/Kolkata")).hour for s in found) == 8


# --- free_windows and candidates ----------------------------------------------------


def test_free_windows_are_cut_by_busy_times_plus_buffer():
    cal = make_cal(busy=[("2026-11-12T10:00:00-05:00", "2026-11-12T11:00:00-05:00"),
                         ("2026-11-12T11:40:00-05:00", "2026-11-12T19:00:00-05:00")])
    tz = ZoneInfo(NY)
    day = [(w.start.astimezone(tz).strftime("%H:%M"), w.end.astimezone(tz).strftime("%H:%M"))
           for w in slots.free_windows(cal, 30) if w.start.astimezone(tz).day == 12]
    # 11:15-11:25 is free but too short for 30 minutes, so it's left out.
    assert day == [("08:00", "09:45"), ("19:15", "20:00")]
    for window in slots.free_windows(cal, 30):
        assert slots.is_allowed(window.start, window.start + timedelta(minutes=30), cal)
        assert slots.is_allowed(window.end - timedelta(minutes=30), window.end, cal)


def test_first_window_starts_after_the_notice_period():
    cal = make_cal()
    assert slots.free_windows(cal, 30)[0].start == slots.to_utc(dt("2026-11-10T10:00:00-05:00"))


def test_candidates_are_spread_across_days_mornings_and_afternoons():
    cal = make_cal(busy=[("2026-11-10T09:00:00-05:00", "2026-11-10T17:00:00-05:00")])
    tz = ZoneInfo(NY)
    picked = slots.pick_candidates(slots.free_slots(cal, 30), tz)
    days = [p.start.astimezone(tz).date() for p in picked]
    assert len(set(days)) == 6 and len(picked) <= 12
    assert all(days.count(d) <= 2 for d in days)
    nov_11 = [p.start.astimezone(tz).strftime("%H:%M") for p in picked if p.start.astimezone(tz).day == 11]
    assert nov_11 == ["10:00", "14:00"]  # preferred mid-morning and mid-afternoon
    nov_10 = [p.start.astimezone(tz).strftime("%H:%M") for p in picked if p.start.astimezone(tz).day == 10]
    assert nov_10 == ["17:30"]  # only the evening is free that day (busy until 17:00 + buffer)


# --- Meeting length and formatting ---------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("Could we find 45 minutes next week?", (45, "email")),
    ("a quick 20-min call", (20, "email")),
    ("Do you have an hour on Thursday?", (60, "email")),
    ("Let's block 1.5 hours for the mock interview", (90, "email")),
    ("half an hour should be plenty", (30, "email")),
    ("an hour-long session", (60, "email")),
    ("Sorry, running 5 minutes late!", (30, "default")),
    ("Please reply within 24 hours.", (30, "default")),
    ("Could we chat sometime?", (30, "default")),
])
def test_meeting_length_from_the_email(text, expected):
    assert slots.meeting_minutes([text], 30) == expected


def test_most_recent_message_with_a_length_wins():
    assert slots.meeting_minutes(["Sounds good!", "Let's do an hour.", "Can we do 30 minutes?"], 30) == (60, "email")


def test_format_interval():
    tz = ZoneInfo(NY)
    assert slots.format_interval(interval("2026-11-17T14:00:00-05:00", "2026-11-17T14:30:00-05:00"), tz) == \
        "Tue, Nov 17, 2:00–2:30 PM EST"
    assert slots.format_interval(interval("2026-11-17T11:30:00-05:00", "2026-11-17T12:00:00-05:00"), tz) == \
        "Tue, Nov 17, 11:30 AM–12:00 PM EST"
    assert slots.format_interval(interval("2026-10-20T09:00:00-04:00", "2026-10-20T10:00:00-04:00"), tz) == \
        "Tue, Oct 20, 9:00–10:00 AM EDT"


def test_on_calendar():
    cal = make_cal(busy=[("2026-11-12T15:00:00-05:00", "2026-11-12T15:30:00-05:00")])
    assert slots.on_calendar(dt("2026-11-12T15:00:00-05:00"), dt("2026-11-12T15:30:00-05:00"), cal)
    assert not slots.on_calendar(dt("2026-11-12T16:00:00-05:00"), dt("2026-11-12T16:30:00-05:00"), cal)
