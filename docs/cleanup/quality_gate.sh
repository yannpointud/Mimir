#!/usr/bin/env bash
# Quality gate of the cleanup mission (see docs/cleanup/BASELINE.md).
#
# Usage: bash docs/cleanup/quality_gate.sh [output_dir]
#
# Runs every check of the gate and writes key=value metrics to
# <output_dir>/metrics.env plus the raw tool outputs next to it. The exit code
# is non-zero when a hard check fails (frozen oracle checksums, oracle or
# integration tests, vitest, front build, fresh-venv health probe). Relative
# checks (test count, coverage, ruff/mypy/pip-audit deltas) are compared by
# the caller against the metrics of the previous pass.
#
# Secrets are forced to dummy values: the real environment is never used.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$(mktemp -d)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
VENV="$ROOT/.venv"
METRICS="$OUT/metrics.env"
: > "$METRICS"
FAILED=0

export MISTRAL_API_KEY=test-key
JWT_SECRET_KEY="$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)))')"
export JWT_SECRET_KEY
export ENVIRONMENT=test
unset MISTRAL_MODEL

metric() { echo "$1=$2" >> "$METRICS"; echo "$1=$2"; }
fail() { FAILED=1; echo "GATE FAILURE: $1"; }

cd "$ROOT"

echo "== frozen oracle checksums =="
if sha256sum --quiet -c docs/cleanup/ORACLE.sha256 > "$OUT/sha256.txt" 2>&1; then
    metric oracle_sha256 ok
else
    metric oracle_sha256 fail; fail "frozen oracle files changed"
fi

echo "== pytest (full suite) =="
"$VENV/bin/python" -m pytest -q -p no:cacheprovider > "$OUT/pytest.txt" 2>&1
SUMMARY="$(grep -E '^=+ .*(passed|failed).* in [0-9.]+s' "$OUT/pytest.txt" | tail -1)"
count() { echo "$SUMMARY" | grep -oE "[0-9]+ $1" | grep -oE '^[0-9]+' || echo 0; }
PASSED=$(count passed); FAILED_T=$(count failed); SKIPPED=$(count skipped); ERRORS=$(count error)
metric tests_total $((PASSED + FAILED_T + SKIPPED + ERRORS))
metric tests_passed "$PASSED"
metric tests_failed "$FAILED_T"
metric tests_errors "$ERRORS"
metric tests_skipped "$SKIPPED"
metric coverage "$(grep -oE 'Total coverage: [0-9.]+%' "$OUT/pytest.txt" | grep -oE '[0-9.]+' || echo 0)"
[ "$FAILED_T" = "0" ] && [ "$ERRORS" = "0" ] || fail "pytest failures"

echo "== oracle + integration tests =="
if "$VENV/bin/python" -m pytest -q -p no:cacheprovider --no-cov tests/oracle tests/integration > "$OUT/pytest_frozen.txt" 2>&1; then
    metric frozen_tests ok
else
    metric frozen_tests fail; fail "oracle/integration tests"
fi

echo "== ruff =="
"$VENV/bin/ruff" check . --output-format concise > "$OUT/ruff.txt" 2>&1
metric ruff_errors "$(grep -cE '^[^ ]+:[0-9]+:[0-9]+: ' "$OUT/ruff.txt")"
if "$VENV/bin/ruff" format --check . > "$OUT/ruff_format.txt" 2>&1; then
    metric ruff_format ok
else
    metric ruff_format "$(grep -c '^Would reformat' "$OUT/ruff_format.txt")_files"
fi

echo "== radon =="
"$VENV/bin/radon" cc -n D -s backend/src > "$OUT/radon.txt" 2>&1
metric radon_d_or_worse "$(grep -cE ' - [DEF] ' "$OUT/radon.txt")"

echo "== mypy =="
"$VENV/bin/mypy" backend/src > "$OUT/mypy.txt" 2>&1
metric mypy_errors "$(grep -cE ': error: ' "$OUT/mypy.txt")"

echo "== pip-audit =="
PIP_AUDIT_REQ="requirements.txt"
if "$VENV/bin/pip-audit" -r "$PIP_AUDIT_REQ" $(sed -n 's/^ *--ignore-vuln \(.*\)$/--ignore-vuln \1/p' scripts/local_ci.sh) > "$OUT/pip_audit.txt" 2>&1; then
    metric pip_audit ok
else
    metric pip_audit fail
fi

echo "== frontend =="
(
    cd frontend
    npm ci --no-audit --no-fund > "$OUT/npm_ci.txt" 2>&1 &&
    npx vitest run > "$OUT/vitest.txt" 2>&1
) && metric vitest ok || { metric vitest fail; fail "vitest"; }
metric vitest_tests "$(grep -oE 'Tests +[0-9]+ passed' "$OUT/vitest.txt" | grep -oE '[0-9]+' || echo 0)"
(cd frontend && npm run build > "$OUT/build.txt" 2>&1) && metric front_build ok || { metric front_build fail; fail "front build"; }

echo "== fresh venv + uvicorn =="
FRESH="$OUT/freshvenv"
RUN="$OUT/run"
rm -rf "$FRESH" "$RUN"
mkdir -p "$RUN"
if python3 -m venv "$FRESH" && "$FRESH/bin/pip" install -q -r requirements.txt > "$OUT/fresh_install.txt" 2>&1; then
    (
        cd backend
        export DATA_DIR="$RUN/data" UPLOAD_DIR="$RUN/data/documents" WATCH_FOLDER="$RUN/data/watch" \
            DATABASE_URL="sqlite:///$RUN/data/sqlite/mimir.db" FAISS_INDEX_PATH="$RUN/data/faiss/index.bin" \
            FAISS_METADATA_PATH="$RUN/data/faiss/metadata.json" BM25_INDEX_PATH="$RUN/data/bm25/index" \
            SQLITE_BACKUP_DIR="$RUN/data/backups"
        exec "$FRESH/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 8765
    ) > "$OUT/uvicorn.txt" 2>&1 &
    UVICORN_PID=$!
    CODE=000
    for _ in $(seq 1 60); do
        CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/v1/health/live || true)
        [ "$CODE" = "200" ] && break
        sleep 1
    done
    kill "$UVICORN_PID" 2>/dev/null; wait "$UVICORN_PID" 2>/dev/null
    metric health_live "$CODE"
    [ "$CODE" = "200" ] || fail "health/live from a fresh venv"
else
    metric health_live install_failed; fail "fresh venv install"
fi
rm -rf "$FRESH"

echo "== result =="
if [ "$FAILED" = "0" ]; then echo "GATE: hard checks passed"; else echo "GATE: FAILED"; fi
exit "$FAILED"
