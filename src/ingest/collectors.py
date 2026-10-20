"""Collectors: where ingest gets email threads from.

Every collector hands back the same thing: the users, and the threads as
dicts in the source format from the Data contract (README), each paired
with a short note of where it came from. Ingest then validates,
deduplicates and writes them the same way no matter which collector was
used, so a new data source only needs a new collector.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path


class SourceMissingError(Exception):
    """A source file ingest needs doesn't exist."""


class Collector(ABC):
    # Recorded on every thread as "source", and copied by preprocess into
    # each message's "source" field.
    name: str

    @abstractmethod
    def users(self) -> list[dict]:
        """The users whose mail this collector returns (user_id, name, email)."""

    @abstractmethod
    def threads(self) -> Iterator[tuple[dict, dict]]:
        """Yield (thread, origin) pairs. `origin` says where the thread came from."""


class FileCollector(Collector):
    """Reads the generated corpus: users.json and generated_threads.jsonl."""

    name = "generated"

    def __init__(self, source_dir: Path):
        self.users_path = source_dir / "users.json"
        self.threads_path = source_dir / "generated_threads.jsonl"

    def check_files_exist(self) -> None:
        missing = [p for p in (self.users_path, self.threads_path) if not p.exists()]
        if missing:
            names = ", ".join(str(p) for p in missing)
            raise SourceMissingError(
                f"Missing source data: {names}. "
                "Run `dvc pull` from the repo root to download it, then try again."
            )

    def users(self) -> list[dict]:
        return json.loads(self.users_path.read_text())

    def threads(self) -> Iterator[tuple[dict, dict]]:
        with self.threads_path.open() as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue  # tolerate blank lines
                try:
                    thread = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{self.threads_path.name} line {line_number}: invalid JSON ({error})") from error
                yield thread, {"file": f"source/{self.threads_path.name}", "line": line_number}


class LLMCollector(Collector):
    """Placeholder: generate threads with an LLM API instead of reading a file.

    Not implemented. We have no LLM API key yet. When we do, this would prompt a
    model with the plans in docs/data/generation/ and yield threads in the
    same format as FileCollector, so the rest of ingest doesn't change.
    """

    name = "llm"

    def users(self) -> list[dict]:
        raise NotImplementedError("LLMCollector is a placeholder; use FileCollector")

    def threads(self) -> Iterator[tuple[dict, dict]]:
        raise NotImplementedError("LLMCollector is a placeholder; use FileCollector")
