"""Tests for cleaning.py: one test per kind of clutter, using text shaped like our corpus."""

from cleaning import clean_body

GMAIL_REPLY = """Tuesday at 3 works, see you then.

Best,
Priya

On Thu, Sep 3, 2026 at 2:30 PM Dana Whitfield <dana.whitfield@careers.college.example> wrote:
> Would Tue Sep 8 at 3:00 or 3:30 work?
>
> Dana"""

OUTLOOK_REPLY = """Option 2 works best for me.

Best regards,
Sofia Okafor
MS Data Science, the College | TA, STAT 142

________________________________
From: Maya Lindqvist <maya.lindqvist@brightwater.example>
Sent: Sunday, September 27, 2026 6:40 PM
Subject: RE: interview

Here are two new options."""

FORWARD = """thoughts?? this is the startup I talked to

---------- Forwarded message ---------
From: Tidewell <updates@tidewell.example>
Date: Fri, Sep 18, 2026 at 2:04 PM
Subject: We're hiring
To: <marcus.bell@example.com>


Tidewell is hiring our first new-grad engineer.

--
You're getting this because you signed up for Tidewell updates."""


def test_gmail_quote_is_removed_and_sign_off_kept():
    assert clean_body(GMAIL_REPLY, "Priya Shah") == "Tuesday at 3 works, see you then.\n\nBest,\nPriya"


def test_outlook_quote_and_signature_title_are_removed():
    assert clean_body(OUTLOOK_REPLY, "Sofia Okafor") == "Option 2 works best for me.\n\nBest regards,\nSofia Okafor"


def test_forward_keeps_content_but_not_header_or_footer():
    cleaned = clean_body(FORWARD, "Marcus Bell")
    assert cleaned == (
        "thoughts?? this is the startup I talked to\n\n"
        "Forwarded message from Tidewell:\n\n"
        "Tidewell is hiring our first new-grad engineer."
    )


def test_signature_block_with_full_name_is_removed():
    body = "Saturday at 10 it is.\n\nCheers,\nRohan\n\nRohan Mehta\nAssociate, Calder Bay Partners\n+44 20 7946 0123"
    assert clean_body(body, "Rohan Mehta") == "Saturday at 10 it is.\n\nCheers,\nRohan"


def test_signature_block_matching_part_of_the_line():
    body = "Good luck this season.\n\nThe Graduate Career Office\ngradcareers@college.example | (617) 555-0177"
    assert clean_body(body, "Graduate Career Office") == "Good luck this season."


def test_confidentiality_footer_and_mobile_footer_are_removed():
    body = (
        "Can we do Thursday?\n\nSent from my iPhone\n\n"
        "This email and any attachments are confidential and intended solely for the addressee."
    )
    assert clean_body(body, "Jordan Lee") == "Can we do Thursday?"


def test_thanks_in_the_middle_is_not_a_sign_off():
    body = "Thanks for the notes.\nI'll book the 4:20 slot.\nThanks for your help with this.\nAnother line.\nAnd one more."
    assert clean_body(body, "Priya Shah") == body


def test_messy_whitespace_is_normalized():
    body = "Hi Ben,   \n\n\n\nsee you   at 8.  \n\n\n"
    assert clean_body(body, "Priya Shah") == "Hi Ben,\n\nsee you at 8."


def test_plain_message_is_unchanged():
    assert clean_body("yes!!", "Maya Chen") == "yes!!"
