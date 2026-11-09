from importlib.metadata import version

import simulator


def test_package_version_matches_installed_distribution() -> None:
    assert simulator.__version__ == version("simulator")
