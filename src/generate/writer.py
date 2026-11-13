"""Write one thread's emails with Claude, then check them against the scenario.

One API call per thread returns the subject and every body at once, as JSON.
The writer never sees label names or rule ids, only what each email does, and
must use each listed time phrase word for word. check_bodies() rejects drafts
that break that, and the thread is rewritten (up to MAX_ATTEMPTS).
"""

import json
import re

import anthropic

from acts import ACTS
from sampler import Scenario

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_ATTEMPTS = 3

SYSTEM = """\
You write realistic emails for a fictional, synthetic dataset used to test a scheduling assistant for students
and young people. Every person, school and company is fictional; addresses use reserved example domains.

You get one email thread as a scenario: the people, what the meeting is about, and for each email who sends
it, when, and what it does. Write the subject line and the body of every email, in order.

Rules:
- Each body does exactly what its "does" line says, and nothing more. Never add a scheduling ask, an offer, an
  acceptance or a cancellation the scenario doesn't list for that email.
- When an email lists "must include", use each phrase exactly as written (same words, numbers and spacing),
  and mention no other dates or times except ones already agreed earlier in the thread.
- Unless its "does" line asks for dates or times (e.g. an announcement or a reminder), an email with no "must
  include" phrases proposes no specific day or time for a meeting. It may refer to a time already agreed earlier
  in the thread, using the same words as before.
- Match each sender's style, role and relationship to the user. Vary length, greetings and sign-offs the way
  real people do. Students and young people often write casually.
- Bodies are plain text: no quoted earlier messages, no email signatures blocks beyond a name, no headers.
  (Signatures, quoted history and footers are added later in code.)
- Don't mention that the data is synthetic."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "bodies": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "bodies"],
    "additionalProperties": False,
}

# A time like "3pm", "3:30 pm" or "15:00": emails with no listed phrase must not contain one.
TIME_PATTERN = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE)
LABEL_WORDS = re.compile(r"\b(new_request|proposed_times|assistant_handoff|needs_response)\b")


def scenario_prompt(scenario: Scenario) -> str:
    user = scenario.user
    lines = [
        f"The user (mailbox owner): {user['name']}, {user['life_context']}",
        f"Meeting topic: {scenario.purpose}",
        "People:",
    ]
    for p in scenario.people:
        if p.role == "user":
            continue
        desc = {"them": "the person the user is scheduling with", "assistant": "schedules for the other person",
                "intro": "introduces the user to the other person", "group": "a mailing list",
                "system": "an automated sender"}[p.role]
        lines.append(f"- {p.name} ({p.title}, {p.org}): {desc}; writing style: {p.style}")
    lines.append("")
    lines.append("Emails, in order:")
    for s in scenario.steps:
        when = s.sent.strftime("%A %B %-d, %-I:%M %p") + f" ({s.sender.timezone})"
        to = ", ".join(p.name for p in s.to)
        cc = f"; cc {', '.join(p.name for p in s.cc)}" if s.cc else ""
        lines.append(f"{s.position + 1}. From {s.sender.name} to {to}{cc}, sent {when}.")
        lines.append(f"   Does: {ACTS[s.act].brief}")
        if s.phrases:
            lines.append("   Must include: " + "; ".join(f'"{p}"' for p in s.phrases))
    lines.append("")
    lines.append(f"Return JSON with the subject and exactly {len(scenario.steps)} bodies.")
    return "\n".join(lines)


def check_bodies(scenario: Scenario, subject: str, bodies: list[str]) -> list[str]:
    """Problems with a draft. Empty means it matches the scenario."""
    problems = []
    if not subject.strip():
        problems.append("empty subject")
    if len(bodies) != len(scenario.steps):
        return problems + [f"expected {len(scenario.steps)} bodies, got {len(bodies)}"]
    earlier: list[str] = []  # phrases already used in the thread may be referred to again
    for step, body in zip(scenario.steps, bodies):
        where = f"email {step.position + 1}"
        if not body.strip():
            problems.append(f"{where}: empty body")
        for phrase in step.phrases:
            if phrase not in body:
                problems.append(f"{where}: missing the exact phrase {phrase!r}")
        if not step.phrases and ACTS[step.act].label != "none":
            rest = body
            for phrase in earlier:
                rest = rest.replace(phrase, "")
            if TIME_PATTERN.search(rest):
                problems.append(f"{where}: mentions a new clock time but should not offer any")
        earlier += step.phrases
        if step.act == "still_on" and "?" not in body:
            problems.append(f"{where}: must ask, as a question, whether the meeting is still on")
        if LABEL_WORDS.search(body):
            problems.append(f"{where}: contains a dataset label name")
    return problems


def write_thread(client: anthropic.Anthropic, scenario: Scenario, model: str = MODEL,
                 effort: str = EFFORT) -> dict:
    """Subject and bodies for a scenario, plus usage. Raises RuntimeError after MAX_ATTEMPTS bad drafts."""
    prompt = scenario_prompt(scenario)
    messages = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "attempts": 0}
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        usage["attempts"] = attempt
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["model"] = response.model
        if response.stop_reason == "refusal":
            raise RuntimeError(f"{scenario.thread_id}: the writer declined ({response.stop_details})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            draft = json.loads(text)
            subject, bodies = draft["subject"], draft["bodies"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            problems = [f"unreadable JSON ({error})"]
        else:
            problems = check_bodies(scenario, subject, bodies)
            if not problems:
                return {"subject": subject.strip(), "bodies": [b.strip() for b in bodies], "usage": usage}
        # Show the writer its draft and what to fix, then ask again (append-only history).
        messages = messages + [
            {"role": "assistant", "content": text or "(no text)"},
            {"role": "user", "content": "Fix these problems and return the whole thread again:\n- "
                                        + "\n- ".join(problems)},
        ]
    raise RuntimeError(f"{scenario.thread_id}: no valid draft after {MAX_ATTEMPTS} attempts: {problems}")
