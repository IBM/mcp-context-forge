#!/usr/bin/env bash
# Bring up the full rate-limiter TLS+AUTH e2e stack so the container test
# (tests/live_gateway/plugins/test_rate_limiter_binding_single_instance_tls_container.py)
# works right away via ./rl-shared-bake/run-e2e.sh.
#
# Idempotent: tears down and recreates the rl-* containers on each run.
#
#   ./rl-shared-bake/up.sh                       # gateway = mcpgateway/mcpgateway:rl-0.1.6 (shared-connection fix)
#   GW_IMAGE=mcpgateway/mcpgateway:base-0.1.4 ./rl-shared-bake/up.sh   # any other tag
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root
HERE="rl-shared-bake"

GW_IMAGE="${GW_IMAGE:-mcpgateway/mcpgateway:rl-0.1.6}"
NET="rl-net"
REDIS_PW='rlTlsTest_pw_2026'      # pragma: allowlist secret  (redis requirepass + URL token)
JWT='rl-e2e-jwt-secret-2026'      # pragma: allowlist secret  (must match run-e2e.sh)
CERTS="$PWD/tls-certs"
CONFIG="$PWD/$HERE/config.yaml"

echo "▶ gateway image: $GW_IMAGE"

# 0) sanity: image, config, CA present
docker image inspect "$GW_IMAGE" >/dev/null 2>&1 \
  || { echo "✗ image $GW_IMAGE not found — build it first (see $HERE/README.md)"; exit 1; }
[ -f "$CONFIG" ] || { echo "✗ $CONFIG missing"; exit 1; }
[ -f "$CERTS/ca.crt" ] && [ -f "$CERTS/ca.key" ] || { echo "✗ tls-certs/ca.{crt,key} missing"; exit 1; }

# 1) certs: ensure the redis server cert SAN covers the container name `rl-redis`
#    (the containerized gateway verifies the TLS cert by network name).
if ! openssl x509 -in "$CERTS/redis.crt" -noout -ext subjectAltName 2>/dev/null | grep -q "rl-redis"; then
  echo "▶ (re)issuing redis cert with SAN rl-redis/localhost/host.docker.internal/127.0.0.1"
  openssl req -newkey rsa:2048 -nodes -keyout "$CERTS/redis.key" -subj "/CN=rl-redis" -out /tmp/redis.csr 2>/dev/null
  printf 'subjectAltName=DNS:localhost,DNS:rl-redis,DNS:host.docker.internal,IP:127.0.0.1\n' > /tmp/redis_san.ext
  openssl x509 -req -in /tmp/redis.csr -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" -CAcreateserial \
    -days 365 -sha256 -extfile /tmp/redis_san.ext -out "$CERTS/redis.crt" 2>/dev/null
  chmod 644 "$CERTS/redis.crt" "$CERTS/redis.key"
fi

# 2) network + fresh backends
docker network create "$NET" >/dev/null 2>&1 || true
echo "▶ (re)starting backends: rl-pg, rl-redis (TLS+AUTH), rl-fast-time"
docker rm -f rl-pg rl-redis rl-fast-time rl-gw >/dev/null 2>&1 || true
docker run -d --name rl-pg --network "$NET" -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mcp postgres:18 >/dev/null
docker run -d --name rl-redis --network "$NET" -p 6379:6379 -v "$CERTS:/certs:ro" redis:latest \
  redis-server --port 0 --tls-port 6379 \
  --tls-cert-file /certs/redis.crt --tls-key-file /certs/redis.key \
  --tls-ca-cert-file /certs/ca.crt --tls-auth-clients no --requirepass "$REDIS_PW" >/dev/null
docker run -d --name rl-fast-time --network "$NET" ghcr.io/ibm/fast-time-server:latest -transport sse >/dev/null

# 3) gateway: baked image, 2 gunicorn workers, container-network addressing.
#    The non-obvious bits folded in here (vs the make-dev docstring):
#      - PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false  (main forces a first-login
#        password change → /admin/* 303-redirects and the test errors)
#      - LOG_LEVEL=INFO                              (surfaces the Rust
#        "opened redis connection (shared across N)" logs)
#      - REDIS_*/RATELIMITER_REDIS_SSL_CA_CERTS      (verify our self-signed CA)
#    Plugin `enforce` + the redis_ssl_ca_certs line live in the mounted config.
echo "▶ starting gateway (2 gunicorn workers)"
docker run -d --name rl-gw --network "$NET" -p 8000:8000 \
  -v "$CONFIG:/app/plugins/config.yaml:ro" \
  -v "$CERTS:/certs:ro" \
  -e HOST=0.0.0.0 -e PORT=8000 \
  -e DATABASE_URL="postgresql+psycopg://postgres:postgres@rl-pg:5432/mcp" \
  -e REDIS_URL="rediss://:${REDIS_PW}@rl-redis:6379/0" \
  -e REDIS_SSL=true -e REDIS_SSL_CA_CERTS="/certs/ca.crt" \
  -e RATELIMITER_REDIS_SSL_CA_CERTS="/certs/ca.crt" \
  -e CACHE_TYPE=redis -e AUTH_REQUIRED=false \
  -e RATE_LIMITING_ENABLED=false -e RATE_LIMITING_REDIS_ENABLED=false \
  -e PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false \
  -e LOG_LEVEL=INFO \
  -e MCPGATEWAY_UI_ENABLED=true -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e SSRF_ALLOW_PRIVATE_NETWORKS=true -e SSRF_ALLOW_LOCALHOST=true \
  -e PLUGINS_ENABLED=true -e PLUGINS_CONFIG_FILE=plugins/config.yaml \
  -e JWT_SECRET_KEY="$JWT" \
  -e GUNICORN_WORKERS=2 -e GUNICORN_PRELOAD_APP=true \
  "$GW_IMAGE" >/dev/null

echo -n "▶ waiting for gateway health "
for _ in $(seq 1 60); do
  if curl -fsS -m 3 http://localhost:8000/health >/dev/null 2>&1; then echo "ok"; break; fi
  docker ps --format '{{.Names}}' | grep -q '^rl-gw$' || { echo "✗ gateway exited"; docker logs rl-gw 2>&1 | tail -25; exit 1; }
  echo -n "."; sleep 2
done

# 4) pre-register fast-time at its container-network URL so the test's session
#    fixture finds it already present and skips the host-IP path.
echo "▶ registering fast-time-sse -> http://rl-fast-time:8080/sse"
TOKEN=$(docker exec rl-gw python3 -m mcpgateway.utils.create_jwt_token \
          --username admin@example.com --exp 10080 --secret "$JWT" 2>/dev/null)
curl -sS -m 30 -X POST http://localhost:8000/gateways \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"fast-time-sse","url":"http://rl-fast-time:8080/sse","transport":"SSE"}' >/dev/null 2>&1 || true
sleep 3
TOOLS=$(curl -fsS -m 5 -H "Authorization: Bearer $TOKEN" http://localhost:8000/tools 2>/dev/null \
        | python3 -c "import sys,json; print(sum('get-system-time' in t.get('name','') for t in json.load(sys.stdin)))" 2>/dev/null || echo 0)
echo "▶ fast-time tools discovered: $TOOLS"

echo
echo "✅ stack ready ($GW_IMAGE) — RateLimiterPlugin=enforce, 2 workers, TLS+AUTH Redis."
echo "   run the test:   ./$HERE/run-e2e.sh"
echo "   watch sharing:  docker logs -f rl-gw 2>&1 | grep --line-buffered 'opened redis connection'"
echo "   tear down:      ./$HERE/down.sh"
