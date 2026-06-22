# Rate limiter shared-connection — containerized TLS e2e

One-command stack to run the rate-limiter TLS+AUTH binding test against the
**baked gateway image** (`cpex-rate-limiter` 0.1.6, shared Redis connection) with
**2 gunicorn workers**, on a shared docker network with container-name
Redis/Postgres/fast-time.

```bash
./rl-shared-bake/up.sh        # build-free if the image exists; brings up the whole stack
./rl-shared-bake/run-e2e.sh   # runs the container test (expects the stack up)
./rl-shared-bake/down.sh      # tear it all down
```

Watch the shared connection live:

```bash
docker logs -f rl-gw 2>&1 | grep --line-buffered "opened redis connection"
# → "rate limiter: opened redis connection (shared across N instance(s) ...)" once per worker
```

## What's in here

| file | purpose |
|------|---------|
| `up.sh` | idempotent bring-up: certs (SAN `rl-redis`), `rl-net`, `rl-pg` / `rl-redis` (TLS+AUTH) / `rl-fast-time`, gateway (2 workers, full env), fast-time pre-registration |
| `run-e2e.sh` | runs `tests/live_gateway/plugins/test_rate_limiter_binding_single_instance_tls_container.py` with the right env |
| `down.sh` | removes the `rl-*` containers + `rl-net` |
| `Dockerfile.rl-shared` | bakes the linux/arm64 0.1.6 wheel onto the base image |
| `config.yaml` | dynamic-test plugin config: RateLimiterPlugin `enforce` + guarded `redis_ssl_ca_certs` |
| `config-static.yaml` | static-test plugin config: `by_user`/`by_tenant`/`by_tool` all `3/m` |
| `static-up.sh` / `static-run.sh` / `static-down.sh` | **isolated** static-config stack (own `rl-static-*` containers, `rl-static-net`, port **8001**) |

## Static-config variant (no bindings API)

A separate, isolated stack that exercises the rate limiter from **static
`config.yaml` only** — closest to Raji's setup. Runs independently of the dynamic
stack (different containers/network/port), so both can be up at once.

```bash
./rl-shared-bake/static-up.sh     # rl-static-* containers, port 8001, config-static.yaml
./rl-shared-bake/static-run.sh    # runs test_rate_limiter_static_config_container.py
./rl-shared-bake/static-down.sh
```

All three limits are `3/m`, so a 5-call burst gives `allowed=3, blocked=2`, and the
`user` / `tool` / `tenant` counter keys each reach 5 under `rl:<team>:*`. The test
creates an ephemeral team + stamps the tool so the tenant dimension is present
(the limit stays 100% static).

## Images it expects

- `mcpgateway/mcpgateway:rl-0.1.6` — base image + the shared-connection wheel baked in (default).
  Override with `GW_IMAGE=<tag> ./rl-shared-bake/up.sh`.

Build the base + bake:

```bash
# base (standard prod build from the current branch; PyPI cpex)
make docker-prod                       # -> mcpgateway/mcpgateway:latest
docker tag mcpgateway/mcpgateway:latest mcpgateway/mcpgateway:base-0.1.4
# bake the local linux wheel on top
docker build --platform linux/arm64 -f rl-shared-bake/Dockerfile.rl-shared \
  -t mcpgateway/mcpgateway:rl-0.1.6 rl-shared-bake/
```

## Why a separate container test

The make-dev test (`..._tls.py`) is left untouched. The container variant
(`..._tls_container.py`) subclasses it and only adds an admin-API redirect guard;
all container specifics (env, cert SAN, plugin `enforce`, CA, fast-time URL) are
folded into `up.sh`. Notably `up.sh` sets `PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false`
— current `main` forces a first-login password change that 303-redirects every
`/admin/*` route, which the make-dev test doesn't account for.
