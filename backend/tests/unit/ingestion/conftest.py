import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from recon.ingestion.adapters.outbound.memory import InMemoryIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

SAMPLE = Path(__file__).parents[4] / "simulator" / "samples" / "orders-200-seed-42"


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    """A private copy of the committed sample, safe to tamper with."""
    return Path(shutil.copytree(SAMPLE, tmp_path / "export"))


@pytest.fixture
def uow() -> InMemoryIngestionUnitOfWork:
    return InMemoryIngestionUnitOfWork()


@pytest.fixture
def import_export(uow: InMemoryIngestionUnitOfWork) -> ImportExport:
    return ImportExport(uow, FixedClock(datetime(2026, 11, 9, tzinfo=UTC)), SequenceIdGenerator())
