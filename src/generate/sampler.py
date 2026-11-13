"""Turn cards and a seed into scenarios: who writes what, when, and the true state.

Everything here is plain, seeded code with no network calls, so a scenario can
be rebuilt exactly from (seed, user, thread number, card files). The writer
(writer.py) only turns each scenario into email text.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from acts import ACTS, FLOWS, answer
from times import Slot, confirmed_from, header_date, iso, make_slots

CARDS_DIR = Path(__file__).parent / "cards"

# Time-phrase styles by who is writing. International senders write day-first.
TIME_STYLES = ["exact", "weekday", "ordinal", "relative", "window", "range"]
INTERNATIONAL_STYLES = ["day_first", "weekday", "window", "exact"]
# Counterparts whose side is on US Eastern time when the user is abroad.
HOME_SIDE = {"professor", "advisor", "recruiter", "hiring_manager", "alum", "admissions", "ta", "classmate"}


def load_cards(cards_dir: Path = CARDS_DIR) -> dict:
    return {name: yaml.safe_load((cards_dir / f"{name}.yaml").read_text())
            for name in ("users", "counterparts", "names")}


def cards_version(cards_dir: Path = CARDS_DIR) -> str:
    """Short hash of every card file, recorded with each thread."""
    digest = hashlib.sha256()
    for path in sorted(cards_dir.glob("*.yaml")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:12]


@dataclass
class Person:
    pid: str  # P0 is always the user
    name: str
    email: str
    role: str  # user, them, assistant, intro, group, system
    title: str = ""
    org: str = ""
    style: str = ""
    timezone: str = "America/New_York"

    @property
    def address(self) -> str:
        return f"{self.name} <{self.email}>"


@dataclass
class Step:
    position: int
    role: str
    act: str
    sender: Person
    to: list[Person]
    cc: list[Person]
    sent: datetime
    label: str
    needs_response: bool
    rule: str
    phrases: list[str] = field(default_factory=list)  # must appear word for word
    state: dict = field(default_factory=dict)  # true thread state after this message


@dataclass
class Scenario:
    user: dict
    thread_id: str
    seed: int
    flow: str
    kind: str  # counterpart kind
    purpose: str
    people: list[Person]
    steps: list[Step]


def _person(rng: random.Random, cards: dict, pid: str, role: str, kind: str, timezone: str) -> Person:
    card = cards["counterparts"][kind]
    first, last = rng.choice(cards["names"]["first"]), rng.choice(cards["names"]["last"])
    if role == "group":
        return Person(pid, card["title"], f"announce-{rng.randint(10, 99)}@{card['domain']}", role,
                      card["title"], card["domain"], "newsletter", timezone)
    if role == "system":
        return Person(pid, "Notifications", f"no-reply@{card['domain']}", role, card["title"], card["domain"],
                      "machine-written", timezone)
    return Person(pid, f"{first} {last}", f"{first}.{last}@{card['domain']}".lower().replace("'", ""), role,
                  card["title"], card["domain"], rng.choice(card["styles"]), timezone)


def _pick_weighted(rng: random.Random, weights: dict) -> str:
    items = [(k, w) for k, w in weights.items() if w > 0]
    return rng.choices([k for k, _ in items], weights=[w for _, w in items], k=1)[0]


def build_scenario(cards: dict, user: dict, number: int, seed: int) -> Scenario:
    """Scenario number `number` for `user`. The same inputs always give the same scenario."""
    rng = random.Random(f"{seed}:{user['user_id']}:{number}")
    kind = _pick_weighted(rng, user["counterparts"])
    card = cards["counterparts"][kind]
    flow = _pick_weighted(rng, card["flows"])
    # Handoff flows need an assistant on their side; skip them for kinds that never have one.
    if flow.startswith("handoff") and not card.get("assistant"):
        flow = "they_offer"
    user_tz = user["timezone"]
    their_tz = "America/New_York" if (user_tz.startswith("Europe") and kind in HOME_SIDE) else user_tz

    me = Person("P0", user["name"], user["email"], "user", timezone=user_tz)
    first_role = FLOWS[flow][0][0]
    them_role = first_role if first_role in ("group", "system") else "them"
    them = _person(rng, cards, "P1", them_role, kind, their_tz)
    people = [me, them]
    if any(role == "assistant" for role, _ in FLOWS[flow]):
        helper = _person(rng, cards, "P2", "assistant", kind, their_tz)
        helper.title = rng.choice(["Executive Assistant", "Recruiting Coordinator", "Program Coordinator",
                                   "Lab Manager", "Scheduling Assistant"])
        people.append(helper)
    if any(role == "intro" for role, _ in FLOWS[flow]):
        intro = _person(rng, cards, "P2", "intro", rng.choice(["professor", "alum", "advisor"]), their_tz)
        people.append(intro)
    by_role = {p.role: p for p in people}

    styles = INTERNATIONAL_STYLES if their_tz != user_tz else TIME_STYLES
    duration = rng.choice([20, 30, 30, 45, 60])
    start = datetime.fromisoformat(str(user["start"])).replace(tzinfo=ZoneInfo(user_tz))
    sent = start + timedelta(days=rng.randint(0, 40), hours=rng.randint(8, 21), minutes=rng.choice([3, 17, 34, 52]))

    steps = _walk(rng, flow, by_role, me, sent, styles, duration)
    return Scenario(user, f"g{number:03d}", seed, flow, kind, rng.choice(card["purposes"]), people, steps)


def _walk(rng, flow, by_role, me, sent, styles, duration) -> list[Step]:
    """Play the flow forward, tracking slots and the true state after each message."""
    state = {"status": None, "proposed": [], "confirmed": None, "waiting_on": "nobody",
             "scheduler": "P1", "needs_response": False}
    open_slots: list[Slot] = []  # the most recent offer, which a 'pick' chooses from
    chosen: Slot | None = None
    steps = []
    for position, (role, act_name) in enumerate(FLOWS[flow]):
        act = ACTS[act_name]
        sender = by_role[role]
        label, needs_response, rule = answer(act_name, role)
        to, cc = _addressing(role, act_name, by_role, me)
        other = to[0].pid if role == "user" else "P0"
        phrases: list[str] = []

        if act.times == "offer":
            count = 1 if act_name.endswith("_one") else rng.choice([2, 2, 3])
            tz = sender.timezone if role != "user" else me.timezone
            open_slots = make_slots(rng, sent, tz, count, styles, duration)
            chosen = None  # a new offer replaces any earlier pick
            phrases = [s.phrase for s in open_slots]
            for s in state["proposed"]:
                if s["state"] == "open":
                    s["state"] = "superseded"
            state["proposed"] += [{**s.as_state(), "by": sender.pid, "position": position, "state": "open"}
                                  for s in open_slots]
            state["status"] = "reschedule_requested" if act_name == "reschedule_offer" else "times_proposed"
        elif act.times == "pick":
            if act_name == "restate":
                slot = chosen  # the time already agreed
            elif act_name == "confirm_choice":
                # The time the user just picked, or one of the times the user just offered (E20).
                slot = chosen or (rng.choice(open_slots) if open_slots else None)
            else:
                slot = rng.choice(open_slots) if open_slots else chosen
            chosen = slot
            if slot is not None:
                phrases = [slot.pick_phrase]
                state["confirmed"] = {**confirmed_from(slot), "by": sender.pid, "position": position,
                                      "tentative": False}
                for s in state["proposed"]:
                    if s["state"] == "open":
                        s["state"] = "accepted" if s["quote"] == slot.phrase else "rejected"
            state["status"] = "confirmed"
        elif act.times == "move":
            new = make_slots(rng, sent, sender.timezone, 1, ["exact", "weekday", "ordinal"], duration)[0]
            chosen = new
            phrases = [new.phrase]
            state["confirmed"] = {**confirmed_from(new), "quote": new.phrase, "by": sender.pid,
                                  "position": position, "tentative": False}
            state["status"] = "confirmed"
        elif act_name in ("request", "catchup", "intro_user", "intro_other"):
            state["status"] = "requested"
        elif act_name == "decline_all":
            for s in state["proposed"]:
                if s["state"] == "open":
                    s["state"] = "rejected"
            open_slots, state["status"] = [], "requested"
        elif act_name in ("handoff_wait", "handoff_ask"):
            state["status"], state["scheduler"] = "requested", "P2"
        elif act_name == "sched_link":
            state["status"] = "times_proposed"
            state["proposed"].append({"kind": "vague", "start": None, "end": None, "quote": "booking link",
                                      "by": sender.pid, "position": position, "state": "open"})
        elif act_name == "cancel_invite" or act_name == "cancel_followup":
            state["status"], state["confirmed"], chosen = "cancelled", None, None

        # Whose move it is. Single-message non-scheduling mail leaves no meeting.
        if act.label == "none" and state["status"] is None:
            waiting = "nobody"
        elif act_name in ("handoff_wait",):
            waiting = "P2"
        elif act_name == "intro_other":
            waiting = "P1"
        elif act_name == "cancel_followup":
            waiting = sender.pid
        elif needs_response:
            waiting = "P0"
        elif label in ("acceptance", "none"):
            waiting = "nobody"
        else:
            waiting = other if role == "user" else "P0"
        state["waiting_on"] = waiting
        state["needs_response"] = needs_response

        steps.append(Step(position, role, act_name, sender, to, cc, sent, label, needs_response, rule, phrases,
                          state=_copy_state(state)))
        sent = sent + timedelta(hours=rng.randint(1, 20), minutes=rng.randint(0, 59))
        if sent.hour < 7:  # people mostly write while awake: push night replies to the morning
            sent = sent.replace(hour=rng.randint(7, 9))
    return steps


def _copy_state(state: dict) -> dict:
    return {**state, "proposed": [dict(s) for s in state["proposed"]],
            "confirmed": dict(state["confirmed"]) if state["confirmed"] else None}


def _addressing(role: str, act_name: str, by_role: dict, me: Person) -> tuple[list[Person], list[Person]]:
    them, helper = by_role.get("them"), by_role.get("assistant")
    if role == "group":
        return [Person("P9", "Students", f"students@{by_role['group'].org}", "group")], []
    if role == "system":
        return [me], []
    if role == "intro":
        return [me, them], []
    if role == "assistant":
        return [me], [them]
    if role == "user":
        return ([helper], [them]) if helper and act_name != "request" else ([them], [])
    if act_name.startswith("handoff"):
        return [me], [helper]
    return [me], []


def to_source_thread(scenario: Scenario, subject: str, bodies: list[str]) -> dict:
    """The thread in data/source/generated_threads.jsonl format (Data contract)."""
    addresses = []
    for person in scenario.people + [p for s in scenario.steps for p in s.to + s.cc]:
        if person.address not in addresses:
            addresses.append(person.address)
    return {
        "user_id": scenario.user["user_id"],
        "thread_id": scenario.thread_id,
        "subject": subject,
        "participants": addresses,
        "messages": [{
            "sender": s.sender.address,
            "recipients": [p.address for p in s.to + s.cc],
            "timestamp": header_date(s.sent),
            "body": body,
            "label": s.label,
        } for s, body in zip(scenario.steps, bodies)],
    }


def to_annotations(scenario: Scenario) -> list[dict]:
    return [{
        "user_id": scenario.user["user_id"], "thread_id": scenario.thread_id, "position": s.position,
        "needs_response": s.needs_response, "rule": s.rule,
        "rationale": f"Generated: {s.role} sends '{s.act}' ({ACTS[s.act].brief.split('.')[0].lower()})",
        "rules_version": "1.5",
    } for s in scenario.steps]


def to_state_record(scenario: Scenario, cards_hash: str) -> dict:
    """Ground-truth thread state after every message (state schema v0.1, see the Thread state proposal)."""
    return {
        "user_id": scenario.user["user_id"], "thread_id": scenario.thread_id, "schema_version": "0.1",
        "flow": scenario.flow, "counterpart": scenario.kind, "purpose": scenario.purpose,
        "seed": scenario.seed, "cards_version": cards_hash,
        "participants": [{"pid": p.pid, "address": p.address, "role": p.role, "timezone": p.timezone}
                         for p in scenario.people],
        "states": [{"position": s.position, "act": s.act, "sender": s.sender.pid, "sent": iso(s.sent),
                    **s.state} for s in scenario.steps],
    }
