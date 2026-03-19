# Conformance

Every new protocol module should prove the same categories of correctness
before it is considered release-ready.

## Minimum Required Gates

### 1. Contract Compatibility

The module must prove:

- descriptor compatibility
- lifecycle compatibility
- SPI version negotiation
- correct startup failure on incompatible SPI

### 2. Security and Policy

The module must prove:

- unauthenticated deny paths
- wrong-team deny paths
- insufficient-permission deny paths
- hidden-resource not-found behavior where the product requires it
- trusted-channel behavior for sidecar-only core APIs

### 3. Protocol Correctness

The module must prove:

- required protocol surfaces
- capability negotiation
- correct optional-surface behavior
- stable request and response shapes
- structured error handling

### 4. Plugin Parity

The module must prove plugin-sensitive flows still behave correctly.

For a protocol module, this means:

- explicitly exercising active plugins, not only plugin-disabled stacks
- proving both the normal path and the parity-sensitive path
- documenting any remaining delegated or unsupported hooks

### 5. Rollback and Degradation

The module must prove:

- health reporting
- degraded-state reporting
- rollback or fallback path
- safe failure when the core is unavailable

### 6. Performance

The module must prove:

- no unacceptable regression on the intended hot paths
- no correctness failures under representative load
- no hidden bypass of policy or plugin behavior in the fast path

## Environment Matrix

At minimum, release validation should cover:

- local or compose deployment
- the intended production deployment mode
- upgrade and migration behavior where the module changes deployment structure

If the release story includes Helm or Kubernetes, that must be validated too.

## Suggested Evidence

- focused unit tests
- live stack-backed E2E tests
- plugin parity tests
- protocol compliance suite where one exists
- benchmark or load sanity checks

## Protocol Profiles

Each protocol profile adds its own required checks:

- [A2A Module Profile](a2a-module.md)
- [LLM Module Profile](llm-module.md)
- [REST/gRPC Module Profile](rest-grpc-module.md)
