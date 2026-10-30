"""Cache of Gemini labels for the user's real emails, in data/fixture.db.

One row per (account, Gmail message id). The account is a sha256 of the
signed-in email address, not the address itself. A row stores only the
classifier's answer and when it was made: never the email's text, subject or
sender. A cached row counts only if it was made with the current labeling
rules version; when the rules change, the email is classified again and the
row replaced. Signing out deletes that account's rows.

Usage:
    cache = ClassificationCache(Path("data/fixture.db"))
    cache.save("me@example.com", "18c2...", {"label": ..., "needs_response": ..., "reason": ...,
                                             "model": ..., "rules_version": "1.2"})
    cache.load_many("me@example.com", ["18c2...", "18c3..."], rules_version="1.2")  # {id: row}
    cache.delete_account("me@example.com")
"""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Returned for each cached row (the account hash stays inside this module).
FIELDS = ("message_id", "label", "needs_response", "reason", "model", "rules_version", "classified_at")


def account_key(email: str) -> str:
    """The stored account id: sha256 of the lowercased email address."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class ClassificationCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            # An early version of this table had no account column. It's only a
            # cache, so drop it and let emails be classified again.
            columns = [row[1] for row in db.execute("PRAGMA table_info(classifications)")]
            if columns and "account" not in columns:
                db.execute("DROP TABLE classifications")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS classifications (
                    account        TEXT NOT NULL,     -- account_key(signed-in email)
                    message_id     TEXT NOT NULL,     -- Gmail message id
                    label          TEXT NOT NULL,
                    needs_response INTEGER NOT NULL,  -- 0 or 1
                    reason         TEXT NOT NULL,     -- Gemini's one-line reason
                    model          TEXT NOT NULL,
                    rules_version  TEXT NOT NULL,
                    classified_at  TEXT NOT NULL,     -- UTC ISO time
                    PRIMARY KEY (account, message_id)
                )
                """
            )

    @contextmanager
    def _connect(self):
        """A fresh connection per call, so it's safe to use from several threads."""
        db = sqlite3.connect(self.db_path)
        try:
            with db:  # commits on success, rolls back on error
                yield db
        finally:
            db.close()

    def save(self, email: str, message_id: str, result: dict) -> None:
        """Insert or replace the label for one of this account's messages."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO classifications VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (account_key(email), message_id, result["label"], int(bool(result["needs_response"])),
                 result["reason"], result["model"], result["rules_version"], now),
            )

    def load_many(self, email: str, message_ids: list[str], rules_version: str) -> dict[str, dict]:
        """This account's cached labels for these ids, made with this rules version. Others are left out."""
        if not message_ids:
            return {}
        marks = ",".join("?" * len(message_ids))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT {', '.join(FIELDS)} FROM classifications "
                f"WHERE account = ? AND rules_version = ? AND message_id IN ({marks})",
                (account_key(email), rules_version, *message_ids),
            ).fetchall()
        results = {}
        for row in rows:
            result = dict(zip(FIELDS, row))
            result["needs_response"] = bool(result["needs_response"])
            results[result["message_id"]] = result
        return results

    def delete_account(self, email: str) -> None:
        """Remove every cached label for this account (does nothing if there are none)."""
        with self._connect() as db:
            db.execute("DELETE FROM classifications WHERE account = ?", (account_key(email),))
