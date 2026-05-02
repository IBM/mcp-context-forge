# TLS Redis smoke test

Local end-to-end test that exercises the cpex-rate-limiter plugin's TLS
support against a real TLS-enabled Redis. Mirrors what AWS ElastiCache
with in-transit encryption looks like operationally — server-side TLS,
client-side handshake against a CA in the OS trust store.

The stack reuses `docker-compose.yml` and overrides only what's needed
to swap plain Redis for a TLS Redis (see `docker-compose-tls-redis.yml`).

## What you're testing

```
host                      docker compose stack
─────                     ─────────────────────────────
                          ┌─ nginx :8080 ──────────────────┐
curl POST                 │                                │
/v1/tools/plugin_bindings │  gateway × 3 replicas          │
   ───────────────────►   │  (mcpgateway-tls-test:local)   │
                          │     ─ rate_limiter plugin      │
                          │       built from PR #74        │
                          │     ─ /etc/pki/tls trust store │
                          │       contains test CA         │
                          │                                │
                          │  rediss://redis:6390/0         │
                          │     │                          │
                          │     ▼  TLS handshake           │
                          │  ┌─ redis:7 ──────┐            │
                          │  │ --tls-port 6390│            │
                          │  │ cert signed by │            │
                          │  │ test CA        │            │
                          │  └────────────────┘            │
                          └────────────────────────────────┘
```

## Prerequisites

- Docker / Docker Compose (v2+)
- The cpex-plugins repo checked out at `../cpex-plugins` relative to
  this repo, on the branch with PR #74's TLS support
  (`fix/rate-limiter-tls-support-and-wipe-on-disable`).
- The base mcpgateway image. Either pull it or build it once via
  `make docker-prod` from this repo's root.

## One-time setup

### 1. Generate self-signed certs

```bash
./tls-test/gen-certs.sh
```

Writes `tls-certs/{ca.crt,ca.key,redis.crt,redis.key}`. Run again any
time you want to rotate them.

### 2. Build the cpex-rate-limiter wheel from PR #74

The wheel build is decoupled from the gateway image build so you can
iterate on either side independently. Run it once now (and again any
time you change rate_limiter source):

```bash
mkdir -p tls-test/wheels

# Build a manylinux wheel from the local cpex-plugins checkout. Uses
# maturin's official Docker image so the wheel matches glibc / abi3
# expectations of the gateway base image.
docker run --rm \
    -v ../cpex-plugins:/io \
    -v "$PWD/tls-test/wheels":/out \
    ghcr.io/pyo3/maturin:latest \
    build --release --manylinux 2_28 \
        --manifest-path /io/plugins/rust/python-package/rate_limiter/Cargo.toml \
        --out /out
```

Outputs e.g. `tls-test/wheels/cpex_rate_limiter-0.0.6-cp311-abi3-manylinux_2_28_x86_64.whl`.

### 3. Build the derivative gateway image

```bash
docker build \
    -f tls-test/Containerfile.tls-gateway \
    -t mcpgateway-tls-test:local \
    .
```

Build context is the `mcp-context-forge` repo root (current dir). The
Containerfile copies `tls-certs/ca.crt` into the trust store, runs
`update-ca-trust extract`, and force-reinstalls the wheel from
`tls-test/wheels/`. Single stage, ~10 lines — fast since we're only
adding two layers on top of `mcpgateway/mcpgateway:latest`.

## Run the stack

```bash
docker compose -p tls-test \
    -f docker-compose.yml \
    -f docker-compose-tls-redis.yml \
    up -d --no-build
```

`--no-build` is **important**: without it, compose tries to rebuild the
gateway image from `Containerfile.lite` (which the base compose
specifies), which would discard our derivative image.

Wait for healthchecks (~30s):

```bash
docker compose -p tls-test ps
```

All services should be `healthy`.

## Smoke test

### Verify the plugin loaded (no silent-skip regression)

```bash
docker logs tls-test-gateway-1 2>&1 | grep -iE "RateLimiter|plugin"
```

Expect to see:

```
INFO  rate limiter initialized: backend=redis
```

Must **not** see (this is the wo-tracker #68217 signature):

```
ERROR  Rust rate limiter: Redis backend init failed:
       can't connect with TLS, the feature is not enabled
ERROR  Failed to load plugin RateLimiterPlugin: ... InvalidClientConfig
```

### Verify TLS connection from the gateway side

```bash
docker exec tls-test-gateway-1 \
    /app/.venv/bin/python - <<'EOF'
import asyncio, redis.asyncio
async def main():
    r = redis.asyncio.from_url("rediss://redis:6390/0")
    print("PING:", await r.ping())
    await r.aclose()
asyncio.run(main())
EOF
```

Expect: `PING: True`. Confirms the host OS trust store has our CA and
the rustls path on the plugin will work too (same trust store).

### Send a burst that should trigger rate limiting

(Use whatever helper you usually run; the existing
`locustfile_rate_limiter_redis_capacity.py` works against this stack
once you point `JWT_SECRET_KEY` and `MCP_SERVER_ID` at the test
deployment. See the main repo's loadtest README for details.)

Inspect Redis directly to see counters appear:

```bash
docker exec tls-test-redis-1 \
    redis-cli --tls -p 6390 \
        --cacert /certs/ca.crt \
        --cert /certs/redis.crt \
        --key /certs/redis.key \
        --insecure \
        --scan --pattern 'rl:*'
```

(`--insecure` here just skips hostname verification on the redis-cli
side; the cert chain itself is still verified.)

## Tear down

```bash
docker compose -p tls-test \
    -f docker-compose.yml \
    -f docker-compose-tls-redis.yml \
    down -v
```

`-v` drops the named volumes (postgres data, redis insights, etc.) so
the next `up` starts clean.

## Known limitations / things to flag

- The derivative image bakes in the test CA — only use this image
  for local testing, never push it.
- `tls-certs/` is local-only; add to `.gitignore` if not already.
- Self-signed certs expire after 365 days. Rerun `gen-certs.sh` when
  expiry hits and rebuild the gateway image (the CA is baked in).
- The wheel built inside `wheelbuilder` is `cp311-abi3-manylinux_2_28`;
  if the gateway image's glibc or Python version drifts from that,
  the wheel install will fail. Adjust the `--manylinux` flag in
  `Containerfile.tls-gateway` if needed.

## Why this exists

cpex-rate-limiter PR #74 enables TLS in the redis crate so operators
can point the plugin at managed Redis with in-transit encryption. The
unit + integration test suites can verify URL parsing and reach the
network layer, but **the only way to prove the rustls handshake
itself works end-to-end** is against a real TLS Redis. This stack
provides one in ~3 commands.
