# Rate limiter over TLS + AUTH Redis — setup & findings

Companion notes for `test_rate_limiter_binding_single_instance_tls.py`.

This documents how to run the single-instance dynamic-binding rate-limiter test
against a **TLS-only, password-protected** Redis (mirroring a managed Redis such
as AWS ElastiCache with in-transit encryption + an auth token), and the config
pitfalls that cause `BACKEND_UNAVAILABLE`.

## How the plugin trusts and authenticates

Two independent layers must both succeed:

- **TLS** — the server proves its identity with a certificate; the plugin
  verifies it against a CA. Triggered by the `rediss://` URL scheme. The CA
  comes from either `redis_ssl_ca_certs` (explicit) or the container's OS trust
  store (the fast path, when `redis_ssl_ca_certs` is unset).
- **AUTH** — the client proves it is allowed by sending a password (the
  `requirepass` / ElastiCache auth token), embedded in the URL:
  `rediss://:<token>@host:6379/0`.

A failure in *either* layer surfaces to the plugin as the same
`BACKEND_UNAVAILABLE` (it just couldn't run its Redis commands). TLS is checked
first; AUTH only after the encrypted channel is up.

## Local setup

### 1. TLS + AUTH Redis

Generate a CA + server cert with SAN for `127.0.0.1`/`localhost`, then run a
TLS-only, password-protected Redis:

```bash
docker run -d --name rl-redis -p 6379:6379 \
  -v "$PWD/tls-certs:/certs:ro" redis:latest \
  redis-server --port 0 --tls-port 6379 \
  --tls-cert-file /certs/redis.crt --tls-key-file /certs/redis.key \
  --tls-ca-cert-file /certs/ca.crt --tls-auth-clients no \
  --requirepass "$REDIS_CLI_PASSWORD"
```

### 2. Plugin config (env-inheritance style)

cpex renders `plugins/config.yaml` through Jinja with `env=os.environ`, so
`{{ env.X }}` pulls from the gateway's environment at load time. Recommended,
nothing hardcoded:

```yaml
# RateLimiterPlugin -> config:
backend: "redis"
redis_url: '{{ env.RATELIMITER_REDIS_URL | default(env.REDIS_URL | default("redis://redis:6379/0")) }}'
# Guard the CA line so an UNSET env var does not render an empty string
# (an empty redis_ssl_ca_certs is treated as "set" and fails — see Pitfalls):
{% if env.RATELIMITER_REDIS_SSL_CA_CERTS %}
redis_ssl_ca_certs: '{{ env.RATELIMITER_REDIS_SSL_CA_CERTS }}'
{% endif %}
algorithm: "fixed_window"
fail_mode: "closed"
```

Then supply the values via the gateway environment (like a k8s secret would):

```bash
RATELIMITER_REDIS_URL='rediss://:<token>@127.0.0.1:6379/0'
RATELIMITER_REDIS_SSL_CA_CERTS='/abs/path/to/tls-certs/ca.crt'
```

If the image's OS trust store already contains the CA that signed the server
cert (e.g. ElastiCache's Amazon root in a UBI image's `ca-bundle.crt`), you can
omit `redis_ssl_ca_certs` entirely and rely on the fast path.

### 3. Run the test

```bash
RUN_BINDING_SINGLE_INSTANCE=1 \
JWT_SECRET_KEY=<secret> \
REDIS_CLI_PASSWORD=<same as requirepass> \
uv run pytest tests/live_gateway/plugins/test_rate_limiter_binding_single_instance_tls.py -v
```

`REDIS_CLI_PASSWORD` is needed so the test's own `redis-cli --tls -a ...` key
checks can authenticate. If it is wrong, the test **skips** the key assertions
(it does not fail) — the plugin may still be working; check for `rl:*` keys
directly.

## Pitfalls (these cause `BACKEND_UNAVAILABLE`)

1. **Scheme must be `rediss://` when any `redis_ssl_*` key is set.** If the URL
   resolves to plaintext `redis://` while `redis_ssl_ca_certs` is present, the
   plugin refuses to load with
   `redis_ssl_* config keys require the rediss:// URL scheme` and is **skipped**
   (so tools pass through unthrottled and no `rl:*` keys appear). Verify the env
   var actually starts with `rediss://` — note `RATELIMITER_REDIS_URL` takes
   precedence over `REDIS_URL` in the template above.

2. **Empty CA from an unset env var.** `redis_ssl_ca_certs: '{{ env.X }}'` with
   `X` unset renders to `""`, which the plugin treats as set-but-empty →
   file-not-found / scheme-guard failure. Guard the line with
   `{% if env.X %}...{% endif %}`, or omit it and use the OS trust store.

3. **Wrong auth token.** TLS can be perfect but if the password in the URL does
   not match `requirepass` / the ElastiCache auth token, Redis returns
   `WRONGPASS` and the plugin reports `BACKEND_UNAVAILABLE`. The token is an
   environment secret owned by the deployer; the plugin only uses what the URL
   carries.

## Verified

Single instance, dynamic per-tool binding, `rediss://:<token>@host` +
`redis_ssl_ca_certs` (both inherited from env): plugin loads, TLS handshake
verifies against the CA, AUTH succeeds, limits enforce, and per-dimension
counter keys are written:

```
rl:<team>:user:<email>:60
rl:<team>:tool:<tool>:60
rl:<team>:tenant:<team>:60
```

Wrong password reproduces `BACKEND_UNAVAILABLE` on demand — same symptom as a
TLS-trust failure, which is why the two layers must be isolated when debugging.
