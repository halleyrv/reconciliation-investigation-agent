import os
from pathlib import Path

# The default points at the Compose database (compose.yaml), which needs no password.
DEFAULT_DATABASE_URL = "postgresql+psycopg://recon@127.0.0.1:55432/recon"


def database_url() -> str:
    return os.environ.get("RECON_DATABASE_URL", DEFAULT_DATABASE_URL)


def import_root() -> Path | None:
    """The only directory tree ``POST /imports`` may read; unset means the API imports nothing."""
    value = os.environ.get("RECON_IMPORT_ROOT")
    return Path(value).resolve() if value else None
