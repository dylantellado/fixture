"""Fixture API. For now it only answers GET /health, so Docker can check that
it started. POST /search (see "Data contract" in the README) comes next.

Run from src/api with:
    uv run uvicorn main:app --port 8000 --reload
"""

from fastapi import FastAPI

app = FastAPI(title="Fixture API")


@app.get("/health")
def health() -> dict:
    """Report that the API is up."""
    return {"status": "ok"}
