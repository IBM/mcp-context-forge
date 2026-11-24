# Modular Runtime Specification

This section turns the [Modular Runtime Architecture](../modular-design.md)
into an implementation-oriented specification that another team can use to
build a protocol module in Rust, Go, or Python.

The intent is not to freeze every future protobuf field today. The intent is
to define the minimum contract surface clearly enough that:

- historical module experiments can inform future implementations
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

## Historical Precedent

The removed [Rust MCP Runtime](../rust-mcp-runtime.md) informed this proposal.
It demonstrated direct protocol ingress with core-owned policy. It is no longer
a reference implementation available for deployment or development.
[ADR-058](../adr/058-remove-rust-runtime-and-workspace.md) records its removal.
Future modules require implementation and validation of these target contracts.

## Status by Protocol Family

| Protocol family | Status |
|-----------------|--------|
| MCP | Python transport; a separate module remains proposed |
| A2A | Planned against this spec |
| LLM | Planned against this spec |
| REST/gRPC | Planned against this spec |
