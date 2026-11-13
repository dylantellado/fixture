"""One tuning run: classify every message in a split with a harness, score it, log it to W&B.

  uv run python main.py --harness harnesses/prod_v1.yaml                 # train split, all messages
  uv run python main.py --harness harnesses/prod_v1.yaml --limit 30      # quick check
  uv run python main.py --harness harnesses/prod_v1.yaml --rules /tmp/labeling_rules_v1.6.md
  uv run python main.py --harness harnesses/prod_v1.yaml --split eval    # final report only, never for tuning

W&B gets the harness file and the rules file as versioned artifacts, every
setting and data hash as the run config, the scores as the summary, and every
prediction as a table. Without W&B credentials, set WANDB_MODE=offline (synced
later with `wandb sync`) or pass --no-wandb.
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from data import PATHS, load
from harness import RESPONSE_SCHEMA, LABELS, load_harness, user_prompt
from scoring import confusion, score

log = logging.getLogger("tuning")
HERE = Path(__file__).parent
WANDB_PROJECT = "fixture-classifier"
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "fixture-ac215-96dhbm")
TRANSIENT = {408, 429, 500, 502, 503, 504}


def gemini_client(location: str):
    from google import genai
    from google.genai import types
    return genai.Client(vertexai=True, project=GCP_PROJECT, location=location,
                        http_options=types.HttpOptions(timeout=60_000))


def classify(client, harness, prompt: str) -> dict:
    """One Gemini call with structured output; retries rate limits and server errors."""
    from google.genai import errors, types
    config = types.GenerateContentConfig(
        system_instruction=harness.system, temperature=0, response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        thinking_config=(types.ThinkingConfig(thinking_budget=harness.config["thinking_budget"])
                         if harness.config.get("thinking_budget") is not None else None),
    )
    for attempt in range(1, 7):
        started = time.monotonic()
        try:
            response = client.models.generate_content(model=harness.config["model"], contents=prompt, config=config)
            answer = json.loads(response.text or "")
            if answer.get("label") not in LABELS or not isinstance(answer.get("needs_response"), bool):
                raise ValueError("answer doesn't match the schema")
            usage = response.usage_metadata
            return {"label": answer["label"], "needs_response": answer["needs_response"],
                    "reason": " ".join(str(answer.get("reason", "")).split()),
                    "latency_s": round(time.monotonic() - started, 2), "attempts": attempt,
                    "input_tokens": (usage and usage.prompt_token_count) or 0,
                    "output_tokens": (usage and usage.candidates_token_count) or 0,
                    "thinking_tokens": (usage and usage.thoughts_token_count) or 0}
        except errors.APIError as error:
            if error.code not in TRANSIENT or attempt == 6:
                raise
        time.sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))
    raise RuntimeError("unreachable")


def run_predictions(harness, threads, concurrency: int, limit: int | None) -> list[dict]:
    jobs = [(m, user_prompt(harness, messages, i)) for messages in threads.values() for i, m in enumerate(messages)]
    jobs.sort(key=lambda j: (j[0]["user_id"], j[0]["thread_id"], j[0]["position"]))
    if limit:
        jobs = jobs[:limit]
    client = gemini_client(harness.config["location"])

    def one(job):
        message, prompt = job
        base = {k: message[k] for k in ("message_id", "user_id", "thread_id", "position", "act", "source_set",
                                        "from_user", "true_label", "true_needs_response")}
        try:
            return {**base, **classify(client, harness, prompt), "error": None}
        except Exception as error:  # recorded and counted, not scored
            return {**base, "label": None, "needs_response": None, "reason": "", "error": f"{type(error).__name__}: {error}"}

    log.info("classifying %d messages with %s (%s)", len(jobs), harness.name, harness.config["model"])
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(one, jobs))


def load_wandb_key_from_secret() -> None:
    """On Vertex AI, read the W&B key from Secret Manager (WANDB_API_KEY_SECRET names the version).

    Locally `wandb login` (~/.netrc) is used instead, and nothing here runs.
    """
    secret = os.environ.get("WANDB_API_KEY_SECRET")
    if not secret or os.environ.get("WANDB_API_KEY"):
        return
    from google.cloud import secretmanager
    payload = secretmanager.SecretManagerServiceClient().access_secret_version(name=secret).payload.data
    os.environ["WANDB_API_KEY"] = payload.decode().strip()


def git_commit() -> str:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                                cwd=HERE).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=HERE).stdout
        return commit + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report(run_name: str, config: dict, metrics: dict, predictions: list[dict]) -> str:
    lines = [f"# Tuning run {run_name}", "", "| Setting | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in config.items()]
    lines += ["", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v:.3f} |" if isinstance(v, float) else f"| {k} | {v} |" for k, v in sorted(metrics.items())]
    misses = [p for p in predictions if p.get("error") is None and p["needs_response"] != p["true_needs_response"]]
    lines += ["", f"## needs_response mistakes ({len(misses)})", "", "| message | act | true | predicted | reason |",
              "|---|---|---|---|---|"]
    lines += [f"| {p['user_id']}/{p['thread_id']}/{p['position']} | {p['act'] or '-'} | {p['true_needs_response']} "
              f"| {p['needs_response']} | {p['reason']} |" for p in misses]
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", type=Path, default=HERE / "harnesses" / "prod_v1.yaml")
    p.add_argument("--rules", type=Path, help="use this rules file instead of the harness's (e.g. a draft)")
    p.add_argument("--split", default="train", choices=["train", "eval"])
    p.add_argument("--data-root", help="read data/... from here instead of the repo (e.g. gs://bucket/run)")
    p.add_argument("--limit", type=int)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--no-wandb", action="store_true")
    p.add_argument("--notes", default="", help="what this run tries (shown in W&B)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s tuning: %(message)s")
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args = parse_args(argv)
    harness = load_harness(args.harness, args.rules)
    paths = None
    if args.data_root:
        root = args.data_root.rstrip("/")
        paths = {k: f"{root}/{Path(v).relative_to(PATHS['messages'].parents[1])}" for k, v in PATHS.items()}
    threads, versions = load(args.split, paths)
    if args.split == "eval":
        log.warning("eval split: report this run, but never change a harness or rule because of it")

    run_name = f"{harness.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}"
    config = {**harness.summary(), **versions, "split": args.split, "limit": args.limit,
              "messages": sum(len(t) for t in threads.values()), "git_commit": git_commit()}

    wb = None
    if not args.no_wandb:
        import wandb
        load_wandb_key_from_secret()
        wb = wandb.init(project=WANDB_PROJECT, name=run_name, job_type="final_eval" if args.split == "eval" else "tune",
                        config=config, notes=args.notes, tags=[harness.name, f"rules-{harness.rules_version}", args.split])
        files = [("harness", harness.path, harness.name)]
        if harness.config["rules_path"]:  # simple_v1 and the like send no rules file
            files.append(("rules", Path(harness.config["rules_path"]) if args.rules else
                          Path(__file__).resolve().parents[2] / harness.config["rules_path"], "labeling_rules"))
        for kind, path, name in files:
            artifact = wandb.Artifact(name, type=kind, metadata={"sha": harness.sha if kind == "harness"
                                                                 else harness.rules_file_sha,
                                                                 "rules_version": harness.rules_version})
            artifact.add_file(str(path))
            wb.log_artifact(artifact)

    started = time.monotonic()
    predictions = run_predictions(harness, threads, args.concurrency, args.limit)
    metrics = score(predictions)
    metrics["wall_time_s"] = round(time.monotonic() - started, 1)
    metrics["tokens/input"] = sum(p.get("input_tokens", 0) for p in predictions)
    metrics["tokens/output_and_thinking"] = sum(p.get("output_tokens", 0) + p.get("thinking_tokens", 0)
                                                for p in predictions)
    log.info("needs_response accuracy %.3f, recall %.3f, missed %d; label accuracy %.3f; %d failures",
             metrics["needs_response/accuracy"], metrics["needs_response/recall"], metrics["needs_response/missed"],
             metrics["label/accuracy"], metrics["failures"])

    out = HERE / "runs" / run_name
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in predictions))
    (out / "system_prompt.txt").write_text(harness.system)
    (out / "report.md").write_text(report(run_name, config, metrics, predictions))
    log.info("wrote %s", out)

    if wb is not None:
        import wandb
        wb.summary.update(metrics)
        columns = ["message_id", "user_id", "thread_id", "position", "source_set", "act", "from_user",
                   "true_needs_response", "needs_response", "true_label", "label", "reason", "error"]
        wb.log({"predictions": wandb.Table(columns=columns, data=[[p.get(c) for c in columns] for p in predictions]),
                "label_confusion": wandb.Table(columns=["true", "predicted", "count"],
                                               data=[[t, p, n] for (t, p), n in sorted(confusion(predictions).items())])})
        report_artifact = wandb.Artifact(f"report-{harness.name}", type="report")
        report_artifact.add_file(str(out / "report.md"))
        wb.log_artifact(report_artifact)
        wb.finish()
    return 1 if metrics["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
