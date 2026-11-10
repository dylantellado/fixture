"""Make clean bodies look like real email: signatures, phone sign-offs, quoted history, footers.

Done in code with a seeded RNG, not by the writer, so it is controlled and
logged: every change is recorded per message. Preprocess later removes quoted
history and signatures again, which tests that cleaning.
"""

import random

from sampler import Scenario
from times import header_date

LEGAL_FOOTER = ("\n\n--\nThis email and any attachments are confidential and intended solely for the addressee. "
                "If you received it in error, please notify the sender and delete it.")


def add_mess(scenario: Scenario, bodies: list[str], seed: int) -> tuple[list[str], list[list[str]]]:
    """(messy bodies, list of changes per message)."""
    rng = random.Random(f"{seed}:mess:{scenario.user['user_id']}:{scenario.thread_id}")
    out, changes = [], []
    for i, (step, body) in enumerate(zip(scenario.steps, bodies)):
        done = []
        sender = step.sender
        if sender.role in ("them", "assistant", "intro") and rng.random() < 0.6:
            body += f"\n\n{sender.name}\n{sender.title}" + (f" | {sender.org}" if sender.org else "")
            done.append("signature")
        if sender.role == "user" and rng.random() < 0.25:
            body += "\n\nSent from my iPhone"
            done.append("phone sign-off")
        if "writes from phone" in sender.style and rng.random() < 0.7:
            body += "\n\nSent from my phone"
            done.append("phone sign-off")
        if scenario.kind in ("recruiter", "hiring_manager") and sender.role != "user" and rng.random() < 0.5:
            body += LEGAL_FOOTER
            done.append("legal footer")
        if i > 0 and rng.random() < 0.4:
            previous = scenario.steps[i - 1]
            quoted = "\n".join("> " + line for line in out[i - 1].splitlines())
            body += f"\n\nOn {header_date(previous.sent)}, {previous.sender.address} wrote:\n{quoted}"
            done.append("quoted history")
        out.append(body)
        changes.append(done)
    return out, changes
