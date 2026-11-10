"""A harness: everything around the model that decides how an email is classified.

One YAML file in harnesses/ holds the instructions, model, thinking budget,
context window and which rules file (and sections) to send. The prompt format
follows src/classifier/prompt.py so the prod_v1 harness matches production
(copied, not imported: services and experiments don't import each other).
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS = ["new_request", "proposed_times", "acceptance", "reschedule", "assistant_handoff", "none"]

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reason": {"type": "STRING"},
        "label": {"type": "STRING", "enum": LABELS},
        "needs_response": {"type": "BOOLEAN"},
    },
    "required": ["reason", "label", "needs_response"],
    "propertyOrdering": ["reason", "label", "needs_response"],
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Harness:
    name: str
    path: Path
    text: str  # the YAML file as written; its hash identifies the harness
    config: dict
    rules_text: str  # what reaches the model
    rules_version: str
    rules_file_sha: str  # hash of the whole rules file

    @property
    def sha(self) -> str:
        return sha256(self.text)[:12]

    @property
    def system(self) -> str:
        return self.config["instructions"].rstrip() + "\n\n" + self.rules_text

    def summary(self) -> dict:
        """What W&B records as the run's config."""
        c = self.config
        return {
            "harness": self.name, "harness_sha": self.sha, "model": c["model"], "location": c["location"],
            "thinking_budget": c.get("thinking_budget"), "max_earlier_messages": c["max_earlier_messages"],
            "max_body_chars": c["max_body_chars"], "rules_path": c["rules_path"],
            "rules_version": self.rules_version, "rules_file_sha256": self.rules_file_sha,
            "rules_sent_sha256": sha256(self.rules_text), "excluded_sections": c["excluded_sections"],
            "system_prompt_sha256": sha256(self.system),
        }


def rules_version(text: str) -> str:
    match = re.search(r"\*\*Version ([0-9][0-9.]*)", text)
    if not match:
        raise ValueError("labeling rules have no '**Version X.Y' line")
    return match.group(1).rstrip(".")


def strip_sections(text: str, excluded: list[str]) -> str:
    """Drop the '## ...' sections whose heading contains an excluded name. Each must match exactly once."""
    parts = re.split(r"(?m)^(?=## )", text)
    headings = [p.splitlines()[0].lower() if p.startswith("## ") else "" for p in parts]
    for name in excluded:
        found = sum(name in h for h in headings)
        if found != 1:
            raise ValueError(f"rules: expected one '## ...{name}...' heading to exclude, found {found}")
    kept = [p for p, h in zip(parts, headings) if not any(name in h for name in excluded)]
    return "".join(kept).strip() + "\n"


def load_harness(path: Path, rules_override: Path | None = None) -> Harness:
    """Load a harness file. rules_override swaps in another rules file (e.g. a draft v1.6)."""
    text = Path(path).read_text()
    config = yaml.safe_load(text)
    for key in ("name", "model", "location", "max_earlier_messages", "max_body_chars", "rules_path",
                "excluded_sections", "instructions"):
        if key not in config:
            raise ValueError(f"{path}: missing '{key}'")
    rules_path = Path(rules_override) if rules_override else REPO_ROOT / config["rules_path"]
    if rules_override:
        config = {**config, "rules_path": str(rules_override)}
    raw = rules_path.read_text()
    return Harness(config["name"], Path(path), text, config, strip_sections(raw, config["excluded_sections"]),
                   rules_version(raw), sha256(raw))


def _neutralize(text: str) -> str:
    return re.sub(r"<(/?)\s*(earlier_message|target_email)", r"<\1 \2", text, flags=re.IGNORECASE)


def _block(tag: str, message: dict, max_chars: int, extra: str = "") -> str:
    body = message["body"]
    if len(body) > max_chars:
        body = body[:max_chars] + "\n[... cut: the rest of this email is not shown]"
    who = " (sent by the user)" if message["from_user"] else ""
    header = f"From: {message['sender']}{who}\n"
    if message.get("recipients"):
        header += f"To: {', '.join(message['recipients'])}\n"
    header += f"Date: {message['timestamp']}\nSubject: {message['subject']}\n\n"
    return f"<{tag}{extra}>\n{_neutralize(header + body)}\n</{tag}>"


def user_prompt(harness: Harness, thread: list[dict], target_index: int) -> str:
    """Earlier messages oldest-first (up to max_earlier_messages), then the target. Later ones are never shown."""
    limit, max_chars = harness.config["max_earlier_messages"], harness.config["max_body_chars"]
    earlier = thread[:target_index][-limit:] if limit else []
    skipped = target_index - len(earlier)
    parts = []
    if earlier:
        intro = f"Earlier messages in this thread, oldest first ({len(earlier)} shown"
        intro += f", {skipped} older ones left out)." if skipped else ")."
        parts.append(intro)
        parts += [_block("earlier_message", m, max_chars, f' number="{skipped + 1 + i}"')
                  for i, m in enumerate(earlier)]
    else:
        parts.append("This is the first message in its thread.")
    parts.append("The email to label:")
    parts.append(_block("target_email", thread[target_index], max_chars))
    parts.append("Label the target email. Answer in JSON only.")
    return "\n\n".join(parts)
