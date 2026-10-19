"""Encrypted storage for users' Google credentials, in a small SQLite file.

Each signed-in user gets one row, keyed by their Google email address.
The credentials (access token, refresh token, and so on) are encrypted
before they're written, because anyone holding them can read that
person's email and calendar.

This file has no web-specific code, so a future background process can
create its own CredentialStore with the same database path and key and
act on a user's behalf.

Usage:
    store = CredentialStore(Path("data/fixture.db"), key)
    store.save("user@example.com", creds, name="User", picture=None)
    creds = store.load("user@example.com")   # None if not found
    store.delete("user@example.com")
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from google.oauth2.credentials import Credentials


class CredentialStore:
    def __init__(self, db_path: Path, key: str | bytes):
        """db_path: SQLite file (created if missing).
        key: a Fernet key, from Fernet.generate_key(). Raises ValueError if malformed.
        """
        self.db_path = Path(db_path)
        self.fernet = Fernet(key)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email       TEXT PRIMARY KEY,
                    credentials BLOB NOT NULL,  -- encrypted JSON from Credentials.to_json()
                    name        TEXT,           -- display name, not secret
                    picture     TEXT,           -- profile photo URL, not secret
                    updated_at  TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self):
        """Open the database, commit if the block succeeds, and always close it.

        A fresh connection per call keeps this safe to use from multiple threads.
        """
        db = sqlite3.connect(self.db_path)
        try:
            with db:  # commits on success, rolls back on error
                yield db
        finally:
            db.close()

    def save(self, email: str, creds: Credentials, name: str | None = None, picture: str | None = None) -> None:
        """Insert or update a user's credentials.

        name and picture are only overwritten when given, so saving refreshed
        credentials (without a profile) keeps the existing name and photo.
        """
        encrypted = self.fernet.encrypt(creds.to_json().encode())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO users (email, credentials, name, picture, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    credentials = excluded.credentials,
                    name        = COALESCE(excluded.name, users.name),
                    picture     = COALESCE(excluded.picture, users.picture),
                    updated_at  = excluded.updated_at
                """,
                (email, encrypted, name, picture, now),
            )

    def load(self, email: str) -> Credentials | None:
        """Return a user's credentials, or None if missing or unreadable.

        "Unreadable" means the encryption key changed or the data is corrupt;
        the user just has to sign in again.
        """
        with self._connect() as db:
            row = db.execute("SELECT credentials FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            return None
        try:
            info = json.loads(self.fernet.decrypt(row[0]))
            return Credentials.from_authorized_user_info(info)
        except (InvalidToken, ValueError):
            return None

    def load_profile(self, email: str) -> dict | None:
        """Return {"email", "name", "picture"} for a stored user, or None."""
        with self._connect() as db:
            row = db.execute("SELECT name, picture FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            return None
        return {"email": email, "name": row[0] or email, "picture": row[1]}

    def delete(self, email: str) -> None:
        """Remove a user's stored credentials (does nothing if not found)."""
        with self._connect() as db:
            db.execute("DELETE FROM users WHERE email = ?", (email,))
