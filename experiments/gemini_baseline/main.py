"""Gemini baseline: label every training message with Gemini and score it.

One Vertex AI call per message: the labeling rules as the system part, the
thread so far as the user part, structured JSON output, temperature 0. Writes
runs/<timestamp>/predictions.jsonl and report.md (see README.md).

Training data only (user_01 to user_04). eval-v1 is frozen: any path under
data/eval/ or user_id starting with eval_ exits with an error before anything runs.

Run from experiments/gemini_baseline:
  uv run python main.py --limit 20
  uv run python main.py
"""

import argparse
import json
import logging
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import gemini
import prompt
import scoring
from data import (
    ANNOTATIONS_PATH,
    MESSAGES_PATH,
    REPO_ROOT,
    TRAINING_USERS,
    USERS_PATH,
    DataError,
    group_threads,
    load_training,
    refuse_eval_path,
    refuse_eval_user,
)

log = logging.getLogger("gemini_baseline")

# Newest Flash model that answered on this project (checked 2026-10-29).
DEFAULT_MODEL = "gemini-3.8-flash"
# A small thinking budget kept label quality on the training data at a third less
# cost and latency (README, "Thinking budget"). "--thinking-budget default" turns it off.
DEFAULT_THINKING_BUDGET = 128
RUNS_DIR = Path(__file__).resolve().parent / "runs"

# Fields written to predictions.jsonl, in this order.
PREDICTION_FIELDS = [
    "message_id", "user_id", "thread_id", "position", "subject",
    "true_label", "pred_label", "true_needs_response", "pred_needs_response", "reason",
    "latency_s", "input_tokens", "cached_input_tokens", "output_tokens", "thinking_tokens",
    "attempts", "model_version", "error",
]  # fmt: skip


def parse_budget(value: str) -> int | None:
    """'128' -> 128; 'default' -> None (the model decides how much to think)."""
    return None if value == "default" else int(value)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model id (default {DEFAULT_MODEL})")
    p.add_argument("--limit", type=int, help="only the first N messages (in user, thread, position order)")
    p.add_argument("--concurrency", type=int, default=4, help="parallel calls (default 4)")
    p.add_argument(
        "--thinking-budget",
        type=parse_budget,
        default=DEFAULT_THINKING_BUDGET,
        help=f"cap on thinking tokens per call (default {DEFAULT_THINKING_BUDGET}); 'default' for the model's own",
    )
    p.add_argument("--users", nargs="+", default=TRAINING_USERS, help="training users to run (default all four)")
    p.add_argument("--messages", type=Path, default=MESSAGES_PATH, help="processed messages.jsonl")
    p.add_argument("--annotations", type=Path, default=ANNOTATIONS_PATH, help="training annotations.jsonl")
    p.add_argument("--project", default=gemini.PROJECT)
    p.add_argument("--location", default=gemini.LOCATION)
    p.add_argument("--price-input", type=float, help="US$ per 1M input tokens (default: from scoring.PRICES)")
    p.add_argument("--price-output", type=float, help="US$ per 1M output+thinking tokens")
    return p.parse_args(argv)


def check_not_eval(args: argparse.Namespace) -> None:
    """Refuse eval data before anything is read or sent."""
    for path in (args.messages, args.annotations, USERS_PATH):
        refuse_eval_path(path)
    for user_id in args.users:
        refuse_eval_user(user_id)
        if user_id not in TRAINING_USERS:
            raise DataError(f"unknown user {user_id!r}: choose from {TRAINING_USERS}")


def git_commit() -> str:
    def git(*cmd):
        return subprocess.run(["git", *cmd], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()

    commit = git("rev-parse", "HEAD") or "unknown"
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return commit + (" (uncommitted changes)" if dirty else "")


def build_jobs(messages, owners, users, limit):
    """(message, user prompt) for each message to run. Threads use all messages, so context is complete."""
    threads = group_threads(messages)
    owner_strings = {u: prompt.owner_address([m for m in messages if m["user_id"] == u], owners[u]) for u in owners}
    selected = [m for m in messages if m["user_id"] in users][:limit]
    return [
        (m, prompt.user_prompt(threads[(m["user_id"], m["thread_id"])], m["position"], owner_strings[m["user_id"]]))
        for m in selected
    ]


def run(jobs, client, model, system, concurrency, thinking_budget=None) -> list[dict]:
    rows = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(gemini.classify, client, model, system, user, thinking_budget): m for m, user in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            m = futures[future]
            result = future.result()
            rows.append(
                {
                    "message_id": m["message_id"],
                    "user_id": m["user_id"],
                    "thread_id": m["thread_id"],
                    "position": m["position"],
                    "subject": m["subject"],
                    "true_label": m["label"],
                    "true_needs_response": m["true_needs_response"],
                    "hard_negative": m.get("hard_negative"),
                }
                | result
            )
            if result["error"]:
                log.warning("%s failed: %s", m["message_id"], result["error"])
            if done % 25 == 0 or done == len(jobs):
                log.info("%d/%d done", done, len(jobs))
    rows.sort(key=lambda r: (r["user_id"], r["thread_id"], r["position"]))
    return rows


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = parse_args(argv)
    try:
        check_not_eval(args)
        messages, owners = load_training(args.messages, args.annotations, USERS_PATH)
    except DataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    log.info("training data OK: %d messages, labels %s", len(messages), dict(Counter(m["label"] for m in messages)))

    rules_text, rules_version = prompt.load_rules()
    system = prompt.system_prompt(rules_text)
    jobs = build_jobs(messages, owners, args.users, args.limit)

    started = datetime.now(timezone.utc)
    run_dir = RUNS_DIR / started.strftime("%Y%m%d-%H%M%SZ")
    run_dir.mkdir(parents=True)
    (run_dir / "system_prompt.txt").write_text(system, encoding="utf-8")
    log.info(
        "model %s, %d messages, concurrency %d, thinking budget %s, rules v%s sha256 %s -> %s",
        args.model, len(jobs), args.concurrency, args.thinking_budget, rules_version, prompt.text_sha256(rules_text)[:12], run_dir,
    )  # fmt: skip

    client = gemini.make_client(args.project, args.location)
    rows = run(jobs, client, args.model, system, args.concurrency, args.thinking_budget)

    with open(run_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({k: row.get(k) for k in PREDICTION_FIELDS}) + "\n")

    prices = scoring.PRICES.get(args.model)
    if args.price_input is not None and args.price_output is not None:
        prices = (args.price_input, args.price_output)
    df = pd.DataFrame(rows)
    info = {
        "model": args.model,
        "model_versions": sorted({r["model_version"] for r in rows if r.get("model_version")}),
        "project": args.project,
        "location": args.location,
        "rules_version": rules_version,
        "rules_sha256": prompt.text_sha256(rules_text),
        "thinking_budget": args.thinking_budget,
        "annotation_rules_version": ", ".join(sorted({m["annotation_rules_version"] for m in messages})),
        "git_commit": git_commit(),
        "date": started.strftime("%Y-%m-%d %H:%M UTC"),
        "limit": args.limit,
        "concurrency": args.concurrency,
        "prices": prices,
    }
    (run_dir / "report.md").write_text(scoring.render_report(df, info), encoding="utf-8")

    failures = int(df["error"].notna().sum())
    log.info(
        "label accuracy %.3f, scheduling recall %.3f, needs_response accuracy %.3f, failures %d",
        scoring.label_accuracy(df),
        scoring.scheduling_recall(df)["recall"],
        scoring.needs_response_metrics(df)["accuracy"],
        failures,
    )
    log.info("wrote %s", run_dir / "report.md")
    return 1 if failures == len(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
