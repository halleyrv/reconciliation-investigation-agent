from pathlib import Path
from typing import Any

import pytest
import yaml
from simulator.cli import main

CONFIGS = Path(__file__).parents[1] / "configs"
DEFAULT_CONFIG = CONFIGS / "default.yaml"


def raw_default() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(DEFAULT_CONFIG.read_text())
    return raw


def run(tmp: Path, raw: dict[str, Any], seed: int = 42) -> Path:
    config = tmp / "config.yaml"
    config.write_text(yaml.safe_dump(raw))
    out = tmp / "out"
    assert main(["--config", str(config), "--seed", str(seed), "--out", str(out)]) == 0
    return out


@pytest.fixture(scope="session")
def anomalous_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return run(tmp_path_factory.mktemp("anomalous"), raw_default())


@pytest.fixture(scope="session")
def clean_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    raw = raw_default()
    raw["anomaly_rates"] = {}
    return run(tmp_path_factory.mktemp("clean"), raw)
