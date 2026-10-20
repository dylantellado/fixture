"""All of the API's ChromaDB access, in one small class.

main.py never talks to ChromaDB directly. It asks FastAPI for a MessageStore
(see get_store in main.py), so tests can swap in a fake client or an
in-memory ChromaDB without a server.

Privacy guarantee: every search opens exactly one collection, the one named
from the requested user_id (messages_<user_id>). There is no code path that
searches more than one collection, so one user's search can never return
another user's messages.
"""

import os
import re
import time

import chromadb
import httpx
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# Where ChromaDB runs. The defaults fit a laptop (the chromadb container's
# host port); docker-compose.yml sets CHROMA_HOST=chromadb, CHROMA_PORT=8000.
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

# Each user's messages live in their own collection, e.g. messages_user_01.
# Must match the rag service, which creates these collections.
COLLECTION_PREFIX = "messages_"

# user_id becomes part of a collection name, so only these characters are allowed
# (see "Rules the search side depends on" in the README's Data contract).
USER_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

# How hard to try reaching ChromaDB before giving up with a 503: a short
# retry, so a request never hangs for long when ChromaDB is down.
CONNECT_ATTEMPTS = 3
CONNECT_DELAY_SECONDS = 0.5


class ChromaUnavailable(Exception):
    """ChromaDB couldn't be reached. main.py turns this into a 503."""


class UnknownUser(Exception):
    """The user_id is malformed or has no collection. main.py turns this into a 400."""


def collection_name(user_id: str) -> str:
    """The one collection that holds this user's messages, e.g. messages_user_01."""
    return f"{COLLECTION_PREFIX}{user_id}"


def connect_to_server():
    """Open a client to the ChromaDB server and check that it answers."""
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    client.heartbeat()
    return client


class MessageStore:
    """Reads per-user message collections from ChromaDB.

    client_factory: makes a ChromaDB client (the real server by default;
        tests pass an in-memory client or a fake).
    embedding_function: turns the query into a vector. It must be the same
        one the rag service indexed with, chromadb's DefaultEmbeddingFunction
        (all-MiniLM-L6-v2), or query vectors won't match the stored ones.
    """

    def __init__(self, client_factory=connect_to_server, embedding_function=None,
                 attempts=CONNECT_ATTEMPTS, delay_seconds=CONNECT_DELAY_SECONDS):
        self.client_factory = client_factory
        self.embedding_function = embedding_function or DefaultEmbeddingFunction()
        self.attempts = attempts
        self.delay_seconds = delay_seconds
        self._client = None  # created on first use, not at startup

    def _get_client(self):
        """Return the ChromaDB client, connecting on first use (with a short retry).

        Connecting lazily means the API still starts, and /health still works,
        while ChromaDB is down.
        """
        if self._client is not None:
            return self._client
        for attempt in range(1, self.attempts + 1):
            try:
                self._client = self.client_factory()
                return self._client
            except Exception:  # chromadb raises ValueError, httpx errors, etc.
                if attempt < self.attempts:
                    time.sleep(self.delay_seconds)
        raise ChromaUnavailable(
            f"The search database (ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}) is not reachable. "
            "Check that the chromadb service is running, then try again."
        )

    def _lost_connection(self) -> ChromaUnavailable:
        """Forget a client whose connection broke, so the next request reconnects."""
        self._client = None
        return ChromaUnavailable(
            "Lost the connection to the search database (ChromaDB). Try again shortly."
        )

    def list_users(self) -> list[dict]:
        """Users that have a messages_* collection, read from collection metadata.

        This only reads each collection's name and metadata (set by rag),
        never any messages.
        """
        client = self._get_client()
        try:
            collections = client.list_collections()
        except httpx.TransportError:
            raise self._lost_connection()

        users = []
        for collection in collections:
            if not collection.name.startswith(COLLECTION_PREFIX):
                continue  # not one of ours
            user_id = collection.name[len(COLLECTION_PREFIX):]
            if not USER_ID_PATTERN.match(user_id):
                continue  # couldn't be searched anyway
            metadata = collection.metadata or {}
            users.append({
                "user_id": user_id,
                "name": metadata.get("user_name", ""),
                "indexed_at": metadata.get("indexed_at", ""),
            })
        return sorted(users, key=lambda u: u["user_id"])

    def search(self, user_id: str, query: str, k: int, label: str | None = None) -> list[dict]:
        """Return the k chunks in this user's collection closest to the query, best first.

        Each result is {"text", "score", "metadata"}, where score is
        1 - cosine distance rounded to 3 places (higher is closer).
        """
        if not USER_ID_PATTERN.match(user_id):
            raise UnknownUser(user_id)

        client = self._get_client()
        try:
            # PRIVACY: the only collection this request ever opens is the one
            # named from the requested user_id. Never loop over collections here.
            collection = client.get_collection(
                collection_name(user_id), embedding_function=self.embedding_function
            )
            found = collection.query(
                query_texts=[query],
                n_results=k,
                where={"label": label} if label else None,
                include=["documents", "metadatas", "distances"],
            )
        except NotFoundError:
            raise UnknownUser(user_id)
        except httpx.TransportError:
            raise self._lost_connection()

        # Chroma returns one list per query text; we sent one query, so take [0].
        results = [
            {"text": text, "score": round(1 - distance, 3), "metadata": metadata}
            for text, metadata, distance in zip(
                found["documents"][0], found["metadatas"][0], found["distances"][0]
            )
        ]
        # Chroma already returns closest first; sort anyway so "best first" never depends on it.
        return sorted(results, key=lambda r: r["score"], reverse=True)
