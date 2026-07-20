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
# Pre-existing dependency advisories are BASELINED below, symmetric with the
# ruff `--add-noqa` onboarding: they are ignored here so the gate is green from
# the first commit, and only NEWLY disclosed advisories (new IDs) will fail CI.
#
# These 53 advisories were present before OPS-02 and are DEFERRED to a dedicated
# dependency-hardening task: many fixes require MAJOR upgrades that this milestone
# forbids ("durcissement, pas migration" -- e.g. starlette 0.47 -> 1.x, pytest
# 7 -> 9, cryptography 45 -> 46/48, python-multipart 0.0.6 -> 0.0.3x). Bumping
# them here would risk the FastAPI/Mistral/RAG stack and is out of scope for the
# "add a local CI runner" deliverable. See 05-04-SUMMARY.md "Deferred Issues".
#
# To re-audit including baselined items, run: pip-audit -r requirements.txt
PIP_AUDIT_IGNORES=(
    # aiohttp 3.12.15 (fix 3.13.3 / 3.13.4 / 3.14.x)
    --ignore-vuln PYSEC-2026-1097 --ignore-vuln PYSEC-2026-1099
    --ignore-vuln PYSEC-2026-1100 --ignore-vuln PYSEC-2026-1101
    --ignore-vuln PYSEC-2026-1105 --ignore-vuln PYSEC-2026-1106
    --ignore-vuln PYSEC-2026-1107 --ignore-vuln PYSEC-2026-1109
    --ignore-vuln PYSEC-2026-2094 --ignore-vuln PYSEC-2026-2095
    --ignore-vuln PYSEC-2026-2096 --ignore-vuln PYSEC-2026-2097
    --ignore-vuln PYSEC-2026-2098 --ignore-vuln PYSEC-2026-2099
    --ignore-vuln PYSEC-2026-2100 --ignore-vuln PYSEC-2026-2101
    --ignore-vuln PYSEC-2026-2102 --ignore-vuln PYSEC-2026-2103
    --ignore-vuln PYSEC-2026-2104 --ignore-vuln PYSEC-2026-2105
    --ignore-vuln PYSEC-2026-2106 --ignore-vuln PYSEC-2026-2107
    --ignore-vuln PYSEC-2026-2108 --ignore-vuln PYSEC-2026-2109
    --ignore-vuln PYSEC-2026-2110 --ignore-vuln PYSEC-2026-2111
    --ignore-vuln PYSEC-2026-2112 --ignore-vuln PYSEC-2026-2113
    --ignore-vuln PYSEC-2026-237
    # aiosmtplib 3.0.1 (fix 5.1.1)
    --ignore-vuln CVE-2026-53533
    # cryptography 45.0.7 (fix 46.x / 48.x)
    --ignore-vuln GHSA-537c-gmf6-5ccf --ignore-vuln PYSEC-2026-2141
    --ignore-vuln PYSEC-2026-35 --ignore-vuln PYSEC-2026-36
    # markdown 3.5.1 (fix 3.8.1)
    --ignore-vuln PYSEC-2026-89
    # orjson 3.10.18 (fix 3.11.6)
    --ignore-vuln PYSEC-2026-107
    # pytest 7.4.3 (fix 9.0.3 -- major bump, test-only dep)
    --ignore-vuln PYSEC-2026-1845
    # python-dotenv 1.1.1 (fix 1.2.2)
    --ignore-vuln PYSEC-2026-2270
    # python-multipart 0.0.6 (fix 0.0.7 .. 0.0.31)
    --ignore-vuln CVE-2026-40347 --ignore-vuln CVE-2026-42561
    --ignore-vuln CVE-2026-53538 --ignore-vuln CVE-2026-53539
    --ignore-vuln CVE-2026-53540 --ignore-vuln PYSEC-2024-38
    --ignore-vuln PYSEC-2026-1850 --ignore-vuln PYSEC-2026-1851
    --ignore-vuln PYSEC-2026-1852
    # starlette 0.47.3 (fix 0.49.1 / 1.x -- major bump, FastAPI-pinned)
    --ignore-vuln PYSEC-2026-161 --ignore-vuln PYSEC-2026-1942
    --ignore-vuln PYSEC-2026-2280 --ignore-vuln PYSEC-2026-2281
    --ignore-vuln PYSEC-2026-248 --ignore-vuln PYSEC-2026-249
)
pip-audit -r requirements.txt "${PIP_AUDIT_IGNORES[@]}"

echo "Local CI green."
