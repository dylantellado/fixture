"""Search one user's indexed messages from the command line.

Examples (from src/rag, with ChromaDB running and the rag job already run):
  uv run python query.py --user user_01 "When is my interview?" --k 5
  uv run python query.py --user user_02 "Who wants to reschedule?" --label reschedule
  uv run python query.py --user user_01 "When is my interview?" --markdown > ../../docs/evidence/retrieval_example.md
"""

import argparse
import sys

from chromadb.errors import NotFoundError

import config
from index import collection_name, connect, search
from inputs import ALLOWED_LABELS, check_user_id


def format_plain(results: list[dict]) -> str:
    """Readable terminal output, one block per result."""
    if not results:
        return "No results."
    blocks = []
    for rank, r in enumerate(results, start=1):
        m = r["metadata"]
        blocks.append(
            f"#{rank}  score {r['score']:.3f}  [{m['label']}]  {m['sender']}  {m['timestamp']}\n"
            f"    Subject: {m['subject']}\n"
            f"    id: {r['id']}  thread: {m['thread_id']}\n"
            + "\n".join(f"    | {line}" for line in r["text"].splitlines())
        )
    return "\n\n".join(blocks)


def format_markdown(query: str, user_id: str, collection_metadata: dict, results: list[dict], k: int, label: str | None) -> str:
    """Markdown for evidence files: the query, the user, the data, each result."""
    command = f'uv run python query.py --user {user_id} "{query}" --k {k}'
    if label:
        command += f" --label {label}"
    command += " --markdown"

    lines = [
        "# Retrieval example",
        "",
        f"- **Query:** {query}",
        f"- **User:** `{user_id}` ({collection_metadata.get('user_name', '')})",
        f"- **Collection:** `{collection_name(user_id)}`",
        f"- **Label filter:** {f'`{label}`' if label else 'none'}",
        f"- **Embedding model:** {collection_metadata.get('embedding_model', '')}, cosine distance",
        f"- **Indexed from:** `{collection_metadata.get('input_path', '')}` "
        f"(sha256 `{collection_metadata.get('input_sha256', '')}`)",
        f"- **Indexed at:** {collection_metadata.get('indexed_at', '')}",
        f"- **Command:** `{command}` (from `src/rag`)",
        "",
        "Score = 1 - cosine distance (higher is closer).",
        "",
    ]
    if collection_metadata.get("used_sample_data"):
        lines += ["> Built from the committed sample data (`samples/`), not generated pipeline data.", ""]

    if not results:
        lines.append("No results.")
    for rank, r in enumerate(results, start=1):
        m = r["metadata"]
        lines += [
            f"## {rank}. {m['subject']} (score {r['score']:.3f})",
            "",
            "| Sender | Date | Label | Message id | Chunk |",
            "|---|---|---|---|---|",
            # Backticks so GitHub shows "<EMAIL_003>" instead of hiding it as an HTML tag.
            f"| `{m['sender']}` | {m['timestamp']} | `{m['label']}` | `{m['message_id']}` | {m['chunk_index']} |",
            "",
            "```text",
            r["text"],
            "```",
            "",
        ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search one user's indexed messages.")
    parser.add_argument("query", help="the question to search for")
    parser.add_argument("--user", required=True, help="whose messages to search, e.g. user_01")
    parser.add_argument("--k", type=int, default=5, help="number of results (default 5)")
    parser.add_argument("--label", choices=sorted(ALLOWED_LABELS), help="only search messages with this label")
    parser.add_argument("--markdown", action="store_true", help="print Markdown for an evidence file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    problem = check_user_id(args.user)
    if problem:
        sys.exit(f"Invalid --user: {problem}")
    if args.k < 1:
        sys.exit("--k must be at least 1")

    try:
        client = connect(attempts=1)
    except ConnectionError as e:
        sys.exit(f"{e}\nIs ChromaDB running? From the repo root: docker compose up -d chromadb")
    name = collection_name(args.user)
    try:
        # Must be the same embedding function the rag job indexed with.
        collection = client.get_collection(name, embedding_function=config.get_embedding_function())
    except NotFoundError:
        known = sorted(
            c.name.removeprefix(config.COLLECTION_PREFIX)
            for c in client.list_collections()
            if c.name.startswith(config.COLLECTION_PREFIX)
        )
        sys.exit(
            f"No collection {name} for user {args.user!r}. Run the rag job first "
            f"(uv run main.py). Users with collections: {', '.join(known) or 'none'}"
        )

    results = search(collection, args.query, k=args.k, label=args.label)
    if args.markdown:
        print(format_markdown(args.query, args.user, collection.metadata or {}, results, args.k, args.label))
    else:
        print(f"Top {len(results)} results for {args.user} ({(collection.metadata or {}).get('user_name', '')}): {args.query!r}\n")
        print(format_plain(results))


if __name__ == "__main__":
    main()
