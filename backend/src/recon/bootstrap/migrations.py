from pathlib import Path

from alembic import command
from alembic.config import Config

# shortcut: migrations are read from the source tree (backend/migrations); package them with
# the wheel when the backend is deployed outside this repository.
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(_config(url), revision)
