#!/usr/bin/env bash
# Local run of the CI quality gates, aborting on the first failure:
# ruff, mypy, pytest and pip-audit (config in pyproject.toml and pytest.ini).
# .github/workflows/ci.yml runs the same steps on every pull request.
#
# Usage: bash scripts/local_ci.sh
set -euo pipefail

echo "== ruff =="
ruff check .
ruff format --check .

echo "== mypy =="
mypy backend/src

echo "== pytest =="
pytest

echo "== pip-audit =="
pip-audit -r requirements-dev.lock --require-hashes --disable-pip
pip-audit -r requirements.lock --require-hashes --disable-pip

echo "Local CI green."
