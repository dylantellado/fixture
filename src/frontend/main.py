"""Fixture demo web app: sign in with Google, then see your calendar and inbox.

Run from src/frontend with:
    uv run uvicorn main:app --port 8501 --reload
"""

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.errors import HttpError
from starlette.middleware.sessions import SessionMiddleware

import google_data

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

# secrets/ at the repo root (this file lives in src/frontend/). Docker overrides it.
SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", Path(__file__).resolve().parents[2] / "secrets"))
CLIENT_FILE = SECRETS_DIR / "web_credentials.json"  # "Fixture Web" OAuth client
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8501/auth/callback")

APP_DIR = Path(__file__).resolve().parent

# Short codes passed in the URL as ?error=..., shown on the sign-in page.
ERRORS = {
    "cancelled": "Sign-in was cancelled.",
    "expired": "Your sign-in expired. Please try again.",
    "scopes": "Fixture needs both Calendar and Gmail access. Please allow both.",
}

app = FastAPI(title="Fixture")
# The browser cookie only holds a random session id; Google tokens stay on the server.
app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32), same_site="lax")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

# Signed-in users' credentials, keyed by session id. Kept in memory only,
# so restarting the server signs everyone out. Fine for a demo.
CREDENTIALS: dict[str, Credentials] = {}


def make_flow(**kwargs) -> Flow:
    return Flow.from_client_secrets_file(
        str(CLIENT_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI, **kwargs
    )


def current_credentials(request: Request) -> Credentials | None:
    """Return this browser's Google credentials, refreshing them if expired."""
    creds = CREDENTIALS.get(request.session.get("sid", ""))
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
    return creds if creds and creds.valid else None


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
        {"user": request.session.get("user"), "calendar": calendar, "inbox": inbox},
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

    sid = secrets.token_urlsafe(16)
    CREDENTIALS[sid] = creds
    request.session.clear()
    request.session["sid"] = sid
    request.session["user"] = google_data.fetch_profile(creds)
    return RedirectResponse("/")


@app.get("/auth/logout")
def logout(request: Request):
    CREDENTIALS.pop(request.session.get("sid", ""), None)
    request.session.clear()
    return RedirectResponse("/")
