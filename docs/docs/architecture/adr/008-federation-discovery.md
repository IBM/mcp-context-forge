# ADR-0008: Federation & Auto-Discovery via DNS-SD

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

The MCP Gateway must support **federated operation**, where multiple gateway instances:

- Automatically discover each other on a shared network
- Exchange metadata and tool/service availability
- Merge registries and route calls to remote nodes

Manual configuration (e.g. hardcoded peer IPs) is error-prone and brittle in dynamic environments like laptops or Kubernetes.

The codebase includes a `DiscoveryService` and federation settings such as:

- `FEDERATION_ENABLED`
- `FEDERATION_DISCOVERY`
- `DISCOVERY_INTERVAL_SECONDS`

## Decision

We enable **auto-discovery via DNS-SD (mDNS/zeroconf)** by default. Each gateway:

- Publishes itself using `_mcp._tcp.local.` with TXT records
- Periodically probes for peers using `zeroconf` or a fallback registry
- Merges discovered gateways into its internal routing map
- Sends periodic liveness pings to verify peer health

Static peer configuration is still supported for restricted networks.

## Consequences

- 🔌 Gateways connect seamlessly on the same local network or overlay mesh
- 🕵️‍♂️ DNS-SD adds moderate background network traffic, tunable via TTL
- ⚠️ Firewalls or environments without multicast must use static peer config
- ♻️ Federated topologies are self-healing and require no orchestration

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Static peer list only** | Manual entry, error-prone, not zero-config. |
| **Central registry (e.g. etcd, Consul)** | Adds external infrastructure and tight coordination. |
| **Cloud DNS-based discovery** | Requires cloud provider integration and persistent internet access. |
| **gRPC service registry** | Less transparent, requires protobuf tooling and internal coordination layer. |

## Status

Auto-discovery is implemented using `zeroconf`, and federation is active when `FEDERATION_ENABLED=true`.

Current feature is early pre-alpha and may not work correctly.
