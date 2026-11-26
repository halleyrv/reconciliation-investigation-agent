import importlib.util

import pytest

from recon.bootstrap.cli import compare_retrieval_main


@pytest.mark.skipif(
    importlib.util.find_spec("fastembed") is not None, reason="fastembed is installed here"
)
def test_compare_retrieval_without_fastembed_points_to_the_models_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert compare_retrieval_main([]) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert err == (
        "recon-compare-retrieval: fastembed is not installed on this platform;"
        " run it in Linux: docker compose run --rm models uv run --locked"
        " recon-compare-retrieval\n"
    )
