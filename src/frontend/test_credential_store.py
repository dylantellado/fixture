"""Tests for credential_store.py, using fake credentials and a temporary database."""

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials

from credential_store import CredentialStore

EMAIL = "test.user@example.com"


def fake_credentials(token: str = "fake-access-token") -> Credentials:
    return Credentials(
        token=token,
        refresh_token="fake-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )


def make_store(tmp_path, key=None) -> CredentialStore:
    return CredentialStore(tmp_path / "test.db", key or Fernet.generate_key())


def test_save_then_load_returns_same_credentials(tmp_path):
    store = make_store(tmp_path)
    store.save(EMAIL, fake_credentials(), name="Test User", picture="https://example.com/p.png")

    loaded = store.load(EMAIL)
    assert loaded.token == "fake-access-token"
    assert loaded.refresh_token == "fake-refresh-token"
    assert loaded.client_id == "fake-client-id"
    assert loaded.scopes == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert store.load_profile(EMAIL) == {
        "email": EMAIL,
        "name": "Test User",
        "picture": "https://example.com/p.png",
    }


def test_saving_again_overwrites_credentials_but_keeps_profile(tmp_path):
    store = make_store(tmp_path)
    store.save(EMAIL, fake_credentials("old-token"), name="Test User")
    # A refresh saves new credentials without a profile.
    store.save(EMAIL, fake_credentials("new-token"))

    assert store.load(EMAIL).token == "new-token"
    assert store.load_profile(EMAIL)["name"] == "Test User"


def test_delete_removes_user(tmp_path):
    store = make_store(tmp_path)
    store.save(EMAIL, fake_credentials())
    store.delete(EMAIL)

    assert store.load(EMAIL) is None
    assert store.load_profile(EMAIL) is None


def test_unknown_email_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.load("nobody@example.com") is None
    store.delete("nobody@example.com")  # deleting a missing user is fine


def test_credentials_are_encrypted_on_disk(tmp_path):
    store = make_store(tmp_path)
    store.save(EMAIL, fake_credentials())

    raw = (tmp_path / "test.db").read_bytes()
    assert b"fake-access-token" not in raw
    assert b"fake-refresh-token" not in raw
    assert b"fake-client-secret" not in raw


def test_wrong_key_cannot_read_credentials(tmp_path):
    make_store(tmp_path).save(EMAIL, fake_credentials())

    # Same database file, different key: treated as signed out, not a crash.
    other = make_store(tmp_path, key=Fernet.generate_key())
    assert other.load(EMAIL) is None


def test_data_survives_a_new_store_instance(tmp_path):
    # Simulates a server restart: same file, same key, new object.
    key = Fernet.generate_key()
    make_store(tmp_path, key).save(EMAIL, fake_credentials())
    assert make_store(tmp_path, key).load(EMAIL).token == "fake-access-token"
