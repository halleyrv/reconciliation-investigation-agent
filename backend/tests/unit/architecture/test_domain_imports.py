"""AC-2a.8 as an allowlist: import-linter forbidden contracts only catch listed packages."""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parents[3] / "src" / "recon"
PURE = [*SRC.glob("*/domain/**/*.py"), *(SRC / "shared_kernel").glob("**/*.py")]


def _imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _allowed(module: str, path: Path) -> bool:
    if module.split(".")[0] in sys.stdlib_module_names:
        return True
    if module.startswith("recon.shared_kernel"):
        return True
    context = path.relative_to(SRC).parts[0]  # a domain may import its own domain
    return context != "shared_kernel" and module.startswith(f"recon.{context}.domain")


@pytest.mark.parametrize("path", PURE, ids=lambda p: str(p.relative_to(SRC)))
def test_domain_and_shared_kernel_import_only_the_stdlib_and_the_shared_kernel(path: Path) -> None:
    assert [m for m in sorted(_imported_modules(path)) if not _allowed(m, path)] == []


def test_the_allowlist_rejects_a_third_party_and_a_context_import() -> None:
    domain = SRC / "ingestion" / "domain" / "records.py"
    kernel = SRC / "shared_kernel" / "money.py"
    assert not _allowed("yaml", domain)
    assert not _allowed("recon.ingestion.application", domain)
    assert not _allowed("recon.ingestion.domain.records", kernel)
    assert _allowed("recon.ingestion.domain.batch", domain)
