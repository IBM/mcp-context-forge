#!/usr/bin/env bash
# Direct demonstration of the mechanism behind issue #4051.
#
# Three steps against the same stack that reproduce.sh uses:
#
#   1. Through PgBouncer (transaction pool, POOL_SIZE=2), take a Postgres
#      session-scoped advisory lock, then close the connection. PgBouncer
#      returns the backend to its pool.
#   2. Query pg_locks on Postgres directly. The lock is STILL HELD — the
#      pgbouncer "session" is gone but the server session on the backend
#      is still alive.
#   3. Open a fresh connection through PgBouncer and try to acquire the
#      SAME lock. Returns FALSE because the backend PgBouncer hands us is
#      the same one that still holds it.
#
# That "FALSE in step 3 even though no-one is actually doing anything" is
# what makes bootstrap_db.main() hang: the advisory-lock retry loop spins
# forever because the lock is orphaned on a backend no client owns.
#
# Requires:
#   - docker compose with the stack defined in
#     tests/integration/fixtures/transaction_pool/docker-compose.yml
#     (postgres + pgbouncer only; no gateway needed).

set -u

REPO_ROOT=$(git rev-parse --show-toplevel)
COMPOSE_FILE="${REPO_ROOT}/tests/integration/fixtures/transaction_pool/docker-compose.yml"
COMPOSE=(docker compose -f "${COMPOSE_FILE}")
LOCK_ID="${LOCK_ID:-42424242424242}"

log() { printf '[demo] %s\n' "$*"; }

PSQL_PGBOUNCER=("${COMPOSE[@]}" exec -T -e PGPASSWORD=reprosecret postgres
                psql -h pgbouncer -p 6432 -U postgres -d mcp -t -A)
PSQL_DIRECT=("${COMPOSE[@]}" exec -T -e PGPASSWORD=reprosecret postgres
             psql -h postgres -p 5432 -U postgres -d mcp -t -A)

log "clean slate"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

log "start postgres + pgbouncer"
"${COMPOSE[@]}" up -d --wait postgres pgbouncer

# Sanity: confirm both are reachable.
"${PSQL_DIRECT[@]}" -c "SELECT 1;" >/dev/null
"${PSQL_PGBOUNCER[@]}" -c "SELECT 1;" >/dev/null

echo
log "=== STEP 1: through PgBouncer, acquire advisory lock ${LOCK_ID}, then disconnect"
"${PSQL_PGBOUNCER[@]}" -c "SELECT pg_advisory_lock(${LOCK_ID});" >/dev/null
log "    done (pgbouncer-facing connection closed)"

echo
log "=== STEP 2: direct to Postgres, check pg_locks for any advisory lock"
# pg_locks splits a 64-bit advisory lock id across classid (high 32 bits) and
# objid (low 32 bits) — both columns are 32-bit OIDs, so we can't compare
# either column to the 64-bit LOCK_ID directly. Filtering by locktype is
# enough: no one else in this stack holds advisory locks.
direct_locks=$("${PSQL_DIRECT[@]}" -c \
    "SELECT pid::text||'|'||locktype||'|'||classid::text||'|'||objid::text||'|'||granted::text FROM pg_locks WHERE locktype='advisory';")
if [ -z "$direct_locks" ]; then
    log "    NO advisory lock found on Postgres — backend was fully reset. Bug not reproducible with this pgbouncer config."
    exit 1
fi
log "    lock still held at server level (classid<<32 | objid == ${LOCK_ID}):"
printf '      %s\n' "$direct_locks" | awk -F'|' '{printf "pid=%s type=%s classid=%s objid=%s granted=%s\n", $1,$2,$3,$4,$5}'

echo
log "=== STEP 3: from a DIFFERENT Postgres session (direct, bypass PgBouncer),"
log "           try to take the same advisory lock"
# Why direct, not through PgBouncer? Advisory locks are reentrant within the
# same session — so if PgBouncer happens to hand us the SAME server backend
# that took the lock in step 1, pg_try_advisory_lock returns TRUE (the lock
# is "already held by this session"). That's misleading. Connecting directly
# to Postgres guarantees a brand-new session, which is exactly the condition
# a new gateway pod hits when its Alembic tries to acquire the lock.
result=$("${PSQL_DIRECT[@]}" -c "SELECT pg_try_advisory_lock(${LOCK_ID});" | tr -d '[:space:]')
log "    pg_try_advisory_lock (from fresh session) -> ${result}"

# Bonus: try the pgbouncer side too, so readers see the reentrant-TRUE effect.
result_via_bouncer=$("${PSQL_PGBOUNCER[@]}" -c "SELECT pg_try_advisory_lock(${LOCK_ID});" | tr -d '[:space:]')
log "    pg_try_advisory_lock (via pgbouncer, may reuse same backend) -> ${result_via_bouncer}"

echo
case "$result" in
    f)
        log "RESULT: ORPHANED. The lock set in step 1 is held by a backend"
        log "        that no pgbouncer client still owns, and a different"
        log "        postgres session cannot acquire it. A new gateway pod"
        log "        taking this path would spin on pg_try_advisory_lock"
        log "        until the advisory_lock retry timeout fires — exactly"
        log "        the symptom described in issue #4051."
        log ""
        if [ "$result_via_bouncer" = "t" ]; then
            log "        (The pgbouncer-side TRUE above is reentrance — it landed"
            log "         on the same backend that still holds the lock. That's"
            log "         a PostgreSQL feature, not contradictory evidence.)"
            log ""
        fi
        log "        tear down with: ${COMPOSE[*]} down -v"
        exit 0
        ;;
    t)
        log "RESULT: lock was NOT orphaned. PgBouncer cleared it between"
        log "        clients (likely via DISCARD ALL on server_reset_query)."
        log "        The bug mechanism does not manifest in this config."
        exit 1
        ;;
    *)
        log "RESULT: unexpected psql output: '${result}'"
        exit 2
        ;;
esac
