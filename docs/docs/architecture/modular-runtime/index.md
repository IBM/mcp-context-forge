# Modular Runtime Specification

This section turns the [Modular Runtime Architecture](../modular-design.md)
into an implementation-oriented specification that another team can use to
build a protocol module in Rust, Go, or Python.

The intent is not to freeze every future protobuf field today. The intent is
to define the minimum contract surface clearly enough that:

- the existing Rust MCP module can be understood as the reference implementation
- a Rust A2A module can be implemented without re-designing the trust model
- a Go LLM proxy module can be implemented without guessing where policy lives
- a REST or gRPC module can be implemented without inventing a different
  lifecycle or error model

## Reading Order

1. [Core SPI](core-spi.md)
2. [Module Descriptor](module-descriptor.md)
3. [Module Lifecycle](module-lifecycle.md)
4. [Error Model](error-model.md)
5. [Conformance](conformance.md)
6. the protocol profile that matches the module being implemented
   - [MCP Module Profile](mcp-module.md)
   - [A2A Module Profile](a2a-module.md)
   - [LLM Module Profile](llm-module.md)
   - [REST/gRPC Module Profile](rest-grpc-module.md)

## Contract Status

This spec set is **normative at the architecture level**:

- the boundaries are intended
- the ownership rules are intended
- the lifecycle and required fields are intended

It is **illustrative at the wire-schema level**:

- example JSON and proto-like structures define the required information model
- final generated bindings can still evolve as long as they preserve those
  semantics

## Implemented Precedent

The first implemented precedent is the
[Rust MCP Runtime](../rust-mcp-runtime.md).

That precedent proves:

- a protocol runtime can move out of Python
- a module can own direct public ingress
- the core can remain authoritative for auth, token scoping, and RBAC
- plugin parity and rollback can still be preserved

It does **not** mean that every future module must copy the exact current Rust
MCP seam. The target-state contracts in this section are slightly more generic
than the current implementation.

## Status by Protocol Family

| Protocol family | Status |
|-----------------|--------|
| MCP | Implemented as a Rust sidecar/runtime path |
| A2A | Planned against this spec |
| LLM | Planned against this spec |
| REST/gRPC | Planned against this spec |
