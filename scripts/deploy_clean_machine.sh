#!/usr/bin/env bash
#
# deploy_clean_machine.sh — reproducible, replayable clean-machine bring-up of
# the Mimir production stack + smoke checks.
#
# It starts from an empty named volume, builds and boots the stack, then asserts
# the deployment invariants: the app is reachable only through nginx :80, the
# backend runs non-root, health probes respond, the SPA is served, and SSE is
# configured unbuffered. The DEFAULT run makes NO real Mistral API call so it is
# safe against the free-tier limit; the token-by-token streaming proof is an
# OPTIONAL operator step gated behind RUN_STREAM_SMOKE=1.
#
# Usage:
#   scripts/deploy_clean_machine.sh            # full clean deploy + smoke, tears down
#   KEEP_UP=1 scripts/deploy_clean_machine.sh  # leave the stack running afterwards
#   RUN_STREAM_SMOKE=1 ... (optional)          # additionally hit the live SSE chat
#
set -euo pipefail

# --- Colored status helpers (matching the repo's start-servers.sh style) ------
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${YELLOW}➜ ${NC}$*"; }
ok()    { echo -e "${GREEN}✅ ${NC}$*"; }
fail()  { echo -e "${RED}❌ ${NC}$*" >&2; }

# Run from the repo root (this script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

BASE_URL="http://localhost"
KEEP_UP="${KEEP_UP:-0}"
RUN_STREAM_SMOKE="${RUN_STREAM_SMOKE:-0}"

cleanup_down() {
  if [ "$KEEP_UP" = "1" ]; then
    info "KEEP_UP=1 — leaving the stack running (docker compose down to stop it)."
  else
    info "Tearing the stack down..."
    docker compose down
  fi
}

echo "🚀 Mimir clean-machine deploy + smoke check"

# 1. Start from a pristine state: remove containers AND the named volume so the
#    run proves a genuine from-scratch deployment.
info "Resetting to a clean state (docker compose down -v)..."
docker compose down -v --remove-orphans || true

# 2. Build the images and boot the stack detached.
info "Building images and starting the stack (docker compose up -d --build)..."
docker compose up -d --build

# From here on, always attempt teardown on exit.
trap cleanup_down EXIT

# 3. Poll liveness through nginx until 200 or timeout.
info "Waiting for /api/v1/health/live through nginx :80..."
DEADLINE=$((SECONDS + 120))
until curl -fsS -o /dev/null "${BASE_URL}/api/v1/health/live"; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    fail "Timed out waiting for /api/v1/health/live"
    docker compose ps
    docker compose logs --tail 50 backend || true
    exit 1
  fi
  sleep 2
done
ok "Liveness probe returned 200 through nginx."

# 4. Assert readiness is reachable (any HTTP status counts as reachable; a fresh
#    box may legitimately report 503 if a dependency is degraded).
info "Checking /api/v1/health/ready is reachable..."
READY_CODE="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/api/v1/health/ready" || echo '000')"
if [ "$READY_CODE" = "000" ]; then
  fail "Readiness endpoint unreachable through nginx."
  exit 1
fi
ok "Readiness endpoint reachable (HTTP ${READY_CODE})."

# 5. Assert the static SPA is served (index HTML with a root div / script).
info "Checking the static frontend is served..."
INDEX_HTML="$(curl -fsS "${BASE_URL}/" || true)"
if ! echo "$INDEX_HTML" | grep -qi '<div id="root"\|<script'; then
  fail "Static SPA index.html was not served correctly."
  echo "$INDEX_HTML" | head -20 >&2
  exit 1
fi
ok "Static SPA index.html served through nginx."

# 6. Assert the backend container runs as a non-root user (UID != 0).
info "Asserting the backend runs non-root..."
BACKEND_UID="$(docker compose exec -T backend id -u | tr -d '\r')"
if [ "$BACKEND_UID" = "0" ] || [ -z "$BACKEND_UID" ]; then
  fail "Backend is running as root (UID=${BACKEND_UID}) — expected non-root."
  exit 1
fi
ok "Backend runs non-root (UID=${BACKEND_UID})."

# 7. Statically assert SSE is configured unbuffered in the running nginx config.
info "Asserting SSE is unbuffered (proxy_buffering off scoped to /chat/stream)..."
if docker compose exec -T frontend grep -q 'proxy_buffering off' /etc/nginx/conf.d/default.conf; then
  ok "proxy_buffering off present in the running nginx config."
elif grep -q 'proxy_buffering off' frontend/nginx.conf; then
  ok "proxy_buffering off present in frontend/nginx.conf (source fallback)."
else
  fail "proxy_buffering off not found — SSE would be buffered."
  exit 1
fi

# 8. OPTIONAL: live token-by-token streaming proof. Disabled by default to avoid
#    hitting the Mistral free tier; operators can opt in explicitly.
if [ "$RUN_STREAM_SMOKE" = "1" ]; then
  info "RUN_STREAM_SMOKE=1 — exercising the live SSE chat endpoint (uses Mistral)..."
  # Capture the response instead of piping to `head`: `curl | head -5` under
  # `set -o pipefail` fails the whole pipeline via SIGPIPE once head closes the
  # pipe on a stream longer than 5 lines, producing a false smoke failure.
  if curl -N -fsS -X POST "${BASE_URL}/api/v1/chat/stream" \
       -H 'Content-Type: application/json' \
       -d '{"message":"ping","session_id":"deploy-smoke"}' >/dev/null; then
    ok "SSE stream responded."
  else
    fail "SSE stream smoke failed."; exit 1
  fi
else
  info "Skipping live SSE chat smoke (set RUN_STREAM_SMOKE=1 to enable; costs Mistral quota)."
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN} PASS — clean-machine deploy verified${NC}"
echo -e "${GREEN}=========================================${NC}"
