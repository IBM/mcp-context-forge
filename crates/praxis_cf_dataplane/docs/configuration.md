# Praxis Configuration Dataplane

ContextForge builds `praxis_cf_dataplane` into the dedicated Praxis image. The image uses the public source
<https://github.com/praxis-proxy/praxis> at full commit `ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88`; manifests use immutable
revision `ed46eb5`. The crate supplies the MCP classifier and CPEX dispatcher needed by generated bundles.

## Runtime contract

The launcher is PID 1 and supervises Praxis from immutable generation directories. It requires
`PRAXIS_CONTROL_PLANE_URL`, `PRAXIS_CA_PATH`, `PRAXIS_TOKEN_PATH`, `PRAXIS_GENERATION_ROOT`, `PRAXIS_STATE_PATH`,
`PRAXIS_BINARY`, and loopback-only `PRAXIS_HEALTH_LISTEN`. The control-plane URL is HTTPS only and ends exactly in
`/praxis/v1`. Direct HTTP, a wrong SAN or an untrusted CA fails closed. Token and CA files are read-only deployment mounts.

The desired poll is `15` seconds and the authenticated heartbeat is `60` seconds. The launcher rereads the mounted token
for every physical request, including one retry after 401 or 403. Each replica has its own JTI-bound token and replicas must
not share a token.

Artifacts are at most 16 MiB and must match `praxis-render-manifest/v1`, bundle `praxis-bundle/v1`, renderer `1.0.0`,
Praxis `ed46eb5`, CPEX `cpex/v1`, MCP `2025-11-25`, and minimum launcher `0.1.0`. Canonical archives and every file hash are
checked before an immutable local generation is published.

## Activation and recovery

Generation identity names content. Rollout and directive identity name an issuance, so the same generation can return in a
fresh rollout cohort with a new fence. Response ETags also carry the report cursor. Reports are monotonic:
`prepared`, `canary_passed`, then `active`.

Activation validates configuration, starts the candidate listener, and checks one local policy denial within `30` seconds.
This canary doesn't claim authenticated MCP traffic parity. Candidate contract or compatibility failure removes local
candidate state and refetches it. A restart reopens and revalidates persisted generation and cursor state.

The launcher keeps the last authenticated generation for `3600` seconds. It becomes stale exactly at `now >= deadline`.
Readiness drops and the process is drained. Stop, rollback, and replacement signal the complete process group with TERM for
30 seconds, then KILL for 5 seconds. Compose and Helm reserve 45 seconds for shutdown.

No hot reload exists. Bundle changes use immutable generations and server-issued directives. This image exposes launcher
health only and has no direct Praxis traffic surface.

## Control-plane confidentiality

ContextForge encrypts archives and source sidecars with AES-256-GCM. Primary and sidecar envelopes reserve distinct nonces;
ciphertext hash, authenticated metadata version, and plaintext archive hash are checked. Operators rotate by selecting a new
active key while keeping retained decrypt keys until old generations retire. Rendered bundles exclude token values,
credentials, upstream authorization headers, private owner state, and control-plane plaintext.
