# Praxis MCP Dataplane Architecture

## Overview

The Praxis MCP dataplane is a filter library for the Praxis proxy framework that provides high-performance MCP (Model Context Protocol) traffic handling. It integrates with the ContextForge Python control plane via gRPC and uses Praxis's auto-discovery mechanism to register custom filters for authentication, authorization, routing, and execution.

## Deployment Model

This crate is a **filter library**, not a standalone binary. It is loaded by the standard `praxis-proxy` server:

1. Add `praxis_cf_dataplane` to the Praxis server's `Cargo.toml`
2. Praxis build.rs discovers filters via `[package.metadata.praxis-filters]`
3. Filters are auto-registered at compile time
4. Configure filters in `praxis_cf_dataplane.yaml`
5. Run: `praxis-proxy -c praxis_cf_dataplane.yaml`

**Filter Registration:**
```rust
// In src/lib.rs
use praxis_filter::export_filters;

export_filters! {
    http "cf_control_plane_data" => filters::ControlPlaneDataFilter::from_config,
    http "cf_tools_router" => filters::ToolsRouterFilter::from_config,
    http "cf_mcp_broker" => filters::McpBrokerFilter::from_config,
    http "cf_upstream_proxy" => filters::UpstreamProxyFilter::from_config,
}
```

## Design Principles

1. **Separation of Concerns** - Data fetching (I/O) is separate from policy evaluation (logic)
2. **Two-Stage Authorization** - Virtual server access + gateway/upstream access
3. **Conditional Execution** - Filters execute based on routing decisions
4. **Metadata Flow** - Filters communicate via shared metadata context
5. **Defense in Depth** - Multiple authorization checkpoints

## Filter Pipeline (7 Filters)

### 1. Praxis McpFilter (Built-in)
**Purpose:** MCP protocol validation and JSON-RPC parsing

**Responsibilities:**
- Validates MCP protocol version header
- Parses JSON-RPC 2.0 envelope
- Extracts method name (e.g., `tools/call`, `tools/list`)
- Extracts tool name from `params.name` (for `tools/call`)
- Validates JSON-RPC structure

**Metadata Written:**
- `mcp.method` - The MCP method being called
- `mcp.name` - The tool name (if `tools/call`)
- `mcp.jsonrpc_id` - Request ID for response correlation
- `mcp.jsonrpc_version` - JSON-RPC version

**Result:** `Continue` (or `Reject` if invalid)

---

### 2. cf_control_plane_data (Custom)
**Purpose:** Fetch session and configuration data from control plane

**Responsibilities:**
- Extract JWT token from `Authorization: Bearer` header
- Call control plane gRPC `Authenticate(token)` → session data
- Cache authenticated sessions (TTL 300s)
- Extract virtual server ID from request path
- Call control plane gRPC `GetVirtualServerConfig(vs_id)` → VS configuration
- Write ALL data to filter metadata for downstream consumption

**Metadata Written:**
- `mcp.session_id` - Unique session identifier
- `mcp.user_email` - User's email address
- `mcp.teams` - Comma-separated team memberships
- `mcp.is_admin` - Admin flag
- `mcp.virtual_server_id` - Virtual server identifier
- `mcp.virtual_server_tools` - JSON array of exposed tools
- `mcp.virtual_server_access_policy` - RBAC rules for VS

**Does NOT:** Make authorization decisions (pure data fetching)

**Result:** `Continue` (or `Reject(401)` if authentication fails)

---

### 3. CPEX Policy Filter #1 (Praxis Built-in)
**Purpose:** Pre-routing authorization (virtual server access control)

**Responsibilities:**
- Evaluate policies against metadata from previous filters
- Check if user has access to virtual server
- Check if tool is exposed on virtual server (for `tools/call`)
- Check if user can list tools (for `tools/list`)

**Metadata Read:**
- `mcp.method` (from McpFilter)
- `mcp.name` (from McpFilter)
- `mcp.user_email` (from cf_control_plane_data)
- `mcp.teams` (from cf_control_plane_data)
- `mcp.virtual_server_tools` (from cf_control_plane_data)
- `mcp.virtual_server_access_policy` (from cf_control_plane_data)

**Policy Example (OPA/Rego):**
```rego
package contextforge.pre_routing

default allow = false

# Allow tools/call if tool is exposed and user has access
allow {
    input.method == "tools/call"
    input.name in input.virtual_server_tools
    has_team_access
}

# Allow tools/list if user has access to virtual server
allow {
    input.method == "tools/list"
    has_team_access
}

has_team_access {
    input.teams[_] in input.virtual_server_access_policy.allowed_teams
}
```

**Result:** `Continue` (or `Reject(403)` if policy denies)

---

### 4. cf_tools_router (Custom)
**Purpose:** Route resolution and tool mapping

**Responsibilities:**
- Determine if request routes to gateway or upstream
- For `tools/call`: resolve virtual server tool → gateway/upstream tool mapping
- For `tools/list`: determine which sources to query (gateway, upstream, or both)
- For `resources/*`, `prompts/*`: route to upstream
- Call control plane gRPC `ResolveToolCall()` or `GetVirtualServerConfig()`

**Metadata Read:**
- `mcp.method` (from McpFilter)
- `mcp.name` (from McpFilter)
- `mcp.virtual_server_id` (from cf_control_plane_data)

**Metadata Written:**
- `mcp.route` - Routing decision: `"gateway"` or `"upstream"`
- `mcp.gateway_id` - Gateway ID (if route=gateway)
- `mcp.gateway_tool` - Gateway tool name (if route=gateway)
- `mcp.upstream_url` - Upstream server URL (if route=upstream)
- `mcp.upstream_tool` - Upstream tool name (if route=upstream)

**Routing Logic:**
```rust
match (method, tool_config) {
    ("tools/call", tool) if tool.source == "gateway" => {
        ctx.set_metadata("mcp.route", "gateway");
        ctx.set_metadata("mcp.gateway_id", tool.gateway_id);
        ctx.set_metadata("mcp.gateway_tool", tool.gateway_tool_name);
    }
    ("tools/call", tool) if tool.source == "upstream" => {
        ctx.set_metadata("mcp.route", "upstream");
        ctx.set_metadata("mcp.upstream_url", tool.upstream_url);
        ctx.set_metadata("mcp.upstream_tool", tool.upstream_tool_name);
    }
    ("tools/list", _) => {
        ctx.set_metadata("mcp.route", "gateway"); // Broker merges catalogs
    }
    ("resources/*" | "prompts/*", _) => {
        ctx.set_metadata("mcp.route", "upstream");
    }
}
```

**Result:** `Continue`

---

### 5. CPEX Policy Filter #2 (Praxis Built-in)
**Purpose:** Post-routing authorization (gateway/upstream access control)

**Responsibilities:**
- Evaluate policies based on routing decision
- If route=gateway: check gateway tool authorization
- If route=upstream: check upstream server authorization
- Conditional execution based on `mcp.route`

**Metadata Read:**
- `mcp.route` (from cf_tools_router)
- `mcp.gateway_id` (from cf_tools_router, if gateway route)
- `mcp.upstream_url` (from cf_tools_router, if upstream route)
- `mcp.user_email` (from cf_control_plane_data)
- `mcp.teams` (from cf_control_plane_data)

**Policy Example (OPA/Rego):**
```rego
package contextforge.post_routing

default allow = false

# Allow gateway route if user has access to gateway
allow {
    input.route == "gateway"
    input.gateway_id in input.user_allowed_gateways
}

# Allow upstream route if user has access to upstream server
allow {
    input.route == "upstream"
    input.upstream_url in input.user_allowed_upstreams
}
```

**Result:** `Continue` (or `Reject(403)` if policy denies)

---

### 6. cf_mcp_broker (Custom)
**Purpose:** Gateway tool execution and catalog management

**Responsibilities:**
- **Conditional:** Only executes if `mcp.route = "gateway"`
- For `tools/call`: execute tool on gateway's MCP server
- For `tools/list`: fetch and merge gateway + upstream catalogs
- For `initialize`: return gateway capabilities
- For `ping`: return pong
- Call control plane gRPC `ExecuteTool()`, `ListTools()`, etc.

**Metadata Read:**
- `mcp.route` (from cf_tools_router)
- `mcp.method` (from McpFilter)
- `mcp.gateway_id` (from cf_tools_router)
- `mcp.gateway_tool` (from cf_tools_router)

**Execution Logic:**
```rust
async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction> {
    // Skip if not gateway route
    if ctx.get_metadata("mcp.route") != Some("gateway") {
        return Ok(FilterAction::Continue);
    }

    let method = ctx.get_metadata("mcp.method").unwrap();
    match method {
        "tools/call" => self.execute_tool(ctx).await,
        "tools/list" => self.list_tools(ctx).await,
        "initialize" => self.initialize(ctx).await,
        "ping" => self.ping(ctx).await,
        _ => Ok(FilterAction::Continue), // Let upstream_proxy handle
    }
}
```

**Result:** `Reject(200, response_body)` - Short-circuits with response

---

### 7. cf_upstream_proxy (Custom)
**Purpose:** Upstream server request forwarding

**Responsibilities:**
- **Conditional:** Only executes if `mcp.route = "upstream"`
- Forward request to upstream MCP server
- Preserve JSON-RPC envelope
- Translate tool names if needed (virtual → upstream)
- Return upstream response as-is

**Metadata Read:**
- `mcp.route` (from cf_tools_router)
- `mcp.upstream_url` (from cf_tools_router)
- `mcp.upstream_tool` (from cf_tools_router)

**Forwarding Logic:**
```rust
async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction> {
    // Skip if not upstream route
    if ctx.get_metadata("mcp.route") != Some("upstream") {
        return Ok(FilterAction::Continue);
    }

    let upstream_url = ctx.get_metadata("mcp.upstream_url").unwrap();
    let response = self.http_client
        .post(upstream_url)
        .json(&request_body)
        .send()
        .await?;

    Ok(FilterAction::Reject(Rejection::status(200).with_body(response.bytes())))
}
```

**Result:** `Reject(200, upstream_response)` - Short-circuits with upstream response

---

## Request Flow Diagram

```
Client Request → /server/{server_id}/mcp
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. McpFilter (Praxis)                                       │
│    Parse MCP protocol, extract method/tool                 │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. cf_control_plane_data                                    │
│    Authenticate JWT, fetch session + VS config             │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. CPEX Policy #1 (Praxis)                                  │
│    Evaluate pre-routing policies (VS access)               │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. cf_tools_router                                          │
│    Resolve routing: gateway or upstream                    │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. CPEX Policy #2 (Praxis)                                  │
│    Evaluate post-routing policies (gateway/upstream)       │
└─────────────────────────────────────────────────────────────┘
    ↓
    ├─── route=gateway ───┐
    │                     │
    ↓                     ↓
┌──────────────────┐  ┌──────────────────┐
│ 6. cf_mcp_broker │  │ 7. cf_upstream_  │
│    Execute tool  │  │    proxy         │
│    on gateway    │  │    Forward to    │
│                  │  │    upstream      │
└──────────────────┘  └──────────────────┘
    ↓                     ↓
    └─────────┬───────────┘
              ↓
         Response to Client
```

## Key Architectural Decisions

### 1. Separation of Data Fetching and Policy Evaluation

**Rationale:** Separating I/O (cf_control_plane_data) from logic (CPEX) provides:
- Cleaner code organization
- Easier testing (mock data vs test policies)
- Better caching opportunities
- Policy flexibility (update policies without changing data fetching)

### 2. Two CPEX Filters

**Rationale:** Pre-routing and post-routing authorization stages provide:
- Defense in depth (two authorization checkpoints)
- Conditional authorization (only check relevant resources)
- Clear separation of concerns (VS access vs gateway/upstream access)

### 3. Conditional Filter Execution

**Rationale:** Filters check `mcp.route` to determine execution:
- Avoids unnecessary work
- Clear execution paths (gateway OR upstream, not both)
- Simpler debugging (know which path was taken)

### 4. Metadata-Based Communication

**Rationale:** Filters communicate via shared metadata:
- Loose coupling between filters
- Easy to add new filters
- Clear data flow
- Praxis-native pattern

## Control Plane Integration

### gRPC Service Methods

```protobuf
service ControlPlane {
    // Authentication
    rpc Authenticate(AuthenticateRequest) returns (AuthenticateResponse);
    
    // Configuration
    rpc GetVirtualServerConfig(GetVirtualServerConfigRequest) returns (GetVirtualServerConfigResponse);
    
    // Routing
    rpc ResolveToolCall(ResolveToolCallRequest) returns (ResolveToolCallResponse);
    
    // Execution
    rpc ExecuteTool(ExecuteToolRequest) returns (ExecuteToolResponse);
    rpc ListTools(ListToolsRequest) returns (ListToolsResponse);
}
```

### Session Caching

**Strategy:** In-memory cache with TTL
- Cache key: JWT token hash
- Cache value: Session data (user_email, teams, session_id)
- TTL: 300 seconds (5 minutes)
- Eviction: LRU when cache full

**Benefits:**
- Reduces control plane load
- Faster authentication (no gRPC call on cache hit)
- Automatic expiration (TTL)

## Security Model

### Two-Stage Authorization

1. **Virtual Server Authorization (CPEX #1)**
   - User must have access to virtual server
   - Tool must be exposed on virtual server
   - Evaluated before routing decision

2. **Gateway/Upstream Authorization (CPEX #2)**
   - User must have access to gateway (if gateway route)
   - User must have access to upstream server (if upstream route)
   - Evaluated after routing decision

### Defense in Depth

Multiple security layers:
1. JWT validation (cf_control_plane_data)
2. Session authentication (cf_control_plane_data)
3. Virtual server access (CPEX #1)
4. Tool exposure check (CPEX #1)
5. Gateway/upstream access (CPEX #2)

## Performance Considerations

### Caching Strategy

- **Session cache:** 300s TTL, reduces auth overhead
- **VS config cache:** Could be added if needed
- **Policy evaluation:** In-memory, very fast

### Conditional Execution

- Filters skip unnecessary work based on `mcp.route`
- Only one execution path runs (gateway OR upstream)
- Short-circuit response (no further filter execution)

### gRPC Connection Pooling

- Reuse gRPC connections to control plane
- Connection pool size: configurable
- Keep-alive: enabled

## Configuration

### Praxis Config (praxis_cf_dataplane.yaml)

```yaml
routes:
  - path: /server/:server_id/mcp
    filters:
      # Protocol validation
      - filter: mcp
        max_body_bytes: 1048576
        on_invalid: reject
      
      # Data fetching
      - filter: cf_control_plane_data
        grpc_endpoint: http://localhost:50051
        session_cache_ttl: 300
        session_cache_size: 10000
      
      # Pre-routing authorization
      - filter: cpex_policy
        name: pre_routing_authz
        policy_file: policies/pre_routing.rego
        input_metadata:
          - mcp.method
          - mcp.name
          - mcp.user_email
          - mcp.teams
          - mcp.virtual_server_tools
          - mcp.virtual_server_access_policy
      
      # Routing
      - filter: cf_tools_router
        grpc_endpoint: http://localhost:50051
      
      # Post-routing authorization
      - filter: cpex_policy
        name: post_routing_authz
        policy_file: policies/post_routing.rego
        input_metadata:
          - mcp.route
          - mcp.gateway_id
          - mcp.upstream_url
          - mcp.user_email
          - mcp.teams
      
      # Execution
      - filter: cf_mcp_broker
        grpc_endpoint: http://localhost:50051
      
      - filter: cf_upstream_proxy
```

## Future Enhancements

1. **Policy Hot-Reload** - Update CPEX policies without restart
2. **Metrics & Tracing** - OpenTelemetry integration
3. **Rate Limiting** - Per-user, per-tool rate limits
4. **Circuit Breaker** - Upstream server health checks
5. **Request Transformation** - Modify requests/responses
6. **Audit Logging** - Detailed audit trail
