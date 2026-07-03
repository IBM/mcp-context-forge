# Praxis CF Dataplane

High-performance MCP (Model Context Protocol) filter library for the Praxis proxy framework.

## Overview

`praxis_cf_dataplane` is a **filter library** (not a standalone binary) that provides custom filters for handling MCP traffic in the ContextForge platform. It integrates with the Python control plane via gRPC and uses Praxis's auto-discovery mechanism for filter registration.

## Architecture

The library implements 4 custom filters that work alongside Praxis built-in filters:

1. **cf_control_plane_data** - Fetches session authentication and virtual server configuration from control plane
2. **cf_tools_router** - Determines routing (gateway vs upstream) based on MCP method and tool name
3. **cf_mcp_broker** - Handles gateway tool execution and catalog management
4. **cf_upstream_proxy** - Forwards requests to upstream MCP servers

These filters integrate with Praxis built-in filters:
- **McpFilter** - MCP protocol validation (Praxis built-in)
- **CPEX Policy Filters** - Authorization via OPA/Rego policies (Praxis built-in)

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Deployment

### 1. Add to Praxis Server

Add this crate to your Praxis server's `Cargo.toml`:

```toml
[dependencies]
praxis_cf_dataplane = { path = "../praxis_cf_dataplane" }
```

### 2. Auto-Discovery

Praxis build.rs automatically discovers filters via the `[package.metadata.praxis-filters]` marker in this crate's `Cargo.toml`. No manual registration code needed.

### 3. Configure Filters

Create `praxis_cf_dataplane.yaml` with your filter pipeline:

```yaml
listeners:
  - name: default
    address: "0.0.0.0:8080"
    filter_chains: [main]

filter_chains:
  - name: main
    filters:
      # MCP protocol validation
      - filter: mcp
        path: /server/:server_id/mcp
        max_body_bytes: 1048576
      
      # Fetch session + VS config
      - filter: cf_control_plane_data
        grpc_endpoint: ${CONTROL_PLANE_GRPC_ENDPOINT:-http://localhost:50051}
        session_cache_ttl: 300
        session_cache_size: 10000
      
      # Pre-routing authorization
      - filter: cpex_policy
        name: pre_routing_authz
        policy_file: policies/pre_routing.rego
      
      # Routing decision
      - filter: cf_tools_router
        grpc_endpoint: ${CONTROL_PLANE_GRPC_ENDPOINT:-http://localhost:50051}
      
      # Post-routing authorization
      - filter: cpex_policy
        name: post_routing_authz
        policy_file: policies/post_routing.rego
      
      # Gateway execution (conditional)
      - filter: cf_mcp_broker
        grpc_endpoint: ${CONTROL_PLANE_GRPC_ENDPOINT:-http://localhost:50051}
        condition:
          metadata_equals:
            mcp.route: gateway
      
      # Upstream forwarding (conditional)
      - filter: cf_upstream_proxy
        timeout_seconds: 30
        max_retries: 3
        condition:
          metadata_equals:
            mcp.route: upstream
```

### 4. Run Praxis Server

```bash
praxis-proxy -c praxis_cf_dataplane.yaml
```

## Development Status

**Current State:** Stub implementations with TODO comments for Praxis integration points.

All filters implement the required `from_config()` factory method and `HttpFilter` trait, but core functionality (gRPC calls, HTTP forwarding) is blocked pending Praxis API documentation for:

- gRPC client injection in filters
- HTTP client for upstream forwarding
- Metadata API usage patterns

See individual filter files in `src/filters/` for detailed TODO comments.

## Configuration

See [docs/configuration.md](docs/configuration.md) for comprehensive configuration guide.

## Documentation

- [Architecture](docs/architecture.md) - Detailed filter pipeline and design decisions
- [Configuration](docs/configuration.md) - Complete configuration reference
- [Filter Chain Examples](docs/filter-chain-examples.md) - Request flow examples

## Dependencies

- `praxis-filter` - Praxis filter framework (feat/cpex branch)
- `tonic` - gRPC client for control plane integration
- `prost` - Protocol Buffers support
- `serde` / `serde_json` / `serde_yaml` - Serialization
- `async-trait` - Async trait support

## License

Apache-2.0

## Contributing

This crate is part of the ContextForge project. See the main repository for contribution guidelines.
