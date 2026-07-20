#!/usr/bin/env bash
#
# validate_milestone.sh — single replayable entrypoint for every non-unit
# milestone acceptance proof (TEST-02).
#
# It wraps (never re-implements) the existing in-repo proofs, runs each one,
# records a per-criterion PASS/FAIL, prints a summary matrix, and exits
# non-zero if ANY wrapped proof failed:
#
#   ROB-01  concurrent FAISS load       -> tests/performance/test_faiss_concurrency.py
#   COST-01 budget cap, 10 parallel      -> tests/performance/test_budget_concurrency.py
#   SEC-03  N+1 request -> 429           -> tests/integration/test_rate_limits.py
#   OPS-03  backup -> restore (verified) -> scripts/backup_sqlite.py + scripts/restore_sqlite.py
#   OPS-01  clean-machine deploy         -> scripts/deploy_clean_machine.sh  (opt-in)
#
# Design: we deliberately do NOT use bare `set -e` around the proof loop. Each
# proof runs, its exit code is captured, and execution continues so the operator
# sees the FULL pass/fail matrix rather than stopping at the first failure. The
# overall exit code is non-zero if any criterion failed.
#
# Mistral free-tier safety: none of the DEFAULT proofs make a real Mistral call.
# The three pytest proofs mock/avoid the API, OPS-03 only touches SQLite, and the
# OPS-01 clean-machine deploy keeps its live-SSE smoke gated behind
# RUN_STREAM_SMOKE=1 inside deploy_clean_machine.sh.
#
# The heavy Docker proof (OPS-01) is OPT-IN. The default run executes the fast,
# safe subset (3 pytest proofs + backup/restore). Set RUN_DEPLOY=1 to also run
# the full clean-machine deploy.
#
# Prerequisites: run with the project's Python environment active (conda env
# "Mimir"), from anywhere — the script cd's to the repo root itself.
#
# Usage:
#   scripts/validate_milestone.sh              # fast subset (ROB-01/COST-01/SEC-03/OPS-03)
#   RUN_DEPLOY=1 scripts/validate_milestone.sh # additionally run OPS-01 clean-machine deploy
#
set -uo pipefail

# --- Colored status helpers (matching the repo's start-servers.sh style) ------
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
banner() { echo -e "\n${BLUE}=== $* ===${NC}"; }
info()   { echo -e "${YELLOW}➜ ${NC}$*"; }
ok()     { echo -e "${GREEN}✅ ${NC}$*"; }
fail()   { echo -e "${RED}❌ ${NC}$*" >&2; }

# Always run from the repo root (this script lives in scripts/) so relative
# settings paths (./data/sqlite/mimir.db, ./data/backups) resolve correctly.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

RUN_DEPLOY="${RUN_DEPLOY:-0}"
PYTEST_NO_COV=(-o addopts="")  # disable coverage/strict addopts for targeted runs

# Per-criterion result matrix: parallel arrays of "ID" and "STATUS".
declare -a CRIT_IDS
declare -a CRIT_STATUS
OVERALL_RC=0

record() {  # $1=criterion id, $2=status (PASS|FAIL|SKIP)
  CRIT_IDS+=("$1")
  CRIT_STATUS+=("$2")
  if [ "$2" = "FAIL" ]; then
    OVERALL_RC=1
  fi
}

# ---------------------------------------------------------------------------
# ROB-01 — concurrent FAISS load (readers during an active ingestion write).
# ---------------------------------------------------------------------------
banner "ROB-01: concurrent FAISS load"
info "python -m pytest tests/performance/test_faiss_concurrency.py"
if python -m pytest tests/performance/test_faiss_concurrency.py -q "${PYTEST_NO_COV[@]}"; then
  ok "ROB-01 passed"; record "ROB-01" "PASS"
else
  fail "ROB-01 failed"; record "ROB-01" "FAIL"
fi

# ---------------------------------------------------------------------------
# COST-01 — 10 parallel budget reservations against a cap of 5 -> exactly 5.
# ---------------------------------------------------------------------------
banner "COST-01: budget cap under 10 parallel reservations"
info "python -m pytest tests/performance/test_budget_concurrency.py"
if python -m pytest tests/performance/test_budget_concurrency.py -q "${PYTEST_NO_COV[@]}"; then
  ok "COST-01 passed"; record "COST-01" "PASS"
else
  fail "COST-01 failed"; record "COST-01" "FAIL"
fi

# ---------------------------------------------------------------------------
# SEC-03 — request N+1 beyond the per-route limit returns 429 (+ Retry-After).
# ---------------------------------------------------------------------------
banner "SEC-03: N+1 request returns 429"
info "python -m pytest tests/integration/test_rate_limits.py"
if python -m pytest tests/integration/test_rate_limits.py -q "${PYTEST_NO_COV[@]}"; then
  ok "SEC-03 passed"; record "SEC-03" "PASS"
else
  fail "SEC-03 failed"; record "SEC-03" "FAIL"
fi

# ---------------------------------------------------------------------------
# OPS-03 — WAL-safe backup, then restore-and-verify (integrity + row counts).
# The restore materializes into a THROWAWAY target inside the data/ tree, never
# over the live DB. Source DB and backup dir are resolved from the same settings
# the backup script itself uses.
# ---------------------------------------------------------------------------
banner "OPS-03: backup -> restore (integrity + row counts)"
ops03_backup_restore() {
  info "python scripts/backup_sqlite.py"
  local backup_out backup_path source_db restore_target rc
  backup_out="$(python scripts/backup_sqlite.py)" || return 1
  echo "$backup_out"
  # backup_sqlite.py prints: "Backup written: <path>"
  backup_path="$(printf '%s\n' "$backup_out" | sed -n 's/^Backup written: //p')"
  if [ -z "$backup_path" ]; then
    fail "Could not parse backup path from backup_sqlite.py output"
    return 1
  fi
  # Resolve the live source DB from settings (same source the backup used).
  source_db="$(python -c "import sys; sys.path.insert(0, 'backend'); from src.config import settings; from pathlib import Path; print(Path(settings.database_url.replace('sqlite:///', '')).resolve())")" || return 1
  # Throwaway restore target inside the data/ tree (restore guard requires it).
  restore_target="data/sqlite/_restore_verify_$$.db"
  rm -f "$restore_target"
  info "python scripts/restore_sqlite.py <backup> <source> <throwaway target>"
  python scripts/restore_sqlite.py "$backup_path" "$source_db" "$restore_target"
  rc=$?
  rm -f "$restore_target"
  return $rc
}
if ops03_backup_restore; then
  ok "OPS-03 passed"; record "OPS-03" "PASS"
else
  fail "OPS-03 failed"; record "OPS-03" "FAIL"
fi

# ---------------------------------------------------------------------------
# OPS-01 — clean-machine Docker deploy + smoke (OPT-IN; heavy build).
# Gated behind RUN_DEPLOY=1 so the default run stays fast. When skipped it is
# recorded as SKIP (not FAIL); 05-05 already proved this end-to-end.
# ---------------------------------------------------------------------------
banner "OPS-01: clean-machine deploy"
if [ "$RUN_DEPLOY" = "1" ]; then
  info "bash scripts/deploy_clean_machine.sh"
  if bash scripts/deploy_clean_machine.sh; then
    ok "OPS-01 passed"; record "OPS-01" "PASS"
  else
    fail "OPS-01 failed"; record "OPS-01" "FAIL"
  fi
else
  info "Skipping OPS-01 clean-machine deploy (set RUN_DEPLOY=1 to run the heavy Docker proof)."
  record "OPS-01" "SKIP"
fi

# ---------------------------------------------------------------------------
# Summary matrix + overall result.
# ---------------------------------------------------------------------------
banner "Milestone validation summary (TEST-02)"
printf '  %-8s | %s\n' "CRITERION" "RESULT"
printf '  %-8s-+-%s\n' "--------" "------"
for i in "${!CRIT_IDS[@]}"; do
  status="${CRIT_STATUS[$i]}"
  case "$status" in
    PASS) color="$GREEN" ;;
    FAIL) color="$RED" ;;
    *)    color="$YELLOW" ;;
  esac
  printf "  %-8s | ${color}%s${NC}\n" "${CRIT_IDS[$i]}" "$status"
done
echo ""
if [ "$OVERALL_RC" -eq 0 ]; then
  echo -e "${GREEN}=========================================${NC}"
  echo -e "${GREEN} OVERALL: PASS — all run proofs succeeded${NC}"
  echo -e "${GREEN}=========================================${NC}"
else
  echo -e "${RED}=========================================${NC}"
  echo -e "${RED} OVERALL: FAIL — at least one proof failed${NC}"
  echo -e "${RED}=========================================${NC}"
fi

exit "$OVERALL_RC"
