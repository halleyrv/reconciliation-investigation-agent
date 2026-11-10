from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from recon.bootstrap.cli import main


@pytest.fixture
def database(migrated_url: str, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    return engine


def test_importing_a_directory_reports_each_batch_and_exits_0(
    database: Engine, sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(sample)]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "orders.json: completed, 204 records"
    assert len(out) == 7
    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM ingestion.orders")).scalar() == 200


def test_a_rejected_file_is_reported_with_line_and_field_and_exits_1(
    database: Engine, sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    import json

    path = sample / "refunds.json"
    data = json.loads(path.read_text())
    data["records"][1]["amount"] = "1.234"
    path.write_text(json.dumps(data))
    manifest = json.loads((sample / "manifest.json").read_text())
    manifest["files"]["refunds.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (sample / "manifest.json").write_text(json.dumps(manifest))

    assert main([str(sample)]) == 1

    out = capsys.readouterr().out
    assert "refunds.json: failed\n  line 2, amount: " in out


@pytest.mark.parametrize("damage", ["tamper", "missing"])
def test_an_export_that_cannot_be_trusted_writes_nothing_and_exits_2(
    database: Engine, sample: Path, capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    path = sample / "fees.json"
    if damage == "tamper":
        path.write_text(path.read_text().replace("12.33", "12.34", 1))
    else:
        path.unlink()

    assert main([str(sample)]) == 2

    assert "fees.json" in capsys.readouterr().err
    with database.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM ingestion.import_batches")).scalar() == 0
        )
