#!/usr/bin/env bash
# Quality gate. The same script runs locally, in the pre-commit hook and in CI.
# It stops at the first failing step with a non-zero exit code.
set -euo pipefail
cd "$(dirname "$0")/.."

step() {
  echo "==> $*"
  uv run --locked "$@"
}

step ruff format --check .
step ruff check .
step lint-imports
step mypy
step pytest -q

echo "==> quality gate passed"
