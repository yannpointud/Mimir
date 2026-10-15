#!/usr/bin/env bash
# scripts/local_ci.sh -- Mimir local CI runner.
#
# Single entrypoint chaining three quality gates, aborting on the first failure:
#   1. ruff       -- static lint and formatting check (config in
#                    pyproject.toml [tool.ruff])
#   2. pytest     -- the full test suite (testpaths=tests in pytest.ini:
#                    unit + integration + performance, incl. the
#                    health/alerting/backup tests and the reused
#                    FAISS concurrency, budget cap and rate-limit harnesses)
#   3. pip-audit  -- runtime dependency vulnerability scan against the PyPA
#                    advisory database
#
# The GitHub Actions workflow (.github/workflows/ci.yml) runs the same steps
# on every pull request.
#
# Usage: bash scripts/local_ci.sh
set -euo pipefail

echo "== ruff =="
ruff check .
ruff format --check .

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
    # pytest 7.4.3 (fix 9.0.3): test-only dependency, major upgrade that also
    # requires a pytest-asyncio upgrade.
    --ignore-vuln PYSEC-2026-1845
)
pip-audit -r requirements.txt "${PIP_AUDIT_IGNORES[@]}"

echo "Local CI green."
