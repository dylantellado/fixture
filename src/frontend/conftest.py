"""Shared test setup. pytest loads this before any test file.

main.py needs two secrets and a data folder as soon as it's imported. Give it
throwaway values here, so tests never use your real .env keys or
data/fixture.db. (load_dotenv doesn't override variables that are already set.)
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fixture-test-")
