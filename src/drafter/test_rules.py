"""Default rules, per-user overrides and versions."""

import json

import pytest
from pydantic import ValidationError

import rules
from rules import InMemoryRulesStore, rules_for


def test_defaults_match_the_spec():
    r = rules_for("anyone@example.com")
    assert r.version == "1.0"
    assert (r.working_hours.start, r.working_hours.end) == ("08:00", "20:00")
    assert r.working_days == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert (r.min_notice_hours, r.buffer_minutes, r.default_meeting_minutes, r.horizon_days) == (24, 15, 30, 14)


def test_stored_then_request_overrides_apply_in_order():
    store = InMemoryRulesStore({"Sam@Example.edu": {"buffer_minutes": 30, "min_notice_hours": 48}})
    r = rules_for("sam@example.edu", {"buffer_minutes": 0}, store)
    assert r.buffer_minutes == 0  # the request wins
    assert r.min_notice_hours == 48  # the stored setting stays
    assert r.version.startswith("1.0+") and len(r.version) == len("1.0+") + 8
    assert rules_for("other@example.edu", None, store).version == "1.0"  # someone else: defaults


def test_same_overrides_give_the_same_version():
    a = rules_for("", {"buffer_minutes": 5, "horizon_days": 7})
    b = rules_for("", {"horizon_days": 7, "buffer_minutes": 5})
    assert a.version == b.version != rules_for("", {"buffer_minutes": 6, "horizon_days": 7}).version


@pytest.mark.parametrize("overrides", [
    {"never_offer_busy": False},  # not a setting: busy times are never offered
    {"buffer": 10},  # unknown name
    {"working_hours": {"start": "18:00", "end": "09:00"}},
    {"working_hours": {"start": "8am", "end": "20:00"}},
    {"working_days": []},
    {"working_days": ["mon", "mon"]},
    {"horizon_days": 365},
    {"buffer_minutes": -5},
])
def test_invalid_overrides_are_refused(overrides):
    with pytest.raises(ValidationError):
        rules_for("", overrides)


def test_default_file_is_valid_and_documents_the_busy_rule():
    data = json.loads(rules.DEFAULT_RULES_PATH.read_text())
    assert any("never offered" in note for note in data["notes"])
    assert "never_offer_busy" not in data  # it's code, not a setting


def test_describe():
    assert rules.describe(rules_for("")) == (
        "8:00 AM-8:00 PM every day, 24 h notice, 15 min buffer around busy events, up to 14 days ahead")
