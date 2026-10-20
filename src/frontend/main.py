"""Fixture demo web app: sign in with Google, then see your calendar and inbox.
The /search page searches fake demo mailboxes through the Fixture API, and /about
explains the pipeline with live status. Neither needs sign-in.

Run from src/frontend with:
    uv run uvicorn main:app --port 8501 --reload
"""

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

import api_client
import google_data
from credential_store import CredentialStore

# This file lives in src/frontend/, so the repo root is three levels up.
# In Docker the file is /app/main.py and this resolves to "/" (parents[2]
# would crash there); that's fine because Docker sets every path and secret
# through environment variables instead.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Read settings from .env at the repo root. Docker passes them in directly instead.
load_dotenv(REPO_ROOT / ".env")


def require_env(name: str, how_to_generate: str) -> str:
    """Return a required setting, or stop with a message saying how to create it."""
    value = os.environ.get(name)
    if not value:
        sys.exit(
            f"Missing {name}. Add it to .env at the repo root (see .env.example).\n"
            f"Generate one from src/frontend with:\n  {how_to_generate}"
        )
    return value


SESSION_SECRET = require_env(
    "SESSION_SECRET", 'uv run python -c "import secrets; print(secrets.token_urlsafe(32))"'
)
TOKEN_ENCRYPTION_KEY = require_env(
    "TOKEN_ENCRYPTION_KEY",
    'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
)

# The Google OAuth library refuses plain http by default. That's right for
# production, but this demo only runs on http://localhost.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Google adds "openid" and reorders scopes in its reply; don't treat that as an error.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Everything the web app asks permission for. All read-only.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# secrets/ and data/ at the repo root. Docker overrides both.
SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", REPO_ROOT / "secrets"))
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
CLIENT_FILE = SECRETS_DIR / "web_credentials.json"  # "Fixture Web" OAuth client
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8501/auth/callback")

APP_DIR = Path(__file__).resolve().parent

# Short codes passed in the URL as ?error=..., shown on the sign-in page.
ERRORS = {
    "cancelled": "Sign-in was cancelled.",
    "expired": "Your sign-in expired. Please try again.",
    "scopes": "Fixture needs both Calendar and Gmail access. Please allow both.",
}

# Friendly messages for the search page. Never show a stack trace.
SEARCH_ERRORS = {
    "api_down": "Search isn't available right now: the Fixture API or its database can't be reached. "
                "Check that the api and chromadb services are running, then try again.",
    "no_users": "No demo mailboxes have been indexed yet. Run the rag job to index the sample emails, "
                "then reload this page.",
    "unknown_user": "That demo user isn't indexed. Pick someone from the list.",
    "api_error": "Something went wrong running that search. Please try a different query.",
}

# Clickable example questions on the search page, per demo mailbox. They come
# from the retrieval demo in docs/data/corpus_notes.md (data-v1). Mailboxes not
# listed here get the general ones.
EXAMPLE_QUESTIONS = {
    "user_01": ["When and where do I meet my career advisor?", "How does Rohan like to meet?",
                "When is my Larkmoor superday?"],
    "user_02": ["When does Professor Osei meet?", "Who schedules meetings with Tom Haskell?",
                "When was my Larkmoor first round moved to?"],
    "user_03": ["Where does Hannah Cho like to meet?", "When is the TA meeting when Prof. Vasquez travels?",
                "When is my Brightwater final round?"],
    "user_04": ["What time is my Oct 26 advising in London time?", "How does Rohan like to meet?",
                "When and where do I meet my career advisor?"],
}
GENERAL_QUESTIONS = ["Who wants to reschedule?", "Which meetings are confirmed?", "Who handed scheduling to an assistant?"]

# How many results the search page can ask for (the API allows 1 to 20).
RESULT_COUNTS = (5, 10, 20)

# Signed-in users' Google credentials, encrypted in data/fixture.db.
try:
    store = CredentialStore(DATA_DIR / "fixture.db", TOKEN_ENCRYPTION_KEY)
except ValueError:
    sys.exit("TOKEN_ENCRYPTION_KEY is not a valid key. Generate a new one (see .env.example).")

app = FastAPI(title="Fixture")
# The signed browser cookie holds only the user's email; Google tokens stay in the database.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def make_flow(**kwargs) -> Flow:
    return Flow.from_client_secrets_file(
        str(CLIENT_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI, **kwargs
    )


def current_credentials(request: Request) -> Credentials | None:
    """Return the signed-in user's Google credentials, or None if signed out.

    Expired access tokens are refreshed and the new version saved back.
    """
    email = request.session.get("email")
    creds = store.load(email) if email else None
    if creds is None:
        return None

    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError:
            # Access was revoked or the login expired (Testing mode: ~7 days).
            store.delete(email)
            return None
        store.save(email, creds)

    return creds if creds.valid else None


def nav_context(request: Request, active: str) -> dict:
    """What the shared top bar (_nav.html) needs: which page is open, and the
    signed-in user's saved profile (None if signed out). Reads only our own
    database, never Google, so it's fast and works when Google logins expire."""
    email = request.session.get("email")
    return {"active": active, "nav_user": store.load_profile(email) if email else None}


@app.get("/")
def home(request: Request):
    creds = current_credentials(request)
    if not creds:
        error = ERRORS.get(request.query_params.get("error", ""))
        return templates.TemplateResponse(request, "login.html", {"error": error})

    # Load each service separately so one failing doesn't hide the other.
    calendar = {"items": [], "calendars": [], "skipped": [], "error": None}
    inbox = {"items": [], "error": None}
    try:
        calendar.update(google_data.fetch_events(creds))
    except HttpError as e:
        calendar["error"] = e.reason
    try:
        inbox["items"] = google_data.fetch_emails(creds)
    except HttpError as e:
        inbox["error"] = e.reason

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            **nav_context(request, "dashboard"),
            "user": store.load_profile(request.session["email"]),
            "calendar": calendar,
            "inbox": inbox,
        },
    )


@app.get("/search")
def search_page(request: Request, user_id: str = "", q: str = "", label: str = "", k: str = "5"):
    """Search past threads in the fake demo mailboxes.

    This page never uses the signed-in Google account, so it works without
    signing in (Testing-mode logins expire). The API is called server-side.
    """
    page = {
        "users": [],
        "user_id": user_id,
        "query": q.strip(),
        "label": label if label in api_client.LABELS else "",  # ignore unknown labels
        "labels": api_client.LABELS,
        # Only the counts we offer; anything else (or a typo in the URL) means 5.
        "k": int(k) if k in {str(n) for n in RESULT_COUNTS} else RESULT_COUNTS[0],
        "result_counts": RESULT_COUNTS,
        "results": None,  # None = no search yet; [] = searched, nothing found
        "error": None,
        "selected_user": None,  # the picked mailbox, if it's indexed
        "examples": [],
        **nav_context(request, "search"),
    }

    # 1. Fill the user picker from GET /users.
    try:
        page["users"] = [api_client.format_user(u) for u in api_client.list_users()]
    except api_client.ApiUnavailable:
        page["error"] = SEARCH_ERRORS["api_down"]
    except api_client.ApiError:
        page["error"] = SEARCH_ERRORS["api_error"]
    else:
        if not page["users"]:
            page["error"] = SEARCH_ERRORS["no_users"]
        elif not page["user_id"]:
            page["user_id"] = page["users"][0]["user_id"]  # default to the first user
        page["selected_user"] = next((u for u in page["users"] if u["user_id"] == page["user_id"]), None)
        if page["selected_user"]:
            page["examples"] = EXAMPLE_QUESTIONS.get(page["user_id"], GENERAL_QUESTIONS)

    # 2. Search, if there's a query. The API checks that user_id is known.
    if page["query"] and page["users"]:
        try:
            results = api_client.search(page["user_id"], page["query"], k=page["k"], label=page["label"] or None)
            page["results"] = [api_client.format_result(r) for r in results]
        except api_client.UnknownUser:
            page["error"] = SEARCH_ERRORS["unknown_user"]
        except api_client.ApiUnavailable:
            page["error"] = SEARCH_ERRORS["api_down"]
        except api_client.ApiError:
            page["error"] = SEARCH_ERRORS["api_error"]

    return templates.TemplateResponse(request, "search.html", page)


@app.get("/about")
def about_page(request: Request):
    """How Fixture works, with the live status of the API and the indexed mailboxes."""
    status = {"api_ok": api_client.is_healthy(), "users": [], "error": None}
    if status["api_ok"]:
        try:
            status["users"] = [api_client.format_user(u) for u in api_client.list_users()]
        except (api_client.ApiUnavailable, api_client.ApiError):
            # /health answers without ChromaDB; /users needs it.
            status["error"] = "The API is up, but its search database (ChromaDB) can't be reached."
    return templates.TemplateResponse(request, "about.html", {**nav_context(request, "about"), "status": status})


@app.get("/auth/login")
def login(request: Request):
    """Send the browser to Google's sign-in page."""
    flow = make_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    # Remember these to verify Google's reply in the callback.
    request.session["state"] = state
    request.session["code_verifier"] = flow.code_verifier
    return RedirectResponse(url)


@app.get("/auth/callback")
def callback(request: Request):
    """Google sends the browser back here after sign-in."""
    if request.query_params.get("error"):
        return RedirectResponse("/?error=cancelled")
    state = request.session.get("state")
    if not state or request.query_params.get("state") != state:
        return RedirectResponse("/?error=expired")

    flow = make_flow(state=state, code_verifier=request.session["code_verifier"])
    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials

    # Make sure the user ticked every permission box on Google's consent screen.
    if not creds.has_scopes(SCOPES):
        return RedirectResponse("/?error=scopes")

    profile = google_data.fetch_profile(creds)
    store.save(profile["email"], creds, name=profile["name"], picture=profile["picture"])
    request.session.clear()
    request.session["email"] = profile["email"]
    return RedirectResponse("/")


@app.get("/auth/logout")
def logout(request: Request):
    """Sign out and delete this user's stored credentials (in every browser)."""
    email = request.session.get("email")
    if email:
        store.delete(email)
    request.session.clear()
    return RedirectResponse("/")
