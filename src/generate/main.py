"""Generate fictional scheduling threads from ground-truth states, and assemble data/source.

Two commands, both run from the repo root by DVC (see dvc.yaml):

  generate  cards + seed -> scenarios -> Claude writes the emails -> data/generated/
  assemble  data/base/ (data-v1) + data/generated/ -> data/source/ (what ingest reads)

Every Claude write is cached in data/cache/generate/writes.jsonl, keyed by the
hash of the exact prompt, so a rerun (or a crash halfway) never pays for the
same thread twice. Use --dry-run to see the scenarios without calling Claude.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from acts import check_flows
from mess import add_mess
from sampler import (build_scenario, cards_version, load_cards, to_annotations, to_source_thread,
                     to_state_record)
from writer import EFFORT, MODEL, scenario_prompt, write_thread

log = logging.getLogger("generate")
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    tmp.replace(path)  # never leave a half-written file


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_env_key(env_file: Path = REPO_ROOT / ".env") -> None:
    """Use ANTHROPIC_API_KEY from the repo's .env when it isn't already set (dvc runs a plain shell)."""
    if os.environ.get("ANTHROPIC_API_KEY") or not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "ANTHROPIC_API_KEY" and value.strip():
            os.environ["ANTHROPIC_API_KEY"] = value.strip().strip('"').strip("'")


def generate(args) -> int:
    problems = check_flows()
    if problems:
        log.error("acts table is inconsistent: %s", problems)
        return 1
    cards = load_cards()
    cards_hash = cards_version()
    users = [u for u in cards["users"] if not args.users or u["user_id"] in args.users]
    scenarios = [build_scenario(cards, u, n, args.seed) for u in users for n in range(1, args.threads_per_user + 1)]
    log.info("%d scenarios for %d users (seed %s, cards %s)", len(scenarios), len(users), args.seed, cards_hash)
    if args.limit:
        scenarios = scenarios[:args.limit]

    if args.dry_run:
        for s in scenarios[:args.show]:
            print(f"--- {s.user['user_id']}/{s.thread_id} flow={s.flow} kind={s.kind}")
            print(scenario_prompt(s))
            for step in s.steps:
                print(f"   [{step.position}] {step.role:9s} {step.act:20s} {step.label:17s} "
                      f"needs_response={step.needs_response} ({step.rule})")
        return 0

    cache_path = DATA / "cache" / "generate" / "writes.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = {r["prompt_sha"]: r for r in read_jsonl(cache_path)}
    todo = []
    for s in scenarios:
        sha = hashlib.sha256(f"{args.model}|{args.effort}|{scenario_prompt(s)}".encode()).hexdigest()
        if sha not in cache:
            todo.append((s, sha))
    log.info("%d threads cached, %d to write with %s", len(scenarios) - len(todo), len(todo), args.model)

    failures = []
    if todo:
        import anthropic  # only needed when something must be written
        load_env_key()
        client = anthropic.Anthropic(max_retries=4)
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(write_thread, client, s, args.model, args.effort): (s, sha) for s, sha in todo}
            for done, future in enumerate(as_completed(futures), 1):
                s, sha = futures[future]
                key = f"{s.user['user_id']}/{s.thread_id}"
                try:
                    written = future.result()
                except Exception as error:  # record and keep going; the run fails at the end
                    failures.append(f"{key}: {error}")
                    log.warning("failed %s: %s", key, error)
                    continue
                record = {"prompt_sha": sha, "key": key, **written}
                cache[sha] = record
                with cache_path.open("a") as f:  # append right away, so a crash loses nothing
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.info("[%d/%d] wrote %s (%s attempts)", done, len(todo), key, written["usage"]["attempts"])
    if failures:
        log.error("%d threads failed; nothing written to %s. Rerun to retry only those.", len(failures), args.out)
        return 1

    threads, annotations, states, gen_log = [], [], [], []
    for s in scenarios:
        sha = hashlib.sha256(f"{args.model}|{args.effort}|{scenario_prompt(s)}".encode()).hexdigest()
        written = cache[sha]
        bodies, mess = add_mess(s, written["bodies"], args.seed)
        threads.append(to_source_thread(s, written["subject"], bodies))
        annotations += to_annotations(s)
        states.append(to_state_record(s, cards_hash))
        gen_log.append({"user_id": s.user["user_id"], "thread_id": s.thread_id, "flow": s.flow,
                        "counterpart": s.kind, "seed": s.seed, "cards_version": cards_hash,
                        "prompt_sha": sha, "usage": written["usage"], "mess": mess})
    out = Path(args.out)
    write_jsonl(out / "threads.jsonl", threads)
    write_jsonl(out / "annotations.jsonl", annotations)
    write_jsonl(out / "thread_states.jsonl", states)
    write_jsonl(out / "generation_log.jsonl", gen_log)
    (out / "users.json").write_text(json.dumps(
        [{"user_id": u["user_id"], "name": u["name"], "email": u["email"], "split": u["split"]} for u in users],
        indent=2) + "\n")
    tokens_in = sum(r["usage"]["input_tokens"] for r in gen_log)
    tokens_out = sum(r["usage"]["output_tokens"] for r in gen_log)
    log.info("wrote %d threads, %d messages to %s (writer tokens: %d in, %d out)", len(threads),
             len(annotations), out, tokens_in, tokens_out)
    return 0


def assemble(args) -> int:
    """data/base (v1) + data/generated -> data/source, in the Data contract's file names."""
    base, generated, out = Path(args.base), Path(args.generated), Path(args.out)
    base_users = json.loads((base / "users.json").read_text())
    gen_users = json.loads((generated / "users.json").read_text())
    ids = [u["user_id"] for u in base_users + gen_users]
    if len(ids) != len(set(ids)):
        log.error("a user_id appears in both data/base and data/generated")
        return 1
    users = base_users + [{k: u[k] for k in ("user_id", "name", "email")} for u in gen_users]
    out.mkdir(parents=True, exist_ok=True)
    (out / "users.json").write_text(json.dumps(users, indent=2) + "\n")
    write_jsonl(out / "generated_threads.jsonl",
                read_jsonl(base / "generated_threads.jsonl") + read_jsonl(generated / "threads.jsonl"))
    write_jsonl(out / "annotations.jsonl",
                read_jsonl(base / "annotations.jsonl") + read_jsonl(generated / "annotations.jsonl"))
    write_jsonl(out / "thread_states.jsonl", read_jsonl(generated / "thread_states.jsonl"))
    # Which users may be used for tuning. data-v1 users are training data; eval-v1 lives in data/eval/.
    splits = {"train": [u["user_id"] for u in base_users] + [u["user_id"] for u in gen_users if u["split"] == "train"],
              "eval": [u["user_id"] for u in gen_users if u["split"] == "eval"]}
    (out / "splits.json").write_text(json.dumps(splits, indent=2) + "\n")
    log.info("assembled %d users (%d train, %d eval) into %s", len(users), len(splits["train"]),
             len(splits["eval"]), out)
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="write threads with Claude into data/generated/")
    g.add_argument("--seed", type=int, default=2026)
    g.add_argument("--threads-per-user", type=int, default=30)
    g.add_argument("--users", nargs="*", help="only these user_ids (default: every user in cards/users.yaml)")
    g.add_argument("--model", default=MODEL)
    g.add_argument("--effort", default=EFFORT)
    g.add_argument("--concurrency", type=int, default=4)
    g.add_argument("--limit", type=int, help="only the first N scenarios (for a quick check)")
    g.add_argument("--out", default=str(DATA / "generated"))
    g.add_argument("--dry-run", action="store_true", help="print scenarios and answers; no API calls")
    g.add_argument("--show", type=int, default=5, help="scenarios to print with --dry-run")
    a = sub.add_parser("assemble", help="combine data/base and data/generated into data/source")
    a.add_argument("--base", default=str(DATA / "base"))
    a.add_argument("--generated", default=str(DATA / "generated"))
    a.add_argument("--out", default=str(DATA / "source"))
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s generate: %(message)s")
    args = parse_args(argv)
    return generate(args) if args.command == "generate" else assemble(args)


if __name__ == "__main__":
    sys.exit(main())
