# Praxis CF Dataplane

`praxis_cf_dataplane` is the ContextForge filter library embedded in the dedicated Praxis configuration image. It is a
root Cargo-workspace member and links the authoritative public Praxis source at
<https://github.com/praxis-proxy/praxis>, pinned to full commit
`ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88` (immutable image revision `ed46eb5`).

## Shipped architecture

The repository-owned image builds the pinned Praxis runtime with the ContextForge MCP classifier and fail-closed CPEX
dispatcher registered explicitly. `praxis_config_launcher` is PID 1. It polls ContextForge's trusted-proxy HTTPS machine
API at exactly `/praxis/v1`, verifies encrypted canonical bundles, stages immutable local generation directories, validates
and canaries a candidate, and supervises the Praxis process group.

This is a configuration-delivery dataplane. It has no client-facing Service, Ingress, published traffic port, or direct
Praxis MCP traffic surface. Operator target management remains on `/v1/praxis` and requires `praxis.manage`; machine desired
and artifact reads require `praxis.artifacts.read`, while monotonic reports require `praxis.reports.write`.

Each registered replica has its own persisted JTI-bound credential. The launcher rereads its read-only mounted token for
each physical request, allowing at most two overlapping active JTIs during rotation. Replicas must not share credentials.
The trusted CA is mounted separately and hostname and certificate verification remain mandatory.

## Immutable generation lifecycle

ContextForge renders only platform-public and team-owned state; owner-private and per-user state is refused as
nonrepresentable. Generation identity names content, while each activation, retry, rollback, stop, or same-generation
replacement receives a fresh rollout, directive, fence, and cohort. Cursor-sensitive response ETags advance with accepted
reports without changing directive identity.

There is no mutable-policy hot reload. A new bundle is a new immutable generation. Candidate validation covers parsing,
listener readiness, and one local policy denial; it does not claim authenticated MCP traffic parity. Candidate failure
causes a server-directed retry, rollback, or stop, and restart recovery revalidates persisted local state.

See [the configuration guide](docs/configuration.md) for exact environment, compatibility, TLS, timeout, shutdown,
key-rotation, and recovery contracts.

## Development and verification

Build and test from the repository root so Cargo uses the workspace lock and exact Praxis revision:

```bash
make praxis-dataplane-check
make praxis-task5-native-check
cargo test --locked -p praxis_config_launcher
```

The image build is also repository-owned:

```bash
make docker-praxis-dataplane IMAGE_TAG=ed46eb5
```

Do not launch this crate as an independent proxy or hand-author mutable runtime policy files. Production configuration is
rendered by ContextForge, encrypted at rest, delivered through the machine API, and activated by the launcher.

## Documentation

- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Filter chain examples](docs/filter-chain-examples.md)

## License

Apache-2.0
