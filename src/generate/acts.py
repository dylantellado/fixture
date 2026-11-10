"""What each generated email does, and the correct answer for it.

An "act" is one email's job in a thread (ask to meet, offer times, accept, ...).
The scenario picks the acts first; Claude only writes text for them. So the
label and needs_response of every message come from this table, which follows
docs/data/labeling_rules.md (v1.5), not from the writer.

Roles: "user" (the mailbox owner), "them" (the person the user is scheduling
with), "assistant" (someone scheduling for "them"), "intro" (someone
introducing the user to "them"), "group" (a list or mass sender) and "system"
(automated mail).
"""

from dataclasses import dataclass

RULES_VERSION = "1.5"


@dataclass(frozen=True)
class Act:
    name: str
    label: str
    # needs_response when someone other than the user sends it. A message the
    # user sends is always False (NR1), so there is no field for that case.
    needs_response: bool
    rule: str  # rule ids that set label and needs_response
    brief: str  # what the writer is told this email does (never the label name)
    times: str = "none"  # "offer": proposes slots, "pick": names one slot, "move": new time, "none"


ACTS = {a.name: a for a in [
    # Asking to meet
    Act("request", "new_request", True, "D1; NR1",
        "Ask to set up a meeting or call. Give the reason. Do not suggest any specific day or time."),
    Act("catchup", "new_request", True, "E8; NR8",
        "A friendly, personal note suggesting you catch up or grab coffee sometime. No specific day or time."),
    Act("decline_all", "new_request", True, "E7; NR1",
        "Say none of the offered times work and ask for a few other options. Do not offer any times yourself."),
    Act("intro_user", "new_request", True, "E17; NR10",
        "Introduce the user to the other person and ask the user to reach out to them to find a time."),
    Act("intro_other", "new_request", False, "E17; NR10",
        "Introduce the user to the other person and tell the other person to reach out to the user to find a time."),
    # Offering times
    Act("propose", "proposed_times", True, "D2; NR1",
        "Offer the listed times for the meeting and ask which works.", times="offer"),
    # One slot only: needed where E14 vs E20 depends on how many times were offered.
    Act("propose_one", "proposed_times", True, "D2; NR1",
        "Offer the single listed time for the meeting and ask if it works.", times="offer"),
    Act("sched_link", "proposed_times", True, "E16; NR5",
        "Share a booking link (use https://cal.example/<a short name>) and ask the reader to pick a slot there."),
    Act("handoff_wait", "assistant_handoff", False, "D5, T2; NR1",
        "Say you are copying the assistant named in the scenario, who manages your calendar and will reach out "
        "with times. The reader doesn't need to do anything yet."),
    Act("handoff_ask", "assistant_handoff", True, "D5, T2; NR1",
        "Say the assistant named in the scenario handles your calendar and ask the reader to send them their "
        "availability."),
    # Agreeing
    Act("accept", "acceptance", False, "D3; NR3",
        "Confirm the meeting at the given time.", times="pick"),
    Act("accept_question", "acceptance", True, "D3; NR3",
        "Confirm the meeting at the given time, and ask whether the reader prefers video or in person.",
        times="pick"),
    Act("confirm_choice", "acceptance", False, "E20; NR3",
        "Confirm the time the reader just chose or suggested (e.g. 'Tuesday it is').", times="pick"),
    # Moving or cancelling a confirmed meeting
    Act("reschedule_offer", "reschedule", True, "D4, PR; NR1",
        "Something came up: move the already-confirmed meeting and offer the listed new times.", times="offer"),
    Act("reschedule_directive", "reschedule", True, "D4; NR9",
        "Move the already-confirmed meeting to the given new time, stated as a decision. You may add 'let me "
        "know if that's a problem'.", times="move"),
    Act("cancel_invite", "reschedule", True, "D4; NR2",
        "Cancel the already-confirmed meeting and ask the reader to suggest another time that works."),
    Act("cancel_followup", "reschedule", False, "D4; NR2",
        "Cancel the already-confirmed meeting and say you will reach out yourself later to find a new time."),
    # After a time is set
    Act("logistics", "none", False, "E1; NR1",
        "Send logistics for the confirmed meeting (room, address or video link). No new times."),
    Act("restate", "none", False, "E14; NR7",
        "Restate the already-agreed time with the details, e.g. 'as agreed, we meet ...'.", times="pick"),
    # Must read as a question the reader has to answer (E13), never as a settled restatement (E14).
    Act("still_on", "none", True, "E13; NR6",
        "Ask, as a direct question the reader must answer, whether the already-confirmed meeting is still on "
        "(e.g. 'Are we still on for ...?'). Don't state it as settled or say they only need to reply if "
        "something changed."),
    Act("thanks", "none", False, "E6; NR1",
        "Thank the reader for the meeting that already happened. Do not ask to meet again."),
    # Not scheduling (hard negatives and plain mail)
    Act("announcement", "none", False, "E3; NR1",
        "A group announcement of an event, deadline or office hours schedule, with dates and times. Not a "
        "personal ask."),
    Act("cold_sales", "none", False, "E9; NR1",
        "An unsolicited sales pitch asking for a short call on a specific day. The reader never asked for it."),
    Act("automated", "none", False, "E2; NR4",
        "An automated reminder or confirmation (appointment, registration or shift), clearly machine-written."),
    Act("out_of_office", "none", False, "E5; NR4", "An automatic out-of-office reply with a return date."),
    Act("task_split", "none", False, "E19; NR1",
        "Divide work between you and the reader, with due days. No meeting is involved."),
    Act("info", "none", False, "D6; NR1",
        "An ordinary non-scheduling email (a question about a document, a link, a short update). No meeting."),
]}


# Thread shapes: (role, act) per message, in order. Each flow starts at the
# first message of a thread. Flows mixing "them" and "assistant" need an
# assistant in the scenario.
FLOWS = {
    "they_ask_user_offers": [("them", "request"), ("user", "propose"), ("them", "confirm_choice")],
    "they_ask_logistics": [("them", "request"), ("user", "propose"), ("them", "confirm_choice"),
                           ("them", "logistics")],
    "user_asks": [("user", "request"), ("them", "propose"), ("user", "accept")],
    # E14: the user accepted the single time offered, so the reply only restates it (none, NR7).
    "user_asks_restate": [("user", "request"), ("them", "propose_one"), ("user", "accept"), ("them", "restate")],
    "they_offer": [("them", "propose"), ("user", "accept"), ("them", "confirm_choice")],
    "they_offer_question": [("them", "propose"), ("user", "accept"), ("them", "accept_question")],
    "decline_then_offer": [("them", "propose"), ("user", "decline_all"), ("them", "propose"), ("user", "accept")],
    "they_decline_user_times": [("user", "propose"), ("them", "decline_all"), ("user", "propose"),
                                ("them", "accept")],
    "user_offers": [("user", "propose"), ("them", "accept")],
    "reschedule_offer": [("them", "propose"), ("user", "accept"), ("them", "reschedule_offer"),
                         ("user", "accept"), ("them", "confirm_choice")],
    "reschedule_directive": [("user", "request"), ("them", "propose"), ("user", "accept"),
                             ("them", "reschedule_directive")],
    "cancel_invite": [("them", "propose"), ("user", "accept"), ("them", "cancel_invite"), ("user", "propose"),
                      ("them", "confirm_choice")],
    "cancel_followup": [("user", "request"), ("them", "propose"), ("user", "accept"), ("them", "cancel_followup")],
    "still_on": [("them", "propose"), ("user", "accept"), ("them", "still_on")],
    "handoff_wait": [("them", "handoff_wait"), ("assistant", "propose"), ("user", "accept"),
                     ("assistant", "confirm_choice")],
    "handoff_ask": [("user", "request"), ("them", "handoff_ask"), ("user", "propose"),
                    ("assistant", "confirm_choice")],
    "sched_link": [("them", "sched_link")],
    "catchup": [("them", "catchup"), ("user", "propose"), ("them", "confirm_choice")],
    "intro_user": [("intro", "intro_user")],
    "intro_other": [("intro", "intro_other")],
    "thanks": [("them", "thanks")],
    "announcement": [("group", "announcement")],
    "cold_sales": [("them", "cold_sales")],
    "automated": [("system", "automated")],
    "out_of_office": [("system", "out_of_office")],
    "task_split": [("them", "task_split")],
    "info": [("them", "info")],
}

NEGATIVE_FLOWS = {"thanks", "announcement", "cold_sales", "automated", "out_of_office", "task_split", "info"}


def answer(act_name: str, role: str) -> tuple[str, bool, str]:
    """(label, needs_response, rule) for one message. The user's own mail is never needs_response (NR1)."""
    act = ACTS[act_name]
    if role == "user":
        return act.label, False, f"{act.rule.split(';')[0].strip()}; NR1 (sent by the user)"
    return act.label, act.needs_response, act.rule


def check_flows() -> list[str]:
    """Problems in FLOWS (unknown acts or roles). Empty when the table is consistent."""
    roles = {"user", "them", "assistant", "intro", "group", "system"}
    problems = []
    for name, steps in FLOWS.items():
        for role, act in steps:
            if act not in ACTS:
                problems.append(f"{name}: unknown act {act}")
            if role not in roles:
                problems.append(f"{name}: unknown role {role}")
    return problems
