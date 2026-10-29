"""Check the held-out classifier test set (data/eval/v1/).

Usage (from the repo root, plain Python 3.12, no extra packages):

    python3 data/eval/v1/check.py work FILE [FILE ...]   # a writer's draft threads (with "meta")
    python3 data/eval/v1/check.py final                  # threads.jsonl + annotations.jsonl

Both modes run the Data contract checks from src/ingest/validation.py plus the
rules for this set: Nov 1 to Dec 15, 2026, real-looking UTC offsets with the
right weekday, fictional addresses and phone numbers, and no names reused from
the training corpus (data/source/ and docs/data/generation/).

"final" also checks that annotations.jsonl lines up with threads.jsonl, prints
counts per label, difficulty, category and writer, the labeler agreement rate,
and the closest match between any eval body and any training body.

Exits 1 if there are errors. Warnings are printed for a person to review.
"""

import json
import re
import sys
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src" / "ingest"))

from validation import ALLOWED_LABELS, address_of, parse_timestamp, validate_thread  # noqa: E402

# --- Rules for this set ---

FIRST_DAY, LAST_DAY = date(2026, 11, 1), date(2026, 12, 15)
# "Mon, 02 Nov 2026 09:12:00 -0500"
DATE_HEADER = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$")
# Offsets in use in Nov/Dec 2026 (US is on standard time, Europe on winter time).
ALLOWED_OFFSETS = {
    "-0800", "-0700", "-0600", "-0500",  # US Pacific, Mountain, Central, Eastern
    "-0300",  # Sao Paulo
    "+0000", "+0100", "+0200", "+0300",  # London/Lisbon, Paris/Berlin/Lagos, Athens/Cairo, Nairobi
    "+0530", "+0800", "+0900", "+1100", "+1300",  # India, Singapore, Tokyo, Sydney, Auckland
}
THREAD_ID = re.compile(r"^t\d{3}$")
META_FIELDS = {"category": str, "difficulty": str, "needs_response": bool, "rationale": str}
ANNOTATION_FIELDS = [
    "user_id", "thread_id", "position", "writer_agent", "category", "difficulty",
    "needs_response", "intended_label", "labeler_label", "final_label", "rationale",
]
MIN_PER_LABEL = 30
MIN_HARD_SHARE_OF_NONE = 0.70

# Phone-looking numbers must be in the fictional ranges: US 555-01xx, UK 020 7946 0xxx, UK 07700 900xxx.
PHONE_LIKE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{7,}\d(?![\w-])")
FICTIONAL_PHONE = re.compile(r"555[ .-]?01\d\d|7946[ .-]?0\d{3}|7700[ .-]?900\d{3}")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def is_fictional_address(address: str) -> bool:
    domain = address.lower().rsplit("@", 1)[-1]
    return domain == "example.com" or domain.endswith(".example")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- Names already used in the training corpus ---


# Real places and plain words in the training text that the dictionary check
# would otherwise flag. Reusing these is fine; they aren't invented names.
REAL_PLACES_AND_WORDS = {
    "Abuja", "Bangalore", "Chicago", "Edinburgh", "England", "Europe", "Frankfurt", "Germany",
    "Lagos", "London", "Portland", "Seattle", "Singapore", "Wales", "Gmail", "Email", "Info",
    "Intro", "Online", "Congrats", "Midterm", "Healthcare", "Neuroscience", "Datasets",
    "Webinar", "Webhooks", "Preprocess", "Programme", "Unsubscribe", "Superday", "Travelling",
    "Guten", "Hallo", "Liebe", "Viele", "Vielen", "Kuss", "Mama", "Schatz", "Sonntag",
    "Centre", "Coordinator", "Planned", "Planning", "Women",
}


def is_dictionary_word(word: str, dictionary: set[str]) -> bool:
    """True if the word, or the word without a common ending, is in the dictionary."""
    if word in dictionary:
        return True
    for ending, replacement in (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"), ("ers", ""), ("ers", "e"), ("d", "")):
        if word.endswith(ending) and word[: -len(ending)] + replacement in dictionary:
            return True
    return False


def training_names() -> tuple[set[str], set[str]]:
    """(full names and org names, single proper-noun words) from the training data.

    Full names come from the training threads' participants. Single words are
    capitalized words in the training bodies and generation plans that aren't
    ordinary dictionary words (e.g. "Larkmoor", "Wexley", "Osei"); common first
    names are usually in the dictionary, so they aren't flagged on their own.
    """
    full_names, texts = set(), []
    for thread in read_jsonl(REPO / "data" / "source" / "generated_threads.jsonl"):
        for person in thread["participants"]:
            name = person.split("<")[0].strip().strip('"')
            if name:
                full_names.add(name)
            # The organization's domain name, e.g. "larkmoor" from careers.larkmoor.example.
            full_names.add(address_of(person).rsplit("@", 1)[-1].split(".")[-2])
        texts.extend(m["body"] for m in thread["messages"])
        texts.append(thread["subject"])
    texts.extend(p.read_text() for p in (REPO / "docs" / "data" / "generation").glob("*.md"))
    texts.append((REPO / "docs" / "data" / "corpus_notes.md").read_text())

    dictionary_path = Path("/usr/share/dict/words")
    dictionary = {w.strip().lower() for w in dictionary_path.read_text().splitlines()} if dictionary_path.exists() else None
    words = set()
    if dictionary is not None:
        for text in texts:
            for word in re.findall(r"\b[A-Z][a-z]{3,}\b", text):
                if not is_dictionary_word(word.lower(), dictionary) and word not in REAL_PLACES_AND_WORDS:
                    words.add(word)
    full_names.discard("example")
    full_names.discard("college")
    return full_names, words


def name_reuse(text: str, full_names: set[str], words: set[str]) -> list[str]:
    hits = [n for n in full_names if len(n) > 3 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text)]
    hits += [w for w in words if re.search(rf"\b{w}\b", text)]
    return sorted(set(hits))


# --- Per-thread checks ---


def eval_rule_problems(thread: dict, users: dict) -> tuple[list[str], list[str]]:
    """Rules for this set on top of the Data contract. Returns (errors, warnings)."""
    where = f"{thread['user_id']}/{thread['thread_id']}"
    errors, warnings = [], []

    user = users.get(thread["user_id"])
    if user and user["email"] not in {address_of(p) for p in thread["participants"]}:
        errors.append(f"{where}: the mailbox owner {user['email']} is not in participants")

    for person in thread["participants"]:
        if not is_fictional_address(address_of(person)):
            errors.append(f"{where}: {person!r} is not a fictional (.example) address")

    for position, message in enumerate(thread["messages"]):
        at = f"{where} msg {position}"
        stamp = message["timestamp"]
        if not DATE_HEADER.match(stamp):
            errors.append(f"{at}: timestamp {stamp!r} is not 'Ddd, DD Mon YYYY HH:MM:SS +HHMM'")
            continue
        if stamp[-5:] not in ALLOWED_OFFSETS:
            errors.append(f"{at}: offset {stamp[-5:]} isn't one in use in Nov/Dec 2026 (US Eastern is -0500)")
        sent = parse_timestamp(stamp)
        if sent.strftime("%a") != stamp[:3]:
            errors.append(f"{at}: {stamp[:3]} is the wrong weekday for {sent:%d %b %Y} (it's a {sent:%A})")
        if not FIRST_DAY <= sent.date() <= LAST_DAY:
            errors.append(f"{at}: sent {sent.date()}, outside Nov 1 to Dec 15, 2026")

        for address in ADDRESS.findall(message["body"]):
            if not is_fictional_address(address):
                errors.append(f"{at}: body address {address!r} is not fictional")
        for candidate in PHONE_LIKE.findall(message["body"]):
            digits = re.sub(r"\D", "", candidate)
            if len(digits) >= 10 and not FICTIONAL_PHONE.search(candidate) and not DATE_LIKE.match(candidate.strip()):
                warnings.append(f"{at}: {candidate!r} looks like a non-fictional phone number")

    return errors, warnings


def meta_problems(thread: dict, users: dict) -> list[str]:
    """Writer drafts: every message needs a "meta" block (stripped before threads.jsonl)."""
    errors = []
    owner = users.get(thread["user_id"], {}).get("email")
    for position, message in enumerate(thread["messages"]):
        at = f"{thread['user_id']}/{thread['thread_id']} msg {position}"
        meta = message.get("meta")
        if not isinstance(meta, dict):
            errors.append(f"{at}: missing 'meta' object")
            continue
        for field, kind in META_FIELDS.items():
            if not isinstance(meta.get(field), kind):
                errors.append(f"{at}: meta.{field} must be a {kind.__name__}")
        if meta.get("difficulty") not in ("easy", "hard"):
            errors.append(f"{at}: meta.difficulty must be 'easy' or 'hard'")
        if address_of(message["sender"]) == owner and meta.get("needs_response") is True:
            errors.append(f"{at}: the user sent this message, so needs_response must be false")
    return errors


def check_threads(threads: list[dict], users: dict, final: bool) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    full_names, words = training_names()
    seen = Counter()
    for thread in threads:
        # The contract checks don't look at extra keys, so drafts with "meta" pass through.
        problems = validate_thread(thread, set(users))
        if problems:
            errors.extend(problems)
            continue
        e, w = eval_rule_problems(thread, users)
        errors.extend(e)
        warnings.extend(w)
        where = f"{thread['user_id']}/{thread['thread_id']}"
        seen[(thread["user_id"], thread["thread_id"])] += 1
        if final:
            if not THREAD_ID.match(thread["thread_id"]):
                errors.append(f"{where}: thread_id should look like t001")
            for position, message in enumerate(thread["messages"]):
                extra = set(message) - {"sender", "recipients", "timestamp", "body", "label"}
                if extra:
                    errors.append(f"{where} msg {position}: unexpected fields {sorted(extra)} (annotations go in annotations.jsonl)")
        else:
            errors.extend(meta_problems(thread, users))

        text = "\n".join([thread["subject"], *thread["participants"], *(m["body"] for m in thread["messages"])])
        for hit in name_reuse(text, full_names, words):
            warnings.append(f"{where}: uses {hit!r}, which appears in the training corpus")

    for key, count in seen.items():
        if count > 1:
            errors.append(f"{key[0]}/{key[1]}: appears {count} times")
    return errors, warnings


def print_counts(title: str, counter: Counter) -> None:
    print(f"\n{title}:")
    for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0]))):
        print(f"  {str(key):32} {count}")


# --- Leakage against the training corpus ---


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def shingles(text: str, size: int = 5) -> set[str]:
    return {text[i : i + size] for i in range(max(1, len(text) - size + 1))}


def closest_training_bodies(eval_bodies: list[tuple[str, str]], top: int = 5) -> list[tuple[float, str, str]]:
    """The eval bodies most similar to any training body.

    Character 5-gram overlap finds the best candidate for each eval body
    quickly; difflib's ratio then measures that pair (0 = nothing shared, 1 = identical).
    """
    training = []
    for thread in read_jsonl(REPO / "data" / "source" / "generated_threads.jsonl"):
        for position, message in enumerate(thread["messages"]):
            text = normalize(message["body"])
            training.append((f"{thread['user_id']}/{thread['thread_id']} msg {position}", text, shingles(text)))

    results = []
    for eval_where, body in eval_bodies:
        text = normalize(body)
        grams = shingles(text)
        best = max(training, key=lambda t: len(grams & t[2]) / (len(grams | t[2]) or 1))
        results.append((SequenceMatcher(None, text, best[1]).ratio(), eval_where, best[0]))
    return sorted(results, reverse=True)[:top]


# --- Modes ---


def check_work(paths: list[Path], users: dict) -> int:
    threads = [thread for path in paths for thread in read_jsonl(path)]
    errors, warnings = check_threads(threads, users, final=False)
    labels, categories, hard_none = Counter(), Counter(), 0
    for thread in threads:
        for message in thread["messages"]:
            labels[message.get("label")] += 1
            meta = message.get("meta") or {}
            categories[meta.get("category")] += 1
            hard_none += message.get("label") == "none" and meta.get("difficulty") == "hard"

    for warning in warnings:
        print(f"WARNING {warning}")
    for error in errors:
        print(f"ERROR   {error}")
    print(f"\n{len(threads)} threads, {sum(labels.values())} messages ({hard_none} hard negatives)")
    print_counts("Per label", labels)
    print_counts("Per category", categories)
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def check_final(users: dict) -> int:
    threads = read_jsonl(EVAL_DIR / "threads.jsonl")
    annotations = read_jsonl(EVAL_DIR / "annotations.jsonl")
    errors, warnings = check_threads(threads, users, final=True)

    # One annotation per message, keyed by (user_id, thread_id, position), agreeing with threads.jsonl.
    labels_in_threads = {
        (t["user_id"], t["thread_id"], position): m["label"]
        for t in threads
        for position, m in enumerate(t["messages"])
    }
    by_key = {}
    for row in annotations:
        missing = [f for f in ANNOTATION_FIELDS if f not in row]
        if missing:
            errors.append(f"annotation {row.get('user_id')}/{row.get('thread_id')}/{row.get('position')}: missing {missing}")
            continue
        key = (row["user_id"], row["thread_id"], row["position"])
        if key in by_key:
            errors.append(f"annotation {key}: appears twice")
        by_key[key] = row
        for field in ("intended_label", "labeler_label", "final_label"):
            if row[field] not in ALLOWED_LABELS:
                errors.append(f"annotation {key}: {field} {row[field]!r} is not a label")
        if row["difficulty"] not in ("easy", "hard"):
            errors.append(f"annotation {key}: difficulty must be easy or hard")
        if not isinstance(row["needs_response"], bool):
            errors.append(f"annotation {key}: needs_response must be true or false")
        if key in labels_in_threads and labels_in_threads[key] != row["final_label"]:
            errors.append(f"annotation {key}: final_label {row['final_label']} but threads.jsonl says {labels_in_threads[key]}")
    for key in labels_in_threads.keys() - by_key.keys():
        errors.append(f"message {key}: has no annotation")
    for key in by_key.keys() - labels_in_threads.keys():
        errors.append(f"annotation {key}: no such message in threads.jsonl")

    rows = list(by_key.values())
    labels = Counter(r["final_label"] for r in rows)
    none_rows = [r for r in rows if r["final_label"] == "none"]
    hard_none = sum(r["difficulty"] == "hard" for r in none_rows)
    agree = sum(r["intended_label"] == r["labeler_label"] for r in rows)

    for label in sorted(ALLOWED_LABELS):
        if labels[label] < MIN_PER_LABEL:
            errors.append(f"label {label}: only {labels[label]} messages (need at least {MIN_PER_LABEL})")
    if none_rows and hard_none / len(none_rows) < MIN_HARD_SHARE_OF_NONE:
        errors.append(f"hard negatives are {hard_none}/{len(none_rows)} of 'none' (need at least {MIN_HARD_SHARE_OF_NONE:.0%})")

    for warning in warnings:
        print(f"WARNING {warning}")
    for error in errors:
        print(f"ERROR   {error}")

    print(f"\n{len(threads)} threads, {len(rows)} messages, {len(users)} users")
    print_counts("Per label (final)", labels)
    print(f"\n'none': {len(none_rows)} messages, {hard_none} hard ({hard_none / max(1, len(none_rows)):.0%})")
    print_counts("Per difficulty", Counter(r["difficulty"] for r in rows))
    print_counts("Per writer agent", Counter(r["writer_agent"] for r in rows))
    print_counts("Per category", Counter(r["category"] for r in rows))
    print_counts("Per user", Counter(r["user_id"] for r in rows))
    print_counts("needs_response", Counter(r["needs_response"] for r in rows))
    print(f"\nLabeler agreed with the writer on {agree}/{len(rows)} messages ({agree / max(1, len(rows)):.1%})")

    bodies = [(f"{t['user_id']}/{t['thread_id']} msg {p}", m["body"]) for t in threads for p, m in enumerate(t["messages"])]
    closest = closest_training_bodies(bodies)
    print("\nClosest eval body to any training body (difflib ratio, 1.0 = identical):")
    for ratio, eval_where, train_where in closest:
        print(f"  {ratio:.3f}  {eval_where}  ~  {train_where}")
    if closest and closest[0][0] >= 0.8:
        errors.append(f"an eval body closely matches a training body (ratio {closest[0][0]:.3f})")
        print(f"ERROR   {errors[-1]}")

    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("work", "final") or (sys.argv[1] == "work" and len(sys.argv) < 3):
        print(__doc__)
        return 2
    users = {u["user_id"]: u for u in json.loads((EVAL_DIR / "users.json").read_text())}
    if sys.argv[1] == "work":
        return check_work([Path(p) for p in sys.argv[2:]], users)
    return check_final(users)


if __name__ == "__main__":
    sys.exit(main())
