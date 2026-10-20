"""Check retrieval against the example queries in docs/data/corpus_notes.md.

For each query (listed in retrieval_cases.json), it searches that user's
collection and checks two things:
  1. Quality: are the messages that answer the question in the top k results?
  2. Isolation: does every result belong to that user? This must always be
     true; the script exits non-zero if it ever isn't.

Examples (from src/rag, with ChromaDB running and the rag job already run on data-v1):
  uv run python check_retrieval.py
  uv run python check_retrieval.py --markdown > ../../docs/evidence/retrieval_check.md
"""

import argparse
import json
import sys
from pathlib import Path

from chromadb.errors import NotFoundError

import config
from index import collection_name, connect, search

CASES_PATH = Path(__file__).resolve().parent / "retrieval_cases.json"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """The example queries: name, user_id, query, answer, expected message_ids."""
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def check_case(case: dict, results: list[dict]) -> dict:
    """Compare one query's search results with the messages that answer it."""
    result_ids = [r["metadata"]["message_id"] for r in results]
    # Rank (1 = top) of each expected message, or None if it isn't in the results.
    ranks = {mid: result_ids.index(mid) + 1 if mid in result_ids else None for mid in case["expected"]}
    found = sum(rank is not None for rank in ranks.values())
    return {
        **case,
        "ranks": ranks,
        "found": found,
        "status": "all" if found == len(ranks) else ("some" if found else "none"),
        "other_user_results": sum(r["metadata"]["user_id"] != case["user_id"] for r in results),
    }


def summarize(checked: list[dict]) -> dict:
    """Counts across all queries."""
    return {
        "queries": len(checked),
        "all_found": sum(c["status"] == "all" for c in checked),
        "some_found": sum(c["status"] == "some" for c in checked),
        "none_found": sum(c["status"] == "none" for c in checked),
        "other_user_results": sum(c["other_user_results"] for c in checked),
    }


def format_ranks(ranks: dict) -> str:
    """'2, 4' or '6+' style: where each expected message ranked."""
    return ", ".join(str(r) if r else "–" for r in ranks.values())


def format_markdown(checked: list[dict], summary: dict, k: int, collection_metadata: dict) -> str:
    """Markdown for an evidence file: data version, summary, one row per query."""
    lines = [
        "# Retrieval check",
        "",
        "Will's example queries (`docs/data/corpus_notes.md`), each searched in that user's own collection.",
        "",
        f"- **Command:** `uv run python check_retrieval.py --k {k} --markdown` (from `src/rag`)",
        f"- **Embedding model:** {collection_metadata.get('embedding_model', '')}, cosine distance",
        f"- **Indexed from:** sha256 `{collection_metadata.get('input_sha256', '')}`, "
        f"at {collection_metadata.get('indexed_at', '')}",
        "",
        "## Summary",
        "",
        f"- **Isolation:** {summary['other_user_results']} results from another user's mailbox "
        f"across {summary['queries']} queries (must be 0).",
        f"- **All answering messages in the top {k}:** {summary['all_found']} of {summary['queries']} queries.",
        f"- **Some of them:** {summary['some_found']}. **None of them:** {summary['none_found']}.",
        "",
        "A miss usually means search found the right thread but ranked a short reply "
        "(for example \"I'd like Friday at 9\") lower, because one chunk is one message.",
        "",
        "## Queries",
        "",
        f"| # | User | Query | Expected answer | Found | Rank(s) in top {k} | Other users' results |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in checked:
        lines.append(
            f"| {c['name']} | `{c['user_id']}` | {c['query']} | {c['answer']} | "
            f"{c['found']}/{len(c['ranks'])} | {format_ranks(c['ranks'])} | {c['other_user_results']} |"
        )
    lines += ["", "Rank `–` means that message wasn't in the top results."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check retrieval against the example queries.")
    parser.add_argument("--k", type=int, default=5, help="results per query (default 5)")
    parser.add_argument("--markdown", action="store_true", help="print Markdown for an evidence file")
    args = parser.parse_args(argv)

    try:
        client = connect(attempts=1)
    except ConnectionError as e:
        sys.exit(f"{e}\nIs ChromaDB running? From the repo root: docker compose up -d chromadb")

    checked, collection_metadata = [], {}
    for case in load_cases():
        try:
            # One collection per query: only the user the query belongs to.
            collection = client.get_collection(
                collection_name(case["user_id"]), embedding_function=config.get_embedding_function()
            )
        except NotFoundError:
            sys.exit(f"No collection for {case['user_id']}. Run the rag job on data-v1 first (uv run main.py).")
        collection_metadata = collection.metadata or {}
        checked.append(check_case(case, search(collection, case["query"], k=args.k)))

    summary = summarize(checked)
    if args.markdown:
        print(format_markdown(checked, summary, args.k, collection_metadata), end="")
    else:
        for c in checked:
            print(f"{c['name']:>3} {c['user_id']}  {c['status']:<4} {c['found']}/{len(c['ranks'])}  "
                  f"ranks {format_ranks(c['ranks'])}  other users {c['other_user_results']}")
        print(f"\nAll found: {summary['all_found']}/{summary['queries']}, some: {summary['some_found']}, "
              f"none: {summary['none_found']}, other users' results: {summary['other_user_results']}")

    # A result from another user's mailbox is a privacy failure, not a quality miss.
    if summary["other_user_results"]:
        sys.exit("FAILED: a search returned another user's messages.")


if __name__ == "__main__":
    main()
