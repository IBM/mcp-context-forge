# Praxis Configuration Dataplane Architecture

## Role

`praxis_cf_dataplane` is the pinned filter library compiled into ContextForge's dedicated Praxis image. ContextForge is the
authoritative control plane: it selects representable platform/team state, renders and encrypts a canonical bundle, and
publishes a fenced desired directive. The launcher owns retrieval, immutable local publication, validation, activation,
health, recovery, and process supervision.

The image is configuration-only in this release. It does not publish a client-facing traffic port, Service, or Ingress.
Owner-private and per-user state is not representable and is refused instead of widened.

## Registered filters

The repository-owned Praxis binary explicitly registers the MCP classifier and unconditional fail-closed CPEX dispatcher.
Generated `praxis.yaml` and `cpex/*.yaml` documents select those filters. Registration and native construction are verified
against Praxis commit `ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88` by `make praxis-task5-native-check`.

## Control and machine boundaries

- Platform management is `/v1/praxis` with `praxis.manage`.
- Replica machine access is trusted-proxy HTTPS at `/praxis/v1`.
- Desired and artifact reads require `praxis.artifacts.read`; reports require `praxis.reports.write`.
- Target and replica identity is derived from the persisted credential JTI.
- Each replica uses its own read-only mounted token and CA; TLS hostname and certificate validation is mandatory.

## Publication and activation

Source epoch, policy epoch, target fence, and desired-pointer CAS prevent stale publication. Content determines generation
identity. Rollout and directive identity determine one issuance, so the same generation can be retried with a new directive
and freshly frozen cohort. Report cursors advance response ETags independently of directive identity.

The launcher writes canonical archive members into a private generation staging directory, syncs them, and atomically
publishes the immutable directory. It validates compatibility and the native Praxis pipeline before starting a candidate.
The activation canary proves configuration parsing, listener readiness, and one local policy denial only. It does not prove
authenticated MCP traffic parity.

Candidate failure is reported to the control plane, which issues a fresh retry, rollback, or stop. Restart recovery verifies
persisted state and local generations before reuse. LKG expiry makes readiness unavailable and drains the complete process
group. No mutable-policy hot reload path exists.

## Verification

Run from the repository root:

```bash
make praxis-dataplane-check
make praxis-task5-native-check
cargo test --locked -p praxis_config_launcher
```
