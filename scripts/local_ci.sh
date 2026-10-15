#!/usr/bin/env bash
# scripts/local_ci.sh -- Mimir local CI runner (OPS-02).
#
# Single entrypoint chaining three quality gates, aborting on the first failure:
#   1. ruff       -- static lint (config in pyproject.toml [tool.ruff])
#   2. pytest     -- the full test suite (testpaths=tests in pytest.ini:
#                    unit + integration + performance, incl. the phase-05
#                    health/alerting/backup tests and the reused
#                    ROB-01/COST-01/SEC-03 harnesses)
#   3. pip-audit  -- runtime dependency vulnerability scan against the PyPA
#                    advisory database
#
# LOCAL-ONLY: this runner never pushes to GitHub and makes no remote calls
# (project constraint: local git only). A committed-but-unpushed GitHub Actions
# workflow mirroring these three steps would be acceptable, but this local
# runner is the deliverable.
#
# Usage: bash scripts/local_ci.sh
set -euo pipefail

echo "== ruff =="
ruff check .

echo "== pytest (full suite) =="
pytest

echo "== pip-audit =="
# Advisories that cannot be fixed without leaving the current scope. Any other
# advisory fails the run.
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
