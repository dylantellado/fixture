"""Tests for anonymize.py."""

from anonymize import Anonymizer, normalize_phone


def build(*texts):
    anonymizer = Anonymizer()
    for text in texts:
        anonymizer.collect(text)
    anonymizer.finalize()
    return anonymizer


def test_every_way_of_writing_a_number_is_the_same_number():
    us = {"(617) 555-0142", "617.555.0142", "617-555-0142", "+1 617 555 0142"}
    uk = {"+44 20 7946 0123", "+44 (0)20 7946 0123", "020 7946 0123", "+442079460123"}
    assert {normalize_phone(p) for p in us} == {"6175550142"}
    assert {normalize_phone(p) for p in uk} == {"02079460123"}


def test_different_numbers_with_the_same_ending_stay_different():
    assert normalize_phone("(312) 555-0163") != normalize_phone("617-555-0163")


def test_dates_and_times_are_not_phone_numbers():
    anonymizer = build("Due 2026-10-13 at 09:12, room 214, Oct 20 2026.")
    assert anonymizer.phones == set()


def test_addresses_and_phones_are_replaced_but_names_kept():
    text = "Write to Dana Whitfield <dana.whitfield@careers.college.example> or call (617) 555-0142."
    anonymizer = build(text)
    assert anonymizer.replace(text) == "Write to Dana Whitfield <EMAIL_001> or call PHONE_001."
    assert anonymizer.person("Dana Whitfield <Dana.Whitfield@careers.college.example>") == "Dana Whitfield <EMAIL_001>"


def test_address_without_display_name():
    anonymizer = build("<marcus.bell@example.com>")
    assert anonymizer.person("<marcus.bell@example.com>") == "<EMAIL_001>"


def test_numbering_does_not_depend_on_order_seen():
    a = "b@college.example then a@college.example"
    b = "a@college.example then b@college.example"
    assert build(a).email_map == build(b).email_map == {"a@college.example": "EMAIL_001", "b@college.example": "EMAIL_002"}


def test_placeholders_widen_past_999():
    anonymizer = build(" ".join(f"person{i}@example.com" for i in range(1000)))
    assert sorted(anonymizer.email_map.values())[0] == "EMAIL_0001"
