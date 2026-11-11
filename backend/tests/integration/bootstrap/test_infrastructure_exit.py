"""S4 (2a F4): a database that is unreachable or not migrated is an infrastructure failure,
with exit code 3 and one message line in every command, never a traceback."""

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from recon.bootstrap.cli import evaluate_main, main, reconcile_main, reference_main
from tests.integration.conftest import create_database, drop_database

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
OCTOBER = ["--from", "2026-10-01", "--to", "2026-10-31"]
UNREACHABLE = "postgresql+psycopg://recon@127.0.0.1:1/none"

Command = tuple[str, Callable[[Sequence[str] | None], int], Callable[[Path, Path], list[str]]]
COMMANDS: list[Command] = [
    ("recon-import", main, lambda export, _: [str(export)]),
    ("recon-reference", reference_main, lambda _, __: [str(REFERENCE_FILE)]),
    ("recon-reconcile", reconcile_main, lambda _, __: OCTOBER),
    (
        "recon-evaluate",
        evaluate_main,
        lambda export, tmp: [str(export), *OCTOBER, "--report", str(tmp / "report.md")],
    ),
]


@pytest.fixture
def unmigrated() -> Iterator[str]:
    url = create_database()
    yield url
    drop_database(url)


@pytest.mark.parametrize(("name", "command", "args"), COMMANDS, ids=[c[0] for c in COMMANDS])
@pytest.mark.parametrize("database", ["unreachable", "unmigrated"])
def test_a_database_failure_exits_3_with_one_message_line(
    name: str,
    command: Callable[[Sequence[str] | None], int],
    args: Callable[[Path, Path], list[str]],
    database: str,
    request: pytest.FixtureRequest,
    sample: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = UNREACHABLE if database == "unreachable" else request.getfixturevalue("unmigrated")
    monkeypatch.setenv("RECON_DATABASE_URL", url)

    assert command(args(sample, tmp_path)) == 3

    out, err = capsys.readouterr()
    assert err.startswith(f"{name}: database unavailable:")
    assert len(err.splitlines()) == 1
    assert "Traceback" not in err and "warning" not in err
    assert out == ""
    assert not (tmp_path / "report.md").exists()
