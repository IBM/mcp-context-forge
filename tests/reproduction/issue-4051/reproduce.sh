#!/usr/bin/env bash
# Reproduces issue #4051.
#
# Brings up postgres + pgbouncer (transaction pool) + N gateway replicas and
# reports how many of them reached "Database ready" within TIMEOUT_SECONDS.
# When the bug is present the first replica finishes bootstrap; the rest hang
# at Alembic's advisory-lock acquisition.

set -u

REPO_ROOT=$(git rev-parse --show-toplevel)
COMPOSE_FILE="${REPO_ROOT}/tests/integration/fixtures/transaction_pool/docker-compose.yml"
COMPOSE=(docker compose -f "${COMPOSE_FILE}")
REPLICAS="${REPLICAS:-3}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"

# bootstrap_db.main() emits exactly one of these per replica on success. The
# match is scoped to the bootstrap_db logger so it does NOT collide with
# db_isready's "Database ready after X.XXs" probe messages.
READY_PATTERN='"name": "mcpgateway.bootstrap_db".*"message": "Database ready"'

log() { printf '[repro] %s\n' "$*"; }

count_ready() {
    "${COMPOSE[@]}" logs --no-log-prefix gateway 2>/dev/null \
        | grep -cE "${READY_PATTERN}" || true
}

log "clean slate (docker compose down -v)"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

log "start postgres + pgbouncer (healthchecks block until ready)"
"${COMPOSE[@]}" up -d postgres pgbouncer

log "scale gateway to ${REPLICAS}"
"${COMPOSE[@]}" up -d --scale gateway="${REPLICAS}" --no-recreate gateway

log "waiting up to ${TIMEOUT_SECONDS}s for all replicas to log 'Database ready'..."
elapsed=0
ready=0
while (( elapsed < TIMEOUT_SECONDS )); do
    ready=$(count_ready)
    running=$("${COMPOSE[@]}" ps -q gateway | wc -l | tr -d ' ')
    printf '  t=%4ds  ready=%s/%s  running=%s/%s\n' "$elapsed" "$ready" "$REPLICAS" "$running" "$REPLICAS"
    if (( ready >= REPLICAS )); then break; fi
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

echo
echo "=============== gateway replica status ==============="
"${COMPOSE[@]}" ps gateway

echo
echo "=============== advisory locks on postgres ==============="
"${COMPOSE[@]}" exec -T postgres psql -U postgres -d mcp -c \
    "SELECT locktype, mode, pid, granted, objid, classid FROM pg_locks WHERE locktype='advisory';" \
    || true

echo
echo "=============== active backends on postgres ==============="
"${COMPOSE[@]}" exec -T postgres psql -U postgres -d mcp -c \
    "SELECT pid, application_name, state, wait_event_type, wait_event, left(query, 80) AS query FROM pg_stat_activity WHERE datname='mcp';" \
    || true

echo
echo "=============== last 40 log lines per replica ==============="
for cid in $("${COMPOSE[@]}" ps -q gateway); do
    name=$(docker inspect --format '{{.Name}}' "$cid" | sed 's#^/##')
    echo "----- $name -----"
    docker logs --tail 40 "$cid" 2>&1 || true
done

echo
if (( ready >= REPLICAS )); then
    log "RESULT: all ${REPLICAS} replicas reached 'Database ready' (BUG NOT REPRODUCED)"
    exit 0
else
    log "RESULT: only ${ready}/${REPLICAS} replicas reached 'Database ready' (BUG REPRODUCED)"
    log "stack left running for inspection. tear down with:"
    log "  ${COMPOSE[*]} down -v"
    exit 1
fi
