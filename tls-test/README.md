# TLS Redis smoke test

Verifies the cpex-rate-limiter plugin works end-to-end against a TLS-enabled
Redis (`rediss://...`) without modifying the host's OS trust store. Mirrors
what managed Redis with in-transit encryption (AWS ElastiCache, Redis Cloud,
IBM Cloud Databases for Redis) looks like operationally — server-side TLS,
client-side handshake against a CA in the trust store.

If you just want to verify TLS support works end-to-end on the current
gateway main, follow the steps in order — every command is copy-pasteable.
Architecture, known limitations, and the rationale for the stack are in
the sections after the steps.

## Prerequisites

- Docker + Docker Compose v2+
- `git`, `bash`, an `openssl` CLI on PATH
- ~6 GB of free disk for images, ~3 GB of free RAM for the running stack

That's it — no Python, Rust, or maturin on the host. The TLS-enabled
cpex-rate-limiter wheel is pulled from PyPI by the base image.

## Step 0 — clone the repo and check out this branch

```bash
mkdir -p ~/work && cd ~/work
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge
git checkout test/tls-redis-smoke-test
```

If you already have the repo somewhere else, just make sure it's on
`test/tls-redis-smoke-test` and rebased onto current `main` (so you
pick up the `cpex-rate-limiter>=0.0.6` pin).

## Step 1 — get the base gateway image

The derivative image in step 3 layers on top of `mcpgateway/mcpgateway:latest`.
Pull it from the registry...

```bash
docker pull mcpgateway/mcpgateway:latest
```

...or build it locally if you can't pull:

```bash
make docker-prod
```

## Step 2 — generate self-signed test certs

```bash
./tls-test/gen-certs.sh
```

Writes `tls-certs/{ca.crt, ca.key, redis.crt, redis.key}`. The CA is a
self-signed cert valid for 365 days; the Redis server cert is signed by it
with SAN coverage for `redis`, `redis-tls`, `localhost`, and `127.0.0.1`.

The `tls-certs/` directory is gitignored — keys are generated locally per
setup and never committed.

## Step 3 — build the derivative gateway image

```bash
docker build \
    -f tls-test/Containerfile.tls-gateway \
    -t mcpgateway-tls-test:local \
    .
```

Build context is the repo root. The Containerfile is a single layer on top
of the base image: copy `tls-certs/ca.crt` into the OS trust store and run
`update-ca-trust extract`. The TLS-enabled cpex-rate-limiter wheel is
already installed in the base image via PyPI (`>=0.0.6`).

## Step 4 — bring the stack up

```bash
docker compose -p tls-test \
    -f docker-compose.yml \
    -f docker-compose-tls-redis.yml \
    up -d --no-build
```

`--no-build` is **important** — without it, compose tries to rebuild the
gateway image from `Containerfile.lite` (specified by the base compose
file), which would discard the derivative image you just built.

Wait ~30s for healthchecks, then confirm everything is `healthy`:

```bash
docker compose -p tls-test ps
```

## Step 5 — verify TLS support

Three checks; run all three for full confidence.

### (a) The rate-limiter plugin loaded with the redis backend

```bash
docker logs tls-test-gateway-1 2>&1 | grep -iE "RateLimiter|plugin"
```

Expect to see something like:

```
INFO  rate limiter initialized: backend=redis
```

Must **not** see:

```
ERROR  Rust rate limiter: Redis backend init failed:
       can't connect with TLS, the feature is not enabled
ERROR  Failed to load plugin RateLimiterPlugin: ... InvalidClientConfig
```

### (b) The gateway can speak TLS to the Redis server

```bash
docker exec tls-test-gateway-1 /app/.venv/bin/python - <<'EOF'
import asyncio, redis.asyncio
async def main():
    r = redis.asyncio.from_url("rediss://redis:6390/0")
    print("PING:", await r.ping())
    await r.aclose()
asyncio.run(main())
EOF
```

Expect: `PING: True`. Proves the gateway's OS trust store contains the
test CA — the same store that rustls-native-certs reads for the plugin's
Rust core.

### (c) The plugin's actual TLS code path works (not just connectivity)

This drives the rate-limiter plugin directly inside the gateway container,
which goes through the Rust core, the redis crate, and the rustls handshake
— i.e. the exact path a customer hits when their managed Redis URL is
`rediss://...`. No JWT or auth setup needed.

```bash
docker exec tls-test-gateway-1 /app/.venv/bin/python - <<'EOF'
import asyncio
from cpex_rate_limiter.rate_limiter import RateLimiterPlugin
from mcpgateway.plugins.framework import (
    GlobalContext, PluginConfig, PluginContext, ToolPreInvokePayload,
)

plugin = RateLimiterPlugin(PluginConfig(
    name="RL",
    kind="cpex_rate_limiter.rate_limiter.RateLimiterPlugin",
    hooks=["tool_pre_invoke"],
    priority=100,
    config={
        "by_user": "3/s",
        "backend": "redis",
        "redis_url": "rediss://redis:6390/0",
        "algorithm": "fixed_window",
    },
))
ctx = PluginContext(global_context=GlobalContext(request_id="r1", user="alice"))
payload = ToolPreInvokePayload(name="tool", arguments={})
result = asyncio.run(plugin.tool_pre_invoke(payload, ctx))
print("continue_processing:", result.continue_processing)
EOF
```

Expect: `continue_processing: True`.

Then confirm the counter key was written into TLS Redis:

```bash
docker exec tls-test-redis-1 redis-cli --tls -p 6390 \
    --cacert /certs/ca.crt --cert /certs/redis.crt --key /certs/redis.key \
    --insecure --scan --pattern 'rl:*'
```

Expect at least one key matching `rl:*alice*`. If you see one, the rustls
handshake succeeded end-to-end through the plugin's Rust core.

(`--insecure` on `redis-cli` skips hostname verification on the CLI side
only; the cert chain is still verified against the CA.)

## Step 6 — tear down

```bash
docker compose -p tls-test \
    -f docker-compose.yml \
    -f docker-compose-tls-redis.yml \
    down -v
```

`-v` drops named volumes (postgres data, redis insight) so the next `up`
starts clean.

---

## Architecture

```
host                      docker compose stack
─────                     ─────────────────────────────
                          ┌─ nginx :8080 ──────────────────┐
curl POST                 │                                │
/v1/tools/plugin_bindings │  gateway × 3 replicas          │
   ───────────────────►   │  (mcpgateway-tls-test:local)   │
                          │     ─ rate_limiter plugin      │
                          │       (cpex-rate-limiter       │
                          │        >=0.0.6 from PyPI)      │
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

The override (`docker-compose-tls-redis.yml`) reuses the base
`docker-compose.yml` and changes only what's needed to swap plain Redis
for a TLS Redis: redis listens on TLS port 6390 with cert bind-mounts,
gateway image is the derivative, gateway's `REDIS_URL` is `rediss://...`.

## Known limitations

- The derivative image bakes in the test CA — strictly local-testing
  material, never push it to a shared registry.
- Self-signed certs expire after 365 days. Rerun `gen-certs.sh` when
  expiry hits, then rebuild the derivative gateway image (the CA is
  baked in).
- `--insecure` on `redis-cli` in step 5(c) skips *hostname* verification
  only; cert-chain verification still happens.

## Why this exists

cpex-rate-limiter 0.0.6 enables TLS in the redis crate so operators can
point the plugin at managed Redis with in-transit encryption. The unit and
integration test suites can verify URL parsing and reach the network layer,
but the only way to prove the rustls handshake itself works end-to-end
under realistic conditions is against a real TLS-enabled Redis server.
This stack provides one with a self-signed CA, a derivative gateway image
that trusts that CA, and the cpex-rate-limiter wheel from PyPI — runnable
on any laptop with Docker.
