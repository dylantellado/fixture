"""Assemble the eval set from the writer agents' drafts (see README.md, "How it was made").

Usage (from the repo root, plain Python 3.12):

    python3 data/eval/v1/build.py merge UNLABELED_OUT
    python3 data/eval/v1/build.py finalize LABELER_LABELS

merge: reads every draft in data/eval/v1/work/<writer>.jsonl, renumbers the
threads t001, t002, ... per user in order of their first message (so the id
says nothing about who wrote it), and writes:
  - work/merged.jsonl: the threads with the writers' labels and notes
  - UNLABELED_OUT: the same threads with labels and notes removed, for the
    labeler. Put it outside the repo so the labeler sees nothing else.

finalize: reads the labeler's labels (JSONL: user_id, thread_id, position,
label, note) and work/adjudications.json (decisions for every message where
the writer and the labeler disagree), then writes:
  - threads.jsonl: the source-thread format from the Data contract, label = final label
  - annotations.jsonl: one line per message with the writer's notes and all three labels
"""

import json
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
WORK_DIR = EVAL_DIR / "work"
WRITERS = ["terse", "corp", "acad", "auto", "intl", "adv"]  # one draft file per writer agent


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def merge(unlabeled_out: Path) -> None:
    threads = []
    for writer in WRITERS:
        for thread in read_jsonl(WORK_DIR / f"{writer}.jsonl"):
            thread["writer_agent"] = writer
            thread["draft_id"] = thread["thread_id"]
            threads.append(thread)

    # Renumber per user by when each thread starts (ties broken by draft id).
    threads.sort(key=lambda t: (t["user_id"], parsedate_to_datetime(t["messages"][0]["timestamp"]), t["draft_id"]))
    counters = {}
    for thread in threads:
        counters[thread["user_id"]] = counters.get(thread["user_id"], 0) + 1
        thread["thread_id"] = f"t{counters[thread['user_id']]:03d}"
    write_jsonl(WORK_DIR / "merged.jsonl", threads)

    unlabeled = [
        {
            "user_id": t["user_id"],
            "thread_id": t["thread_id"],
            "subject": t["subject"],
            "participants": t["participants"],
            "messages": [
                {k: m[k] for k in ("sender", "recipients", "timestamp", "body")} for m in t["messages"]
            ],
        }
        for t in threads
    ]
    write_jsonl(unlabeled_out, unlabeled)
    print(f"merged {len(threads)} threads, {sum(len(t['messages']) for t in threads)} messages")


def finalize(labels_path: Path) -> None:
    threads = read_jsonl(WORK_DIR / "merged.jsonl")
    labeler = {(r["user_id"], r["thread_id"], r["position"]): r for r in read_jsonl(labels_path)}
    adjudications_path = WORK_DIR / "adjudications.json"
    adjudications = json.loads(adjudications_path.read_text()) if adjudications_path.exists() else {}

    final_threads, annotations, missing = [], [], []
    for thread in threads:
        messages = []
        for position, message in enumerate(thread["messages"]):
            key = (thread["user_id"], thread["thread_id"], position)
            name = "/".join(map(str, key))
            meta = message["meta"]
            intended = message["label"]
            labeled = labeler[key]["label"]

            if intended == labeled:
                final, rationale = intended, meta["rationale"]
            elif name in adjudications:
                final = adjudications[name]["final_label"]
                rationale = f"Writer said {intended}, labeler said {labeled}: {adjudications[name]['rationale']}"
            else:
                missing.append(f"{name}: writer {intended}, labeler {labeled}")
                continue

            # A disagreement can also change difficulty or needs_response.
            override = adjudications.get(name, {})
            messages.append({k: message[k] for k in ("sender", "recipients", "timestamp", "body")} | {"label": final})
            annotations.append({
                "user_id": thread["user_id"],
                "thread_id": thread["thread_id"],
                "position": position,
                "writer_agent": thread["writer_agent"],
                "category": meta["category"],
                "difficulty": override.get("difficulty", meta["difficulty"]),
                "needs_response": override.get("needs_response", meta["needs_response"]),
                "intended_label": intended,
                "labeler_label": labeled,
                "final_label": final,
                "rationale": rationale,
            })
        final_threads.append({k: thread[k] for k in ("user_id", "thread_id", "subject", "participants")} | {"messages": messages})

    if missing:
        print("No adjudication for these disagreements (add them to work/adjudications.json):")
        print("\n".join(f"  {m}" for m in missing))
        sys.exit(1)

    write_jsonl(EVAL_DIR / "threads.jsonl", final_threads)
    write_jsonl(EVAL_DIR / "annotations.jsonl", annotations)
    print(f"wrote {len(final_threads)} threads and {len(annotations)} annotations")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("merge", "finalize"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "merge":
        merge(Path(sys.argv[2]))
    else:
        finalize(Path(sys.argv[2]))
