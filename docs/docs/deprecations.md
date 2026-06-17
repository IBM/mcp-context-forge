# Deprecations

This page lists active deprecations and migration guidance.

!!! warning "Deprecated as of 2026-06-11; sunsets on 2026-07-07"
    The Rust MCP runtime sidecar, Rust A2A runtime sidecar, and
    `ValidationMiddleware` are deprecated. They remain available for existing
    deployments, but new deployments should use the default Python runtime
    paths and endpoint-level validation. They are scheduled for sunset on
    2026-07-07.

## Rust MCP runtime sidecar

Deprecated controls include `RUST_MCP_MODE`, `EXPERIMENTAL_RUST_MCP_*`, and
`MCP_RUST_*` settings that enable or configure the Rust MCP sidecar.

Use the default Python MCP transport path by leaving `RUST_MCP_MODE=off` and
`EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=false`.

Runtime signals:

- Gateway startup logs include a deprecation warning when the Rust MCP runtime
  path is enabled.
- Rust MCP runtime responses include `Deprecation`, `Sunset`, and
  `Link: <...>; rel="deprecation"` headers.

## Rust A2A runtime sidecar

Deprecated controls include `RUST_A2A_MODE`, `EXPERIMENTAL_RUST_A2A_*`, and
`A2A_RUST_*` settings that enable or configure the Rust A2A sidecar.

Use the default Python A2A invocation path by leaving `RUST_A2A_MODE=off`,
`EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=false`, and
`EXPERIMENTAL_RUST_A2A_RUNTIME_DELEGATE_ENABLED=false`.

Runtime signals:

- Gateway A2A delegation logs include a deprecation warning when an invocation
  uses the Rust A2A runtime.
- The Rust A2A binary logs a deprecation warning at startup.

## ValidationMiddleware

`mcpgateway.middleware.validation_middleware.ValidationMiddleware` is
deprecated.

Use endpoint-level Pydantic models, the existing `SecurityValidator` helpers,
and protocol-specific validation middleware instead. Leave
`VALIDATION_MIDDLEWARE_ENABLED=false` unless you need compatibility with an
existing deployment that already depends on this middleware.

Runtime signals:

- Gateway startup logs include a deprecation warning when the middleware is
  enabled.
- Instantiating the middleware emits a Python `DeprecationWarning`.
