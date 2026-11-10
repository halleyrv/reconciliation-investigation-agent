import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from recon.bootstrap.cli import reference_main

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"


@pytest.fixture
def database(migrated_url: str, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    return engine


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM recon.{table}")).scalar_one())


def test_loading_the_reference_file_twice_adds_it_once_and_exits_0(
    database: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert reference_main([str(REFERENCE_FILE)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out == [
        "fee schedules: 2 added, 0 already loaded",
        "holidays: 7 added, 0 already loaded",
        "calendar years: 1 added, 0 already loaded",
        "fee schedules: 0 added, 2 already loaded",
        "holidays: 0 added, 7 already loaded",
        "calendar years: 0 added, 1 already loaded",
    ]
    assert (_count(database, "fee_schedules"), _count(database, "holidays")) == (2, 7)


def test_a_conflicting_schedule_loads_nothing_and_exits_1(
    database: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert reference_main([str(REFERENCE_FILE)]) == 0
    content = json.loads(REFERENCE_FILE.read_text())
    content["fee_schedules"][0] |= {"rate_bps": 300, "valid_from": "2026-06-01"}
    content["holidays"].append("2026-12-25")
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(content))

    assert reference_main([str(changed)]) == 1

    err = capsys.readouterr().err
    assert "recon-reference: nothing loaded: gateway_a processing from 2026-06-01 overlaps" in err
    assert (_count(database, "fee_schedules"), _count(database, "holidays")) == (2, 7)


@pytest.mark.parametrize("content", ["{not json", '{"fee_schedules": [], "holidays": [1]}'])
def test_an_unreadable_file_exits_2(
    database: Engine, tmp_path: Path, content: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content)

    assert reference_main([str(path)]) == 2
    assert reference_main([str(tmp_path / "missing.json")]) == 2

    assert capsys.readouterr().err.startswith("recon-reference: nothing loaded:")
    assert _count(database, "holidays") == 0
