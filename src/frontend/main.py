"""Fixture demo web app: sign in with Google, then see your calendar and inbox.

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

import google_data
from credential_store import CredentialStore

REPO_ROOT = Path(__file__).resolve().parents[2]  # this file lives in src/frontend/

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
        {"user": store.load_profile(request.session["email"]), "calendar": calendar, "inbox": inbox},
    )


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
