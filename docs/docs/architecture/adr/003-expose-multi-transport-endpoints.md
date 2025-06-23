# ADR-0003: Expose Multi-Transport Endpoints (HTTP / WebSocket / SSE / STDIO)

- *Status:* Accepted
- *Date:* 2025-02-01
- *Deciders:* Mihai Criveti

## Context

The MCP Gateway must serve diverse clients: web browsers, CLIs, language-specific SDKs, and headless daemons.
Different use cases require support for both **request/response** and **streaming** interactions.

Requirements:

- Human-readable RPC over HTTP for developers
- Low-latency streaming for long-running tools
- IPC-style invocations for local CLI integration
- Unified business logic regardless of transport

## Decision

The gateway will support the following built-in transports:

- **HTTP JSON-RPC** (primary RPC interface)
- **WebSocket** (bidirectional messaging)
- **SSE (Server-Sent Events)** (for push-only event streaming)
- **Streamable HTTP**  (bidirectional, resumable streams, efficient MCP transport over HTTP)
- **STDIO** (optional local CLI / subprocess transport)

Transport selection is dynamic, based on environment (`TRANSPORT_TYPE`) and route grouping. All transports share the same service layer and authentication mechanisms.

## Consequences

- ✅ Maximum client flexibility, supporting modern browsers and legacy CLI tools.
- 🔄 Business logic remains decoupled from transport implementation.
- 📶 Streaming transports (WS, SSE) require timeout, reconnection, and back-pressure handling. Easy expansion with new MCP standards

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **HTTP-only JSON API** | Poor fit for long-lived streaming tasks; requires polling. |
| **gRPC (HTTP/2)** | Not browser-friendly; requires generated stubs; less discoverable. |
| **Separate microservices per transport** | Code duplication, diverging implementations, and operational complexity. |
| **Single transport abstraction** | Reduces explicitness; transport-specific needs get buried in generic interfaces. |

## Status

All four transports are implemented in the current FastAPI application and are toggleable via configuration.
