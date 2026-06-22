#!/usr/bin/env bash
# Stand up an ISOLATED static-config rate-limiter stack — its own containers
# (rl-static-*), its own network (rl-static-net), and host port 8001 — so it
# never touches the dynamic stack (rl-*, port 8000). Both can run at once.
#
#   ./rl-shared-bake/static-up.sh
#   ./rl-shared-bake/static-run.sh
#   ./rl-shared-bake/static-down.sh
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root
HERE="rl-shared-bake"

GW_IMAGE="${GW_IMAGE:-mcpgateway/mcpgateway:rl-0.1.6}"
NET="rl-static-net"
PORT="${STATIC_PORT:-8001}"
REDIS_PW='rlTlsTest_pw_2026'      # pragma: allowlist secret
JWT='rl-e2e-jwt-secret-2026'      # pragma: allowlist secret  (must match static-run.sh)
CERTS="$PWD/tls-certs"
CONFIG="$PWD/$HERE/config-static.yaml"

echo "▶ STATIC stack — image=$GW_IMAGE  port=$PORT  config=config-static.yaml"
docker image inspect "$GW_IMAGE" >/dev/null 2>&1 || { echo "✗ image $GW_IMAGE not found (see $HERE/README.md)"; exit 1; }
[ -f "$CONFIG" ] || { echo "✗ $CONFIG missing"; exit 1; }
[ -f "$CERTS/ca.crt" ] && [ -f "$CERTS/ca.key" ] || { echo "✗ tls-certs/ca.{crt,key} missing"; exit 1; }

# Dedicated server cert with SAN rl-static-redis — does NOT touch the dynamic
# stack's redis.crt, so the two stacks never fight over the cert file.
if [ ! -f "$CERTS/redis-static.crt" ] || ! openssl x509 -in "$CERTS/redis-static.crt" -noout -ext subjectAltName 2>/dev/null | grep -q "rl-static-redis"; then
  echo "▶ issuing redis-static cert (SAN rl-static-redis/localhost/127.0.0.1)"
  openssl req -newkey rsa:2048 -nodes -keyout "$CERTS/redis-static.key" -subj "/CN=rl-static-redis" -out /tmp/redis_static.csr 2>/dev/null
  printf 'subjectAltName=DNS:localhost,DNS:rl-static-redis,DNS:host.docker.internal,IP:127.0.0.1\n' > /tmp/redis_static_san.ext
  openssl x509 -req -in /tmp/redis_static.csr -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" -CAcreateserial \
    -days 365 -sha256 -extfile /tmp/redis_static_san.ext -out "$CERTS/redis-static.crt" 2>/dev/null
  chmod 644 "$CERTS/redis-static.crt" "$CERTS/redis-static.key"
fi

docker network create "$NET" >/dev/null 2>&1 || true
echo "▶ (re)starting static backends (network-only — no host port clashes with the dynamic stack)"
docker rm -f rl-static-pg rl-static-redis rl-static-fast-time rl-static-gw >/dev/null 2>&1 || true
docker run -d --name rl-static-pg --network "$NET" \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mcp postgres:18 >/dev/null
docker run -d --name rl-static-redis --network "$NET" -v "$CERTS:/certs:ro" redis:latest \
  redis-server --port 0 --tls-port 6379 \
  --tls-cert-file /certs/redis-static.crt --tls-key-file /certs/redis-static.key \
  --tls-ca-cert-file /certs/ca.crt --tls-auth-clients no --requirepass "$REDIS_PW" >/dev/null
docker run -d --name rl-static-fast-time --network "$NET" ghcr.io/ibm/fast-time-server:latest -transport sse >/dev/null

echo "▶ starting static gateway (2 gunicorn workers, port $PORT)"
docker run -d --name rl-static-gw --network "$NET" -p "${PORT}:8000" \
  -v "$CONFIG:/app/plugins/config.yaml:ro" -v "$CERTS:/certs:ro" \
  -e HOST=0.0.0.0 -e PORT=8000 \
  -e DATABASE_URL="postgresql+psycopg://postgres:postgres@rl-static-pg:5432/mcp" \
  -e REDIS_URL="rediss://:${REDIS_PW}@rl-static-redis:6379/0" \
  -e REDIS_SSL=true -e REDIS_SSL_CA_CERTS="/certs/ca.crt" \
  -e RATELIMITER_REDIS_SSL_CA_CERTS="/certs/ca.crt" \
  -e CACHE_TYPE=redis -e AUTH_REQUIRED=false \
  -e RATE_LIMITING_ENABLED=false -e RATE_LIMITING_REDIS_ENABLED=false \
  -e PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false -e LOG_LEVEL=INFO \
  -e MCPGATEWAY_UI_ENABLED=true -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e SSRF_ALLOW_PRIVATE_NETWORKS=true -e SSRF_ALLOW_LOCALHOST=true \
  -e PLUGINS_ENABLED=true -e PLUGINS_CONFIG_FILE=plugins/config.yaml \
  -e JWT_SECRET_KEY="$JWT" -e GUNICORN_WORKERS=2 -e GUNICORN_PRELOAD_APP=true \
  "$GW_IMAGE" >/dev/null

echo -n "▶ waiting for static gateway health "
for _ in $(seq 1 60); do
  if curl -fsS -m 3 "http://localhost:${PORT}/health" >/dev/null 2>&1; then echo "ok"; break; fi
  docker ps --format '{{.Names}}' | grep -q '^rl-static-gw$' || { echo "✗ gateway exited"; docker logs rl-static-gw 2>&1 | tail -25; exit 1; }
  echo -n "."; sleep 2
done

# register fast-time + a virtual server so the tool is callable at /servers/{id}/mcp
echo "▶ registering fast-time-sse + virtual server"
TOKEN=$(docker exec rl-static-gw python3 -m mcpgateway.utils.create_jwt_token \
          --username admin@example.com --exp 10080 --secret "$JWT" 2>/dev/null)
curl -sS -m 30 -X POST "http://localhost:${PORT}/gateways" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"fast-time-sse","url":"http://rl-static-fast-time:8080/sse","transport":"SSE"}' >/dev/null 2>&1 || true
sleep 3
FT_IDS=$(curl -fsS -m 5 -H "Authorization: Bearer $TOKEN" "http://localhost:${PORT}/tools" 2>/dev/null \
  | python3 -c "import sys,json; print(json.dumps([t['id'] for t in json.load(sys.stdin) if 'fast-time' in (t.get('name') or '').lower()]))" 2>/dev/null || echo "[]")
curl -sS -m 15 -X POST "http://localhost:${PORT}/servers" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"server\":{\"name\":\"fast-time\",\"description\":\"static stack\",\"associated_tools\":$FT_IDS}}" >/dev/null 2>&1 || true
echo "▶ fast-time tools: $FT_IDS"

echo
echo "✅ STATIC stack ready ($GW_IMAGE) at http://localhost:${PORT} — by_user/by_tenant/by_tool all 3/m."
echo "   run the test:   ./$HERE/static-run.sh"
echo "   tear down:      ./$HERE/static-down.sh"
