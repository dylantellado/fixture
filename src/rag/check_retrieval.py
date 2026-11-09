"""Score retrieval on the example queries in retrieval_cases.json.

Each case is a question a student might ask, the user whose mailbox it is
about, and the message_ids that answer it (checked by reading the data).
For each case the script searches that user's collection only and measures:

  - recall@k:  share of the expected messages that appear in the top k
               (summed over all cases of a split, so every expected message
               counts once)
  - MRR:       mean over cases of 1 / rank of the first expected message in
               the top k (0 when none is there)
  - full / partial / miss: all, some or none of a case's expected messages
               are in the top k
  - cross-user results: results that belong to another user. This is a
               privacy failure, must always be 0, and makes the script exit
               non-zero.

Splits: every case is "dev" or "test". The test cases were drawn at random
with a fixed seed (assign_splits, seed in retrieval_cases.json) before any
experiment ran. Build and tune on dev only. Test results are reported, never
tuned on: the console shows per-query lines for dev cases only, and test
appears only as a summary (and in the --markdown evidence file).

Examples (from src/rag, with ChromaDB running and the rag job already run on data-v1):
  uv run python check_retrieval.py                       # dev, per query
  uv run python check_retrieval.py --split all --record "Vertex + thread context"
  uv run python check_retrieval.py --split all --markdown > ../../docs/evidence/retrieval_check.md
"""

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from chromadb.errors import NotFoundError

import config
from index import collection_name, connect, search

CASES_PATH = Path(__file__).resolve().parent / "retrieval_cases.json"
EXPERIMENTS_PATH = config.REPO_ROOT / "docs" / "evidence" / "rag_experiments.md"
SPLITS = ("dev", "test")


# --- Cases and splits ----------------------------------------------------------


def load_case_file(path: Path = CASES_PATH) -> dict:
    """The whole cases file: the split seed and size, plus the cases."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """The cases: name, user_id, query, answer, expected message_ids, split, ..."""
    return load_case_file(path)["cases"]


def assign_splits(names: list[str], seed: int, test_size: int) -> dict[str, str]:
    """Pick test_size case names at random (fixed seed) for "test"; the rest are "dev".

    Sorting first makes the draw depend only on the names and the seed, not on
    the order of the cases in the file. The committed splits must equal this
    (a test checks it), so nobody can quietly move a case between splits.
    """
    test = set(random.Random(seed).sample(sorted(names), test_size))
    return {name: ("test" if name in test else "dev") for name in names}


def cases_for_split(cases: list[dict], split: str) -> list[dict]:
    """The cases in one split, or all of them for split="all"."""
    return [c for c in cases if split == "all" or c["split"] == split]


# --- Scoring -----------------------------------------------------------------------


def check_case(case: dict, results: list[dict]) -> dict:
    """Compare one query's search results (best first) with the messages that answer it."""
    result_ids = [r["metadata"]["message_id"] for r in results]
    # Rank (1 = top) of each expected message, or None if it isn't in the results.
    ranks = {mid: result_ids.index(mid) + 1 if mid in result_ids else None for mid in case["expected"]}
    found = sum(rank is not None for rank in ranks.values())
    found_ranks = [rank for rank in ranks.values() if rank is not None]
    return {
        **case,
        "ranks": ranks,
        "found": found,
        "reciprocal_rank": 1 / min(found_ranks) if found_ranks else 0.0,
        "status": "full" if found == len(ranks) else ("partial" if found else "miss"),
        "other_user_results": sum(r["metadata"]["user_id"] != case["user_id"] for r in results),
    }


def summarize(checked: list[dict]) -> dict:
    """Metrics across a list of checked cases (one split)."""
    expected = sum(len(c["ranks"]) for c in checked)
    return {
        "queries": len(checked),
        "recall": sum(c["found"] for c in checked) / expected if expected else 0.0,
        "mrr": sum(c["reciprocal_rank"] for c in checked) / len(checked) if checked else 0.0,
        "full": sum(c["status"] == "full" for c in checked),
        "partial": sum(c["status"] == "partial" for c in checked),
        "miss": sum(c["status"] == "miss" for c in checked),
        "other_user_results": sum(c["other_user_results"] for c in checked),
    }


def format_ranks(ranks: dict) -> str:
    """'2, –' style: where each expected message ranked (– = not in the top k)."""
    return ", ".join(str(r) if r else "–" for r in ranks.values())


def summary_line(split: str, summary: dict, k: int) -> str:
    return (
        f"{split:<5} {summary['queries']:>2} queries  recall@{k} {summary['recall']:.3f}  "
        f"MRR {summary['mrr']:.3f}  full {summary['full']}  partial {summary['partial']}  "
        f"miss {summary['miss']}  cross-user {summary['other_user_results']}"
    )


# --- Index facts and the experiment log -----------------------------------------------


def index_stats(collections: list) -> dict:
    """Facts about the searched collections for the experiment log.

    chunks: total chunks in the users' collections.
    over_limit: chunks longer than the embedding model's token limit, as
        counted by rag (collection metadata), or "n/a" if rag didn't record it.
    """
    chunks = sum(c.count() for c in collections)
    over = [(c.metadata or {}).get("chunks_over_token_limit") for c in collections]
    models = sorted({(c.metadata or {}).get("embedding_model", "") for c in collections})
    return {
        "chunks": chunks,
        "over_limit": sum(over) if over and all(isinstance(o, int) for o in over) else "n/a",
        "embedding_model": ", ".join(models),
    }


def git_commit() -> str:
    """Short commit of the code that ran, with "-dirty" if src/rag or src/api has uncommitted changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, cwd=config.REPO_ROOT
        ).stdout.strip()
        changed = subprocess.run(
            ["git", "status", "--porcelain", "--", "src/rag", "src/api"],
            capture_output=True, text=True, check=True, cwd=config.REPO_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit}-dirty" if changed else commit


EXPERIMENTS_HEADER = """# RAG experiments

One row per scored run of `check_retrieval.py --record`, appended automatically.
Rows are never edited or removed: they are the history of what each setup scored.
Splits: `dev` is used to build and tune; `test` is only reported (see
`src/rag/retrieval_cases.json` for the seed that drew it). Recall@5 is the share
of expected messages in the top 5; MRR uses the first expected message in the
top 5. "Over limit" counts chunks longer than the embedding model's token limit.

| Variant | Embedding model | Split | Queries | Recall@5 | MRR | Full | Partial | Miss | Cross-user | Chunks | Over limit | Commit | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def experiment_row(variant: str, split: str, summary: dict, stats: dict, commit: str, date: str) -> str:
    """One Markdown table row for the experiment log."""
    return (
        f"| {variant} | {stats['embedding_model']} | {split} | {summary['queries']} | "
        f"{summary['recall']:.3f} | {summary['mrr']:.3f} | {summary['full']} | {summary['partial']} | "
        f"{summary['miss']} | {summary['other_user_results']} | {stats['chunks']} | {stats['over_limit']} | "
        f"`{commit}` | {date} |"
    )


def append_experiment_rows(rows: list[str], path: Path = EXPERIMENTS_PATH) -> None:
    """Append rows to the experiment log, creating it with its header the first time."""
    if not path.exists():
        path.write_text(EXPERIMENTS_HEADER, encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(row + "\n")


# --- Evidence file ------------------------------------------------------------------


def format_markdown(checked: list[dict], summaries: dict[str, dict], k: int, collection_metadata: dict, stats: dict) -> str:
    """Markdown for an evidence file: data version, per-split summary, one row per query."""
    lines = [
        "# Retrieval check",
        "",
        f"{len(checked)} example queries, each searched in that user's own collection. "
        "The first 15 are Will's queries from `docs/data/corpus_notes.md`; the rest were added in "
        "Milestone 3 (`src/rag/retrieval_cases.json`). Each lists the messages that answer it.",
        "",
        f"- **Command:** `uv run python check_retrieval.py --split all --k {k} --markdown` (from `src/rag`)",
        f"- **Embedding model:** {collection_metadata.get('embedding_model', '')}, cosine distance",
        f"- **Chunks:** {stats['chunks']} in the searched users' collections, "
        f"{stats['over_limit']} over the model's token limit",
        f"- **Indexed from:** sha256 `{collection_metadata.get('input_sha256', '')}`, "
        f"at {collection_metadata.get('indexed_at', '')}",
        f"- **Code:** commit `{git_commit()}`",
        "",
        "## Summary",
        "",
        f"| Split | Queries | Recall@{k} | MRR | Full | Partial | Miss | Cross-user results |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for split, s in summaries.items():
        lines.append(
            f"| {split} | {s['queries']} | {s['recall']:.3f} | {s['mrr']:.3f} | {s['full']} | "
            f"{s['partial']} | {s['miss']} | {s['other_user_results']} |"
        )
    lines += [
        "",
        f"Cross-user results must be 0: a search never returns another user's messages. "
        f"`dev` cases were used to build the search; `test` cases were drawn at random before any "
        f"experiment and never tuned on.",
        "",
        "## Queries",
        "",
        f"| # | Split | User | Query | Expected answer | Found | Rank(s) in top {k} | Other users' results |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in checked:
        lines.append(
            f"| {c['name']} | {c['split']} | `{c['user_id']}` | {c['query']} | {c['answer']} | "
            f"{c['found']}/{len(c['ranks'])} | {format_ranks(c['ranks'])} | {c['other_user_results']} |"
        )
    lines += ["", "Rank `–` means that message wasn't in the top results."]
    return "\n".join(lines) + "\n"


# --- Running it ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score retrieval on the example queries.")
    parser.add_argument("--k", type=int, default=5, help="results per query (default 5)")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                        help="which cases to run (default dev; test is never shown per query on the console)")
    parser.add_argument("--record", metavar="VARIANT",
                        help="append one row per split to docs/evidence/rag_experiments.md")
    parser.add_argument("--markdown", action="store_true", help="print Markdown for an evidence file")
    args = parser.parse_args(argv)

    try:
        client = connect(attempts=1)
    except ConnectionError as e:
        sys.exit(f"{e}\nIs ChromaDB running? From the repo root: docker compose up -d chromadb")

    cases = cases_for_split(load_cases(), args.split)
    collections = {}
    for user_id in sorted({c["user_id"] for c in cases}):
        try:
            # One collection per user: a query only ever searches its own user's collection.
            collections[user_id] = client.get_collection(
                collection_name(user_id), embedding_function=config.get_embedding_function()
            )
        except NotFoundError:
            sys.exit(f"No collection for {user_id}. Run the rag job on data-v1 first (uv run main.py).")

    checked = [check_case(c, search(collections[c["user_id"]], c["query"], k=args.k)) for c in cases]
    splits = [s for s in SPLITS if any(c["split"] == s for c in checked)]
    summaries = {s: summarize([c for c in checked if c["split"] == s]) for s in splits}
    stats = index_stats(list(collections.values()))

    if args.markdown:
        any_metadata = next(iter(collections.values())).metadata or {}
        print(format_markdown(checked, summaries, args.k, any_metadata, stats), end="")
    else:
        for c in checked:
            if c["split"] == "dev":  # never show test cases one by one while building
                print(f"{c['name']:>4} {c['user_id']}  {c['status']:<7} {c['found']}/{len(c['ranks'])}  "
                      f"ranks {format_ranks(c['ranks'])}  other users {c['other_user_results']}")
        print()
        for split, summary in summaries.items():
            print(summary_line(split, summary, args.k))
        print(f"chunks {stats['chunks']}, over token limit {stats['over_limit']}, model {stats['embedding_model']}")

    if args.record:
        date = datetime.now(timezone.utc).date().isoformat()
        commit = git_commit()
        append_experiment_rows([experiment_row(args.record, s, summaries[s], stats, commit, date) for s in splits])
        print(f"Recorded {len(splits)} row(s) in {EXPERIMENTS_PATH}", file=sys.stderr)

    # A result from another user's mailbox is a privacy failure, not a quality miss.
    if any(s["other_user_results"] for s in summaries.values()):
        sys.exit("FAILED: a search returned another user's messages.")


if __name__ == "__main__":
    main()
