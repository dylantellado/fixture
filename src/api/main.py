"""Fixture API: search one user's indexed scheduling emails.

Endpoints (see "Data contract" in the README and src/api/README.md):
    GET  /health   is the API up?
    GET  /users    users that have an indexed message collection
    POST /search   semantic search over ONE user's messages

Run from src/api with:
    uv run uvicorn main:app --port 8000 --reload
"""

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from chroma_store import ChromaUnavailable, MessageStore, UnknownUser

# The six labels from the Data contract.
Label = Literal["new_request", "proposed_times", "acceptance", "reschedule", "assistant_handoff", "none"]

app = FastAPI(title="Fixture API")

# One shared store for the whole app. It connects to ChromaDB on the first
# request, not here, so the API starts even if ChromaDB isn't up yet.
store = MessageStore()


def get_store() -> MessageStore:
    """FastAPI injects this into each endpoint. Tests override it with
    app.dependency_overrides[get_store] to use a fake or in-memory ChromaDB."""
    return store


class SearchRequest(BaseModel):
    # user_id is checked in search() instead of here, so a malformed id gets
    # the same 400 "unknown user" as one with no collection.
    user_id: str
    query: str
    k: int = Field(default=5, ge=1, le=20)
    label: Label | None = None  # optional: only return messages with this label

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class SearchResult(BaseModel):
    text: str
    score: float
    metadata: dict


class SearchResponse(BaseModel):
    user_id: str
    query: str
    results: list[SearchResult]


class User(BaseModel):
    user_id: str
    name: str
    indexed_at: str


@app.get("/health")
def health() -> dict:
    """Report that the API is up. Doesn't check ChromaDB, so Docker's
    healthcheck passes even while the database is still starting."""
    return {"status": "ok"}


@app.get("/users")
def users(store: MessageStore = Depends(get_store)) -> list[User]:
    """List the users that have an indexed collection (for the app's user picker)."""
    try:
        return store.list_users()
    except ChromaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/search")
def search(request: SearchRequest, store: MessageStore = Depends(get_store)) -> SearchResponse:
    """Search one user's messages.

    user_id must come from the app (for example, the signed-in user or the
    picker), never from an LLM, because it decides whose mailbox is searched.
    """
    try:
        results = store.search(request.user_id, request.query, request.k, request.label)
    except UnknownUser:
        raise HTTPException(status_code=400, detail="unknown user")
    except ChromaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return SearchResponse(user_id=request.user_id, query=request.query, results=results)
