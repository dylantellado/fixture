"""Everything that talks to ChromaDB: connect, rebuild collections, search."""

import copy
import logging
import time

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError

import config

log = logging.getLogger(__name__)


def collection_name(user_id: str) -> str:
    """The collection that holds one user's messages, e.g. messages_user_01."""
    return f"{config.COLLECTION_PREFIX}{user_id}"


def connect(
    host: str = config.CHROMA_HOST,
    port: int = config.CHROMA_PORT,
    attempts: int = config.CONNECT_ATTEMPTS,
    delay: float = config.CONNECT_DELAY_SECONDS,
):
    """Connect to the ChromaDB server, retrying briefly while it starts up."""
    for attempt in range(1, attempts + 1):
        try:
            client = chromadb.HttpClient(
                host=host, port=port, settings=Settings(anonymized_telemetry=False)
            )
            client.heartbeat()  # fails if the server isn't answering yet
            log.info("Connected to ChromaDB at %s:%s", host, port)
            return client
        except Exception as e:
            if attempt == attempts:
                raise ConnectionError(
                    f"Could not reach ChromaDB at {host}:{port} after {attempts} tries: {e}"
                )
            log.info("ChromaDB not ready at %s:%s (try %d/%d), retrying...", host, port, attempt, attempts)
            time.sleep(delay)


def rebuild_index(
    client,
    embedding_function,
    users: list[dict],
    chunks_by_user: dict[str, list[dict]],
    shared_metadata: dict,
) -> dict[str, int]:
    """Rebuild every user's collection from scratch.

    For each user in users.json: delete their collection if it exists, create
    it again, and upsert their chunks in batches. Then delete any messages_*
    collection whose user is no longer in users.json. Rebuilding (instead of
    updating in place) means removed or renamed messages never linger.

    shared_metadata is stored on every collection (input file, sha256, ...).
    Returns {collection name: number of chunks stored}.
    """
    sizes = {}
    for user in users:
        user_id = user["user_id"]
        name = collection_name(user_id)

        try:
            client.delete_collection(name)
        except NotFoundError:
            pass  # first run for this user

        collection = client.create_collection(
            name=name,
            # A fresh copy each time: Chroma writes the embedding function into
            # the dict it is given, which would leak into the next collection.
            configuration=copy.deepcopy(config.COLLECTION_CONFIGURATION),
            metadata={**shared_metadata, "user_id": user_id, "user_name": user["name"]},
            embedding_function=embedding_function,
        )

        chunks = chunks_by_user.get(user_id, [])
        for start in range(0, len(chunks), config.BATCH_SIZE):
            batch = chunks[start : start + config.BATCH_SIZE]
            collection.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )
        sizes[name] = collection.count()

    # Remove collections for users who are no longer in the data.
    # Only messages_* collections are touched; anything else is left alone.
    for existing in client.list_collections():
        if existing.name.startswith(config.COLLECTION_PREFIX) and existing.name not in sizes:
            client.delete_collection(existing.name)
            log.info("Deleted stale collection %s (user no longer in users.json)", existing.name)

    return sizes


def search(collection, query: str, k: int = 5, label: str | None = None) -> list[dict]:
    """Return the k chunks closest to the query, best first.

    Each result is {"id", "text", "score", "metadata"}, where
    score = 1 - cosine distance (1.0 means same direction, higher is closer).
    If label is given, only chunks with that label are searched.
    """
    response = collection.query(
        query_texts=[query],
        n_results=k,
        where={"label": label} if label else None,
        include=["documents", "metadatas", "distances"],
    )
    # Chroma returns one list per query text; we sent one query, so take [0].
    return [
        {"id": chunk_id, "text": text, "score": 1 - distance, "metadata": metadata}
        for chunk_id, text, metadata, distance in zip(
            response["ids"][0],
            response["documents"][0],
            response["metadatas"][0],
            response["distances"][0],
        )
    ]
