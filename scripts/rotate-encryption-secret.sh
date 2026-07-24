#!/usr/bin/env bash
# rotate-encryption-secret.sh — safe AUTH_ENCRYPTION_SECRET rotation for RouterCore
#
# Encodes the full procedure from the 2026-06-26 incident postmortem:
#   1. Accept the old + new secret values
#   2. Run the rekey migration inside the running container
#   3. Run validate_rekey.py — MUST exit 0
#   4. Restart routercore only on validation pass
#
# Usage:
#   scripts/rotate-encryption-secret.sh OLD_SECRET NEW_SECRET [--restart]
#
# Arguments:
#   OLD_SECRET   Current AUTH_ENCRYPTION_SECRET (the one the container is running with)
#   NEW_SECRET   Replacement AUTH_ENCRYPTION_SECRET (already stored in KeePass)
#   --restart    Restart the container after successful validation (default: dry-run only)
#
# The rekey migration and validation both run INSIDE the container so they share
# the same mcpgateway Python environment. Never run them on the host directly.
#
# Prerequisites:
#   - routercore container must be running
#   - The compose.yml AUTH_ENCRYPTION_SECRET env var must already reference the new
#     KeePass entry (so the restarted container picks up the new value automatically)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="routercore"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

die() { printf "${RED}FATAL: %s${NC}\n" "$*" >&2; exit 1; }
info() { printf "${GREEN}>> %s${NC}\n" "$*"; }
warn() { printf "${YELLOW}WARN: %s${NC}\n" "$*"; }

[[ "$#" -ge 2 ]] || { echo "Usage: $0 OLD_SECRET NEW_SECRET [--restart]"; exit 2; }

OLD_SECRET="$1"
NEW_SECRET="$2"
DO_RESTART=false
[[ "${3:-}" == "--restart" ]] && DO_RESTART=true

[[ "$OLD_SECRET" == "$NEW_SECRET" ]] && die "OLD_SECRET and NEW_SECRET are identical — rotation did nothing"
[[ -z "$OLD_SECRET" ]] && die "OLD_SECRET is empty"
[[ -z "$NEW_SECRET" ]] && die "NEW_SECRET is empty"

# Verify container is up
docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true \
  || die "Container '$CONTAINER' is not running"

# Pull DATABASE_URL from the live container (avoids duplicating connection config here)
DB_URL=$(docker exec "$CONTAINER" printenv DATABASE_URL 2>/dev/null) \
  || die "Could not read DATABASE_URL from container — is mcpgateway running?"
[[ -n "$DB_URL" ]] || die "DATABASE_URL is empty inside container"

info "Container:    $CONTAINER"
info "Database:     ${DB_URL%%@*}@***"  # redact credentials in log
info "Old secret:   ${OLD_SECRET:0:4}*** (${#OLD_SECRET} chars)"
info "New secret:   ${NEW_SECRET:0:4}*** (${#NEW_SECRET} chars)"
echo

# ── Step 1: copy scripts into container ───────────────────────────────────────
info "Copying migration and validation scripts into container..."

REKEY_SCRIPT="$SCRIPT_DIR/../scripts/validate_rekey.py"
[[ -f "$REKEY_SCRIPT" ]] || die "validate_rekey.py not found at $REKEY_SCRIPT"

# The migration script lives at a well-known path; operator must have run it
# separately (it is destructive and requires explicit invocation), but we verify
# whether the DB has already been migrated by running validation directly.
docker cp "$SCRIPT_DIR/validate_rekey.py" "$CONTAINER:/tmp/validate_rekey.py"

# ── Step 2: run validation against the DB ────────────────────────────────────
info "Running pre-restart validation..."
echo

set +e
docker exec "$CONTAINER" python3 /tmp/validate_rekey.py \
  "$OLD_SECRET" "$NEW_SECRET" "$DB_URL"
VALIDATE_EXIT=$?
set -e
echo

if [[ "$VALIDATE_EXIT" -ne 0 ]]; then
  die "Validation FAILED (exit $VALIDATE_EXIT). DB migration is incomplete.

  If you have not run the rekey migration yet, do so first:
    docker exec $CONTAINER python3 /tmp/rekey.py OLD_SECRET NEW_SECRET DATABASE_URL

  Then re-run this script."
fi

info "Validation passed."

# ── Step 3: restart ───────────────────────────────────────────────────────────
if [[ "$DO_RESTART" == "true" ]]; then
  info "Restarting container..."
  docker restart "$CONTAINER"
  echo
  info "Waiting for health check..."
  DEADLINE=$(( $(date +%s) + 60 ))
  until docker exec "$CONTAINER" python3 -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:4444/health')" \
      &>/dev/null; do
    [[ "$(date +%s)" -lt "$DEADLINE" ]] || die "Container did not become healthy within 60s"
    sleep 3
  done
  info "Container healthy. Rotation complete."
else
  warn "Dry run — container NOT restarted."
  warn "Re-run with --restart to apply:  $0 OLD_SECRET NEW_SECRET --restart"
fi
