#!/usr/bin/env bash
# Multi-instance primary-worker e2e: scale the standard compose gateway to 2
# replicas with the redis election backend and assert exactly one primary is
# elected across the containers (a per-container file lock cannot do this).
#
# Observability: the marker plugin RPUSHes <host>:<pid> to a shared Redis list
# only when is_primary_worker() is true, so we count across containers via Redis.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="mcpgw-pw-e2e"
COMPOSE="docker compose -p $PROJECT -f docker-compose.yml"
KEY="mcpgw:primary_worker:e2e:markers"
REPLICAS="${REPLICAS:-2}"

# Preconditions.
command -v docker >/dev/null 2>&1 || { echo "SKIP: docker not found"; exit 0; }
docker compose version >/dev/null 2>&1 || { echo "SKIP: 'docker compose' not available"; exit 0; }
docker image inspect "${IMAGE_LOCAL:-mcpgateway/mcpgateway:latest}" >/dev/null 2>&1 \
  || { echo "SKIP: local image not found — build it from this branch with 'make docker' first"; exit 0; }
# NOTE: the gateway code is baked into the image (only ./plugins is mounted), so
# the image MUST be rebuilt from the current branch ('make docker') for the
# election backend to be present.

cleanup() { $COMPOSE down --remove-orphans -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "▶ bringing up redis and clearing the marker key"
$COMPOSE up -d redis >/dev/null
for _ in $(seq 1 30); do
  [ "$($COMPOSE exec -T redis redis-cli ping 2>/dev/null | tr -d '\r')" = "PONG" ] && break
  sleep 1
done
$COMPOSE exec -T redis redis-cli DEL "$KEY" >/dev/null

echo "▶ starting $REPLICAS gateway replicas (backend=redis)"
PRIMARY_WORKER_ELECTION_BACKEND=redis \
PLUGINS_CONFIG_FILE=plugins/primary_worker_multiinstance_config.yaml \
  $COMPOSE up -d --scale gateway="$REPLICAS" gateway >/dev/null

echo "▶ waiting for $REPLICAS healthy gateways ..."
ready=0
for _ in $(seq 1 120); do
  healthy=$($COMPOSE ps gateway 2>/dev/null | grep -c "healthy" || true)
  if [ "$healthy" -ge "$REPLICAS" ]; then ready=1; break; fi
  sleep 2
done
[ "$ready" = 1 ] || { echo "❌ gateways did not become healthy in time"; $COMPOSE ps gateway; exit 1; }
sleep 3  # settle: ensure every replica finished plugin initialize()

n=$($COMPOSE exec -T redis redis-cli LLEN "$KEY" 2>/dev/null | tr -d '\r')
echo "▶ primaries across $REPLICAS instances: $n"
$COMPOSE exec -T redis redis-cli LRANGE "$KEY" 0 -1 2>/dev/null | sed 's/^/    /'

[ "$n" = "1" ] || { echo "❌ FAIL: expected exactly 1 primary across $REPLICAS instances, got $n"; exit 1; }
echo "✅ PASS: exactly one primary elected across $REPLICAS instances (cross-instance election works)"
