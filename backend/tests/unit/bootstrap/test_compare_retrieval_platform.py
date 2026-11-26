import importlib.util
from collections.abc import Callable, Sequence

import pytest

from recon.bootstrap.cli import compare_retrieval_main, ingest_corpus_main


@pytest.mark.skipif(
    importlib.util.find_spec("fastembed") is not None, reason="fastembed is installed here"
)
@pytest.mark.parametrize(
    ("main", "command"),
    [
        (compare_retrieval_main, "recon-compare-retrieval"),
        (ingest_corpus_main, "recon-ingest-corpus"),
    ],
)
def test_a_model_command_without_fastembed_points_to_the_models_service(
    capsys: pytest.CaptureFixture[str],
    main: Callable[[Sequence[str] | None], int],
    command: str,
) -> None:
    assert main([]) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert err == (
        f"{command}: fastembed is not installed on this platform;"
        f" run it in Linux: docker compose run --rm models uv run --locked {command}\n"
    )
