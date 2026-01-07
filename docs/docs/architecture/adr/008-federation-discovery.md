# ADR-0008: Federation & Auto-Discovery via DNS-SD

- *Status:* **Deprecated** (see [#1912](https://github.com/IBM/mcp-context-forge/issues/1912))
- *Date:* 2025-02-21
- *Deprecated:* 2026-01-07
- *Deciders:* Core Engineering Team

> **⚠️ Deprecation Notice:** The `DiscoveryService` (mDNS auto-discovery) and `ForwardingService` have been removed. The `ToolService` now handles all gateway tool invocations with improved OAuth, plugin, and SSE support. Gateway peer management via `/gateways` API remains available.

## Context

The MCP Gateway must support **federated operation**, where multiple gateway instances:

- Automatically discover each other on a shared network
- Exchange metadata and tool/service availability
- Merge registries and route calls to remote nodes

Manual configuration (e.g. hardcoded peer IPs) is error-prone and brittle in dynamic environments like laptops or Kubernetes.

The codebase included a `DiscoveryService` and federation settings such as:

- `FEDERATION_ENABLED` *(deprecated)*
- `FEDERATION_DISCOVERY` *(deprecated)*
- `FEDERATION_PEERS` *(deprecated)*
- `FEDERATION_SYNC_INTERVAL` *(deprecated)*

## Decision

We enabled **auto-discovery via DNS-SD (mDNS/zeroconf)** by default. Each gateway:

- Published itself using `_mcp._tcp.local.` with TXT records
- Periodically probed for peers using `zeroconf` or a fallback registry
- Merged discovered gateways into its internal routing map
- Sent periodic liveness pings to verify peer health

Static peer configuration was supported for restricted networks.

## Consequences

- 🔌 Gateways connected seamlessly on the same local network or overlay mesh
- 🕵️♂️ DNS-SD added moderate background network traffic, tunable via TTL
- ⚠️ Firewalls or environments without multicast required static peer config
- ♻️ Federated topologies were self-healing and required no orchestration

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Static peer list only** | Manual entry, error-prone, not zero-config. |
| **Central registry (e.g. etcd, Consul)** | Adds external infrastructure and tight coordination. |
| **Cloud DNS-based discovery** | Requires cloud provider integration and persistent internet access. |
| **gRPC service registry** | Less transparent, requires protobuf tooling and internal coordination layer. |

## Deprecation Rationale

- **mDNS Discovery** was not required for current deployment models (Kubernetes, cloud environments)
- **ForwardingService** duplicated functionality already present in `ToolService`, which provides more advanced features (OAuth, plugins, SSE)
- Gateway peer management remains available via the `/gateways` REST API
- `FEDERATION_TIMEOUT` setting is retained for gateway request timeouts

## Status

**Deprecated.** The `DiscoveryService` and `ForwardingService` have been removed. Use the `/gateways` API for manual gateway peer registration.
