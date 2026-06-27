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

GW_IMAGE="${GW_IMAGE:-mcpgateway/mcpgateway:latest}"
NET="rl-static-net"
PORT="${STATIC_PORT:-8001}"
STATIC_LIMIT="${STATIC_LIMIT:-3}"
STATIC_RATE_UNIT="${STATIC_RATE_UNIT:-m}"
STATIC_RATE_LIMIT="${STATIC_RATE_LIMIT:-${STATIC_LIMIT}/${STATIC_RATE_UNIT}}"
REDIS_PW='rlTlsTest_pw_2026'      # pragma: allowlist secret
JWT='rl-e2e-jwt-secret-2026'      # pragma: allowlist secret  (must match static-run.sh)
PG_PASSWORD='postgres'            # pragma: allowlist secret
CERTS="$PWD/tls-certs"
CONFIG="$PWD/$HERE/config-static.yaml"
STATIC_USE_IMAGE_PLUGIN_CONFIG="${STATIC_USE_IMAGE_PLUGIN_CONFIG:-0}"
STATIC_GATEWAY_SSL="${STATIC_GATEWAY_SSL:-1}"
if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
  BASE_URL="http://localhost:${PORT}"
else
  BASE_URL="https://localhost:${PORT}"
fi
GATEWAY_REDIS_URL="${GATEWAY_REDIS_URL:-rediss://:${REDIS_PW}@rl-static-redis:6379/0}"
PLUGIN_REDIS_URL="${PLUGIN_REDIS_URL:-$GATEWAY_REDIS_URL}"
GATEWAY_REDIS_SSL_CA_CERTS="${GATEWAY_REDIS_SSL_CA_CERTS:-/certs/ca.crt}"
PLUGIN_REDIS_SSL_CA_CERTS="${PLUGIN_REDIS_SSL_CA_CERTS:-/certs/ca.crt}"
STATIC_REQUIRE_READY="${STATIC_REQUIRE_READY:-1}"
STATIC_GUNICORN_WORKERS="${STATIC_GUNICORN_WORKERS:-2}"
STATIC_GUNICORN_PRELOAD_APP="${STATIC_GUNICORN_PRELOAD_APP:-true}"
STATIC_GATEWAY_RATE_LIMITING_ENABLED="${STATIC_GATEWAY_RATE_LIMITING_ENABLED:-false}"
STATIC_GATEWAY_RATE_LIMITING_REDIS_ENABLED="${STATIC_GATEWAY_RATE_LIMITING_REDIS_ENABLED:-false}"
STATIC_DIRECT_PROXY_ENABLED="${STATIC_DIRECT_PROXY_ENABLED:-true}"

curl_gateway() {
  if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
    curl "$@"
  else
    curl --cacert "$CERTS/ca.crt" "$@"
  fi
}

echo "▶ STATIC stack — image=$GW_IMAGE  port=$PORT  config=config-static.yaml  rate=$STATIC_RATE_LIMIT"
docker image inspect "$GW_IMAGE" >/dev/null 2>&1 || { echo "✗ image $GW_IMAGE not found; build/tag it first or set GW_IMAGE=<image>"; exit 1; }
if [ "$STATIC_USE_IMAGE_PLUGIN_CONFIG" != "1" ]; then
  [ -f "$CONFIG" ] || { echo "✗ $CONFIG missing"; exit 1; }
fi
mkdir -p "$CERTS"
CA_REGENERATED=0
if [ ! -f "$CERTS/ca.crt" ] || [ ! -f "$CERTS/ca.key" ] || ! openssl x509 -in "$CERTS/ca.crt" -noout -text 2>/dev/null | grep -q "Certificate Sign"; then
  echo "▶ issuing static test CA"
  rm -f "$CERTS/redis-static.crt" "$CERTS/redis-static.key" "$CERTS/gateway-static.crt" "$CERTS/gateway-static.key"
  openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
    -keyout "$CERTS/ca.key" -out "$CERTS/ca.crt" \
    -subj "/CN=rl-static-test-ca" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" 2>/dev/null
  chmod 644 "$CERTS/ca.crt" "$CERTS/ca.key"
  CA_REGENERATED=1
fi

# Dedicated server cert with SAN rl-static-redis — does NOT touch the dynamic
# stack's redis.crt, so the two stacks never fight over the cert file.
if [ "$CA_REGENERATED" = "1" ] || [ ! -f "$CERTS/redis-static.crt" ] || ! openssl x509 -in "$CERTS/redis-static.crt" -noout -ext subjectAltName 2>/dev/null | grep -q "rl-static-redis"; then
  echo "▶ issuing redis-static cert (SAN rl-static-redis/localhost/127.0.0.1)"
  openssl req -newkey rsa:2048 -nodes -keyout "$CERTS/redis-static.key" -subj "/CN=rl-static-redis" -out /tmp/redis_static.csr 2>/dev/null
  printf 'subjectAltName=DNS:localhost,DNS:rl-static-redis,DNS:host.docker.internal,IP:127.0.0.1\n' > /tmp/redis_static_san.ext
  openssl x509 -req -in /tmp/redis_static.csr -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" -CAcreateserial \
    -days 365 -sha256 -extfile /tmp/redis_static_san.ext -out "$CERTS/redis-static.crt" 2>/dev/null
  chmod 644 "$CERTS/redis-static.crt" "$CERTS/redis-static.key"
fi

# Dedicated gateway cert for the host-facing HTTPS endpoint.
if [ "$CA_REGENERATED" = "1" ] || [ ! -f "$CERTS/gateway-static.crt" ] || ! openssl x509 -in "$CERTS/gateway-static.crt" -noout -ext subjectAltName 2>/dev/null | grep -q "DNS:localhost"; then
  echo "▶ issuing gateway-static cert (SAN localhost/rl-static-gw/127.0.0.1)"
  openssl req -newkey rsa:2048 -nodes -keyout "$CERTS/gateway-static.key" -subj "/CN=localhost" -out /tmp/gateway_static.csr 2>/dev/null
  printf 'subjectAltName=DNS:localhost,DNS:rl-static-gw,DNS:host.docker.internal,IP:127.0.0.1\n' > /tmp/gateway_static_san.ext
  openssl x509 -req -in /tmp/gateway_static.csr -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" -CAcreateserial \
    -days 365 -sha256 -extfile /tmp/gateway_static_san.ext -out "$CERTS/gateway-static.crt" 2>/dev/null
  chmod 644 "$CERTS/gateway-static.crt" "$CERTS/gateway-static.key"
fi

docker network create "$NET" >/dev/null 2>&1 || true
echo "▶ (re)starting static backends (network-only — no host port clashes with the dynamic stack)"
docker rm -f rl-static-pg rl-static-redis rl-static-fast-time rl-static-gw >/dev/null 2>&1 || true
docker run -d --name rl-static-pg --network "$NET" \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB=mcp postgres:18 >/dev/null
docker run -d --name rl-static-redis --network "$NET" -v "$CERTS:/certs:ro" redis:latest \
  redis-server --port 0 --tls-port 6379 \
  --tls-cert-file /certs/redis-static.crt --tls-key-file /certs/redis-static.key \
  --tls-ca-cert-file /certs/ca.crt --tls-auth-clients no --requirepass "$REDIS_PW" >/dev/null
docker run -d --name rl-static-fast-time --network "$NET" ghcr.io/ibm/fast-time-server:latest -transport sse >/dev/null

if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
  echo "▶ starting static gateway (${STATIC_GUNICORN_WORKERS} gunicorn workers, HTTP port $PORT, auth required)"
else
  echo "▶ starting static gateway (${STATIC_GUNICORN_WORKERS} gunicorn workers, HTTPS port $PORT, auth required)"
fi
echo "▶ gateway Redis URL: $GATEWAY_REDIS_URL"
echo "▶ plugin  Redis URL: $PLUGIN_REDIS_URL"
if [ "$STATIC_USE_IMAGE_PLUGIN_CONFIG" = "1" ]; then
  echo "▶ plugin config: using image-baked /app/plugins/config.yaml"
  CONFIG_MOUNT_ARGS=(-v "$CERTS:/certs:ro")
else
  echo "▶ plugin config: mounting $CONFIG"
  CONFIG_MOUNT_ARGS=(-v "$CONFIG:/app/plugins/config.yaml:ro" -v "$CERTS:/certs:ro")
fi
docker run -d --name rl-static-gw --network "$NET" -p "${PORT}:8000" \
  "${CONFIG_MOUNT_ARGS[@]}" \
  -e HOST=0.0.0.0 -e PORT=8000 \
  -e SSL="$([ "$STATIC_GATEWAY_SSL" = "0" ] && echo false || echo true)" -e CERT_FILE=/certs/gateway-static.crt -e KEY_FILE=/certs/gateway-static.key \
  -e DATABASE_URL="postgresql+psycopg://postgres:${PG_PASSWORD}@rl-static-pg:5432/mcp" \
  -e REDIS_URL="$GATEWAY_REDIS_URL" \
  -e RATELIMITER_REDIS_URL="$PLUGIN_REDIS_URL" \
  -e REDIS_SSL=true -e REDIS_SSL_CA_CERTS="$GATEWAY_REDIS_SSL_CA_CERTS" \
  -e RATELIMITER_REDIS_SSL_CA_CERTS="$PLUGIN_REDIS_SSL_CA_CERTS" \
  -e STATIC_RATE_LIMIT="$STATIC_RATE_LIMIT" \
  -e CACHE_TYPE=redis -e AUTH_REQUIRED=true \
  -e RATE_LIMITING_ENABLED="$STATIC_GATEWAY_RATE_LIMITING_ENABLED" -e RATE_LIMITING_REDIS_ENABLED="$STATIC_GATEWAY_RATE_LIMITING_REDIS_ENABLED" \
  -e PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false -e LOG_LEVEL=INFO \
  -e MCPGATEWAY_DIRECT_PROXY_ENABLED="$STATIC_DIRECT_PROXY_ENABLED" \
  -e MCPGATEWAY_UI_ENABLED=true -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e SSRF_ALLOW_PRIVATE_NETWORKS=true -e SSRF_ALLOW_LOCALHOST=true \
  -e PLUGINS_ENABLED=true -e PLUGINS_CONFIG_FILE=plugins/config.yaml \
  -e JWT_SECRET_KEY="$JWT" -e GUNICORN_WORKERS="$STATIC_GUNICORN_WORKERS" -e GUNICORN_PRELOAD_APP="$STATIC_GUNICORN_PRELOAD_APP" \
  "$GW_IMAGE" >/dev/null

echo -n "▶ waiting for static gateway health "
READY=0
for _ in $(seq 1 "${STATIC_READY_ATTEMPTS:-60}"); do
  if curl_gateway -fsS -m 3 "${BASE_URL}/ready" >/dev/null 2>&1; then echo "ok"; READY=1; break; fi
  docker ps --format '{{.Names}}' | grep -q '^rl-static-gw$' || { echo "✗ gateway exited"; docker logs rl-static-gw 2>&1 | tail -25; exit 1; }
  echo -n "."; sleep 2
done
if [ "$READY" != "1" ]; then
  echo
  echo "✗ gateway /ready did not become ready; gateway-level Redis may be failing"
  curl -sS -m 3 -k "${BASE_URL}/ready" || true
  echo
  docker logs rl-static-gw 2>&1 | tail -50
  if [ "$STATIC_REQUIRE_READY" != "0" ]; then
    exit 1
  fi
  echo "▶ continuing because STATIC_REQUIRE_READY=0"
fi

# register fast-time + a virtual server so the tool is callable at /servers/{id}/mcp
echo "▶ registering fast-time-sse + virtual server"
TOKEN=$(docker exec rl-static-gw python3 -m mcpgateway.utils.create_jwt_token \
          --username admin@example.com --admin --exp 10080 --secret "$JWT" 2>/dev/null)
curl_gateway -sS -m 30 -X POST "${BASE_URL}/gateways" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"fast-time-sse","url":"http://rl-static-fast-time:8080/sse","transport":"SSE"}' >/dev/null 2>&1 || true
sleep 3
FT_IDS=$(curl_gateway -fsS -m 5 -H "Authorization: Bearer $TOKEN" "${BASE_URL}/tools" 2>/dev/null \
  | python3 -c "import sys,json; print(json.dumps([t['id'] for t in json.load(sys.stdin) if 'fast-time' in (t.get('name') or '').lower()]))" 2>/dev/null || echo "[]")
curl_gateway -sS -m 15 -X POST "${BASE_URL}/servers" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"server\":{\"name\":\"fast-time\",\"description\":\"static stack\",\"associated_tools\":$FT_IDS}}" >/dev/null 2>&1 || true
echo "▶ fast-time tools: $FT_IDS"

echo
if [ "$STATIC_GATEWAY_SSL" = "0" ]; then
  echo "✅ STATIC stack ready ($GW_IMAGE) at ${BASE_URL} — auth required, HTTP gateway, by_user/by_tenant/by_tool all ${STATIC_RATE_LIMIT}."
else
  echo "✅ STATIC stack ready ($GW_IMAGE) at ${BASE_URL} — auth required, TLS enabled, by_user/by_tenant/by_tool all ${STATIC_RATE_LIMIT}."
fi
echo "   run the test:   ./$HERE/static-run.sh"
echo "   tear down:      ./$HERE/static-down.sh"
