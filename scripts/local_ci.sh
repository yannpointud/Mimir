#!/usr/bin/env bash
# scripts/local_ci.sh -- Mimir local CI runner.
#
# Single entrypoint chaining four quality gates, aborting on the first failure:
#   1. ruff       -- static lint and formatting check (config in
#                    pyproject.toml [tool.ruff])
#   2. mypy       -- static type check of backend/src (config in
#                    pyproject.toml [tool.mypy])
#   3. pytest     -- the full test suite (testpaths=tests in pytest.ini:
#                    unit + integration + performance, incl. the
#                    health/alerting/backup tests and the reused
#                    FAISS concurrency, budget cap and rate-limit harnesses)
#   4. pip-audit  -- dependency vulnerability scan against the PyPA advisory
#                    database, of the hash-pinned requirements-dev.lock and of
#                    requirements.txt
#
# The GitHub Actions workflow (.github/workflows/ci.yml) runs the same steps
# on every pull request.
#
# Usage: bash scripts/local_ci.sh
set -euo pipefail

echo "== ruff =="
ruff check .
ruff format --check .

echo "== mypy =="
mypy backend/src

echo "== pytest (full suite) =="
pytest

echo "== pip-audit =="
# Advisories that cannot be fixed without leaving the current scope. Keep this
# list in sync with .github/workflows/ci.yml. Any other advisory fails the run.
#
# To re-audit including these, run: pip-audit -r requirements.txt
PIP_AUDIT_IGNORES=(
    # orjson 3.10.18 (fix 3.11.5): pinned below 3.11 by mistralai 0.4.2; the
    # fix requires migrating the Mistral SDK.
    --ignore-vuln PYSEC-2026-107
)
pip-audit -r requirements-dev.lock --require-hashes --disable-pip "${PIP_AUDIT_IGNORES[@]}"
pip-audit -r requirements.txt "${PIP_AUDIT_IGNORES[@]}"

echo "Local CI green."
