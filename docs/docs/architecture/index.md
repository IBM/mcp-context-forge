# Architecture Overview

The **MCP Gateway** acts as a unified entry point for tools, resources, prompts, and servers, federating local and remote nodes into a coherent MCP-compliant interface.

This gateway:

- Wraps REST/MCP tools and resources under JSON-RPC and streaming protocols
- Offers a pluggable backend (cache, auth, storage)
- Exposes multiple transports (HTTP, WS, SSE, StreamableHttp, stdio)
- Automatically discovers and merges federated peers

## System Architecture

```mermaid
graph TD
    subgraph Clients
        ui["Admin UI (Browser)"]
        cli["CLI Tools"]
        sdk["SDK / Scripts"]
    end

    subgraph Gateway
        app["FastAPI App"]
        auth["Auth Middleware<br/>(JWT + Basic)"]
        router["Transport Router<br/>(HTTP / WS / SSE / STDIO)"]
        services["Service Layer<br/>(Tool / Resource / Prompt / Server)"]
        db["Async DB<br/>(SQLAlchemy + Alembic)"]
        cache["Cache Backend<br/>(memory / redis / db)"]
        metrics["Metrics Exporter<br/>(/metrics Prometheus)"]
    end

    subgraph Federation
        discovery["Discovery Service<br/>(DNS-SD + Static Peers)"]
        peers["Remote Gateways"]
    end

    ui --> app
    cli --> router
    sdk --> router
    app --> auth --> router
    router --> services
    services --> db
    services --> cache
    services --> metrics
    services --> discovery
    discovery --> peers

```

> Each service (ToolService, ResourceService, etc.) operates independently with unified auth/session/context layers.

## Additional Architecture Documentation

- [Export/Import System Architecture](export-import-architecture.md) - Technical design of configuration management system

## ADRs and Design Decisions

We maintain a formal set of [Architecture Decision Records](adr/index.md) documenting all major design tradeoffs and rationale.

📜 See the [full ADR Index →](adr/index.md)
