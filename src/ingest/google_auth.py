"""Google sign-in helper shared by anything that talks to Google APIs.

The first run opens a browser to log in, then saves a token in secrets/
so later runs sign in silently.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# All the permissions Fixture asks for, in one place.
# To add Gmail later, add a Gmail scope here, for example:
#   "https://www.googleapis.com/auth/gmail.readonly"
# The next run notices the token is missing it and asks you to log in again.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]

# secrets/ at the repo root (this file lives in src/ingest/).
SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"
CREDENTIALS_FILE = SECRETS_DIR / "credentials.json"  # OAuth client, downloaded from Google Cloud
TOKEN_FILE = SECRETS_DIR / "token.json"  # your personal login, created on first run


def get_credentials() -> Credentials:
    """Return valid Google credentials, logging in through the browser if needed."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))

    # The saved token was made before SCOPES changed, so log in again.
    if creds and not creds.has_scopes(SCOPES):
        print("Permissions changed since your last login. Opening browser to log in again.")
        creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Missing {CREDENTIALS_FILE}. Download the OAuth client JSON "
                "from Google Cloud and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    return creds
