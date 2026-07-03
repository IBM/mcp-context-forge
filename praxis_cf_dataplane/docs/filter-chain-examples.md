# Filter Chain Execution Examples

This document provides detailed examples of how requests flow through the Praxis MCP dataplane filter pipeline.

## Architecture Overview

All MCP traffic flows through a single entry point: `/server/{server_id}/mcp`

The filter pipeline consists of:
1. **Praxis McpFilter** (built-in) - Protocol validation and JSON-RPC parsing
2. **cf_control_plane_data** (custom) - Fetch session and VS config from control plane
3. **CPEX Policy Filter #1** (Praxis built-in) - Pre-routing authorization
4. **cf_tools_router** (custom) - Routing decision (gateway vs upstream)
5. **CPEX Policy Filter #2** (Praxis built-in) - Post-routing authorization
6. **cf_mcp_broker** (custom) - Gateway execution (conditional)
7. **cf_upstream_proxy** (custom) - Upstream forwarding (conditional)

## Example 1: tools/list (Mixed Catalog)

### Scenario
A virtual server exposes 3 gateway tools and 2 upstream tools. The client requests the complete tool catalog.

### Request
```http
POST /server/vs-123/mcp HTTP/1.1
Host: gateway.example.com
Authorization: Bearer eyJhbGc...
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tools/list"
}
```

### Filter Execution Flow

#### 1. Praxis McpFilter
**Action:** Parse and validate request
```
Input:  Raw HTTP request body
Output: Parsed JSON-RPC envelope
```

**Metadata Written:**
- `mcp.method` = `"tools/list"`
- `mcp.jsonrpc_id` = `"req-1"`
- `mcp.jsonrpc_version` = `"2.0"`

**Result:** `Continue`

---

#### 2. cf_control_plane_data
**Action:** Fetch session and virtual server configuration

**Reads:**
- Authorization header: `Bearer eyJhbGc...`
- Request path: `/server/vs-123/mcp`

**gRPC Calls:**
```protobuf
# Authenticate user
Authenticate(token: "eyJhbGc...") → {
  session_id: "sess-abc123",
  user_email: "alice@example.com",
  teams: ["team-alpha", "team-beta"],
  is_admin: false
}

# Fetch virtual server config
GetVirtualServerConfig(virtual_server_id: "vs-123") → {
  virtual_server_id: "vs-123",
  tools: [
    {name: "get_weather", source: "gateway", gateway_id: "gw-1"},
    {name: "search_docs", source: "gateway", gateway_id: "gw-1"},
    {name: "send_email", source: "gateway", gateway_id: "gw-2"},
    {name: "fetch_data", source: "upstream", upstream_url: "http://data-mcp:8080/mcp"},
    {name: "query_db", source: "upstream", upstream_url: "http://db-mcp:8080/mcp"}
  ],
  access_policy: {
    allowed_teams: ["team-alpha", "team-beta", "team-gamma"]
  }
}
```

**Metadata Written:**
- `mcp.session_id` = `"sess-abc123"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`
- `mcp.is_admin` = `"false"`
- `mcp.virtual_server_id` = `"vs-123"`
- `mcp.virtual_server_tools` = `["get_weather", "search_docs", "send_email", "fetch_data", "query_db"]`
- `mcp.virtual_server_access_policy` = `{"allowed_teams": ["team-alpha", "team-beta", "team-gamma"]}`

**Result:** `Continue`

---

#### 3. CPEX Policy Filter #1
**Action:** Evaluate pre-routing authorization policies

**Reads:**
- `mcp.method` = `"tools/list"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`
- `mcp.virtual_server_access_policy` = `{"allowed_teams": [...]}`

**Policy Evaluation (OPA/Rego):**
```rego
package contextforge.pre_routing

default allow = false

# Allow tools/list if user has access to virtual server
allow {
    input.method == "tools/list"
    has_team_access
}

has_team_access {
    input.teams[_] in input.virtual_server_access_policy.allowed_teams
}

# Evaluation:
# input.method = "tools/list" ✓
# input.teams = ["team-alpha", "team-beta"]
# "team-alpha" in allowed_teams ✓
# Result: allow = true
```

**Result:** `Continue`

---

#### 4. cf_tools_router
**Action:** Determine routing strategy

**Reads:**
- `mcp.method` = `"tools/list"`
- `mcp.virtual_server_id` = `"vs-123"`

**Logic:**
- Method is `tools/list`
- Virtual server has mixed tool sources (gateway + upstream)
- Route to gateway broker (will merge catalogs)

**Metadata Written:**
- `mcp.route` = `"gateway"`
- `mcp.tool_sources` = `"gateway,upstream"` (for broker to merge)

**Result:** `Continue`

---

#### 5. CPEX Policy Filter #2
**Action:** Evaluate post-routing authorization policies

**Reads:**
- `mcp.route` = `"gateway"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`

**Policy Evaluation (OPA/Rego):**
```rego
package contextforge.post_routing

default allow = false

# Allow gateway route if user has access
allow {
    input.route == "gateway"
    # For tools/list, gateway access is implicitly granted
    # if user passed pre-routing authz
}

# Evaluation:
# input.route = "gateway" ✓
# Result: allow = true
```

**Result:** `Continue`

---

#### 6. cf_mcp_broker
**Action:** Execute tools/list with catalog merging

**Reads:**
- `mcp.route` = `"gateway"`
- `mcp.method` = `"tools/list"`
- `mcp.tool_sources` = `"gateway,upstream"`
- `mcp.virtual_server_id` = `"vs-123"`

**gRPC Calls:**
```protobuf
# Fetch gateway tools
ListGatewayTools(gateway_ids: ["gw-1", "gw-2"]) → {
  tools: [
    {name: "get_weather", description: "Get weather data", inputSchema: {...}},
    {name: "search_docs", description: "Search documentation", inputSchema: {...}},
    {name: "send_email", description: "Send email", inputSchema: {...}}
  ]
}

# Fetch upstream tools
ListUpstreamTools(upstream_urls: ["http://data-mcp:8080/mcp", "http://db-mcp:8080/mcp"]) → {
  tools: [
    {name: "fetch_data", description: "Fetch data from API", inputSchema: {...}},
    {name: "query_db", description: "Query database", inputSchema: {...}}
  ]
}
```

**Response Construction:**
```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "tools": [
      {
        "name": "get_weather",
        "description": "Get weather data",
        "inputSchema": {...}
      },
      {
        "name": "search_docs",
        "description": "Search documentation",
        "inputSchema": {...}
      },
      {
        "name": "send_email",
        "description": "Send email",
        "inputSchema": {...}
      },
      {
        "name": "fetch_data",
        "description": "Fetch data from API",
        "inputSchema": {...}
      },
      {
        "name": "query_db",
        "description": "Query database",
        "inputSchema": {...}
      }
    ]
  }
}
```

**Result:** `Reject(200, response_body)` (short-circuit with success)

---

#### 7. cf_upstream_proxy
**Action:** Skip (already responded)

**Logic:** Previous filter returned response, pipeline terminated

**Result:** Not executed

---

### Response
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "tools": [
      {"name": "get_weather", "description": "Get weather data", ...},
      {"name": "search_docs", "description": "Search documentation", ...},
      {"name": "send_email", "description": "Send email", ...},
      {"name": "fetch_data", "description": "Fetch data from API", ...},
      {"name": "query_db", "description": "Query database", ...}
    ]
  }
}
```

---

## Example 2: tools/call (Upstream Tool)

### Scenario
A client calls a tool that is backed by an external MCP server (not handled by the gateway).

### Request
```http
POST /server/vs-123/mcp HTTP/1.1
Host: gateway.example.com
Authorization: Bearer eyJhbGc...
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-2",
  "method": "tools/call",
  "params": {
    "name": "fetch_data",
    "arguments": {
      "endpoint": "/api/users",
      "limit": 10
    }
  }
}
```

### Filter Execution Flow

#### 1. Praxis McpFilter
**Action:** Parse and validate request

**Metadata Written:**
- `mcp.method` = `"tools/call"`
- `mcp.name` = `"fetch_data"`
- `mcp.jsonrpc_id` = `"req-2"`

**Result:** `Continue`

---

#### 2. cf_control_plane_data
**Action:** Fetch session and virtual server configuration

**gRPC Calls:**
```protobuf
Authenticate(token: "eyJhbGc...") → {
  session_id: "sess-abc123",
  user_email: "alice@example.com",
  teams: ["team-alpha", "team-beta"],
  is_admin: false
}

GetVirtualServerConfig(virtual_server_id: "vs-123") → {
  virtual_server_id: "vs-123",
  tools: [
    {name: "fetch_data", source: "upstream", upstream_url: "http://data-mcp:8080/mcp"},
    ...
  ],
  access_policy: {
    allowed_teams: ["team-alpha", "team-beta"]
  }
}
```

**Metadata Written:**
- `mcp.session_id` = `"sess-abc123"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`
- `mcp.virtual_server_id` = `"vs-123"`
- `mcp.virtual_server_tools` = `["fetch_data", ...]`
- `mcp.virtual_server_access_policy` = `{...}`

**Result:** `Continue`

---

#### 3. CPEX Policy Filter #1
**Action:** Evaluate pre-routing authorization

**Reads:**
- `mcp.method` = `"tools/call"`
- `mcp.name` = `"fetch_data"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`
- `mcp.virtual_server_tools` = `["fetch_data", ...]`

**Policy Evaluation:**
```rego
package contextforge.pre_routing

default allow = false

# Allow tools/call if tool is exposed and user has access
allow {
    input.method == "tools/call"
    input.name in input.virtual_server_tools
    has_team_access
}

has_team_access {
    input.teams[_] in input.virtual_server_access_policy.allowed_teams
}

# Evaluation:
# input.method = "tools/call" ✓
# input.name = "fetch_data"
# "fetch_data" in virtual_server_tools ✓
# "team-alpha" in allowed_teams ✓
# Result: allow = true
```

**Result:** `Continue`

---

#### 4. cf_tools_router
**Action:** Resolve tool to upstream server

**Reads:**
- `mcp.method` = `"tools/call"`
- `mcp.name` = `"fetch_data"`
- `mcp.virtual_server_id` = `"vs-123"`

**gRPC Call:**
```protobuf
ResolveToolCall(
  virtual_server_id: "vs-123",
  tool_name: "fetch_data"
) → {
  source: "upstream",
  upstream_url: "http://data-mcp:8080/mcp",
  upstream_tool_name: "fetch_data"
}
```

**Metadata Written:**
- `mcp.route` = `"upstream"`
- `mcp.upstream_url` = `"http://data-mcp:8080/mcp"`
- `mcp.upstream_tool` = `"fetch_data"`

**Result:** `Continue`

---

#### 5. CPEX Policy Filter #2
**Action:** Evaluate post-routing authorization

**Reads:**
- `mcp.route` = `"upstream"`
- `mcp.upstream_url` = `"http://data-mcp:8080/mcp"`
- `mcp.user_email` = `"alice@example.com"`
- `mcp.teams` = `"team-alpha,team-beta"`

**Policy Evaluation:**
```rego
package contextforge.post_routing

default allow = false

# Allow upstream route if user has access to upstream server
allow {
    input.route == "upstream"
    input.upstream_url in input.user_allowed_upstreams
}

# Evaluation:
# input.route = "upstream" ✓
# input.upstream_url = "http://data-mcp:8080/mcp"
# Check if user has access to this upstream server ✓
# Result: allow = true
```

**Result:** `Continue`

---

#### 6. cf_mcp_broker
**Action:** Skip (route != "gateway")

**Reads:**
- `mcp.route` = `"upstream"`

**Logic:** Route is not "gateway", skip this filter

**Result:** `Continue`

---

#### 7. cf_upstream_proxy
**Action:** Forward request to upstream MCP server

**Reads:**
- `mcp.route` = `"upstream"`
- `mcp.upstream_url` = `"http://data-mcp:8080/mcp"`
- `mcp.upstream_tool` = `"fetch_data"`
- Original request body

**HTTP Call:**
```http
POST http://data-mcp:8080/mcp HTTP/1.1
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-2",
  "method": "tools/call",
  "params": {
    "name": "fetch_data",
    "arguments": {
      "endpoint": "/api/users",
      "limit": 10
    }
  }
}
```

**Upstream Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "req-2",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Fetched 10 users from /api/users"
      }
    ]
  }
}
```

**Result:** `Reject(200, upstream_response)` (short-circuit with upstream response)

---

### Response
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "req-2",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Fetched 10 users from /api/users"
      }
    ]
  }
}
```

---

## Key Observations

### Separation of Data Fetching and Policy Evaluation

**cf_control_plane_data** (Filter #2):
- Fetches ALL required data from control plane
- Writes data to filter metadata
- Does NOT make authorization decisions
- Pure I/O operation

**CPEX Policy Filters** (Filters #3 and #5):
- Read data from filter metadata
- Evaluate policies (pure logic)
- Do NOT fetch data
- Stateless policy evaluation

### Two-Stage Authorization

Both examples demonstrate defense-in-depth security:

1. **Pre-Routing Authorization (CPEX #1)**
   - Checks if user can access the virtual server
   - Checks if tool is exposed on virtual server
   - Evaluated BEFORE routing decision

2. **Post-Routing Authorization (CPEX #2)**
   - Checks if user can access the gateway (if gateway route)
   - Checks if user can access the upstream server (if upstream route)
   - Evaluated AFTER routing decision

### Conditional Filter Execution

Filters check `mcp.route` metadata to determine if they should execute:
- `cf_mcp_broker` only runs when `mcp.route = "gateway"`
- `cf_upstream_proxy` only runs when `mcp.route = "upstream"`

### Short-Circuit Response

The executing filter (either `cf_mcp_broker` or `cf_upstream_proxy`) returns `Reject(200, response)` to short-circuit the pipeline and return the response immediately.

### Metadata Flow

Each filter reads metadata set by previous filters and writes new metadata for downstream filters. This creates a clear data flow through the pipeline without tight coupling between filters.

## Policy Examples

### Pre-Routing Policy (policies/pre_routing.rego)

```rego
package contextforge.pre_routing

import future.keywords.if
import future.keywords.in

default allow := false

# Allow tools/call if tool is exposed and user has team access
allow if {
    input.method == "tools/call"
    input.name in input.virtual_server_tools
    has_team_access
}

# Allow tools/list if user has team access
allow if {
    input.method == "tools/list"
    has_team_access
}

# Allow initialize and ping for all authenticated users
allow if {
    input.method in ["initialize", "ping"]
    input.user_email != ""
}

# Helper: Check if user has team access
has_team_access if {
    some team in input.teams
    team in input.virtual_server_access_policy.allowed_teams
}
```

### Post-Routing Policy (policies/post_routing.rego)

```rego
package contextforge.post_routing

import future.keywords.if
import future.keywords.in

default allow := false

# Allow gateway route if user has access to gateway
allow if {
    input.route == "gateway"
    # Gateway access is implicitly granted if user passed pre-routing authz
    # Additional gateway-specific checks can be added here
}

# Allow upstream route if user has access to upstream server
allow if {
    input.route == "upstream"
    input.upstream_url in input.user_allowed_upstreams
}

# Helper: Get user's allowed upstream servers
user_allowed_upstreams := upstreams if {
    # This would be populated by cf_control_plane_data
    # based on user's team memberships and upstream access policies
    upstreams := input.user_allowed_upstreams
}
```

## Debugging Tips

### Inspect Filter Metadata

Use Praxis's built-in metadata inspection to debug filter execution:

```bash
# Enable metadata logging
export PRAXIS_LOG_METADATA=true

# View metadata after each filter
curl -v http://localhost:8080/server/vs-123/mcp \
  -H "Authorization: Bearer eyJ..." \
  -H "X-Praxis-Debug: metadata" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list"}'
```

### Test Policies in Isolation

Use OPA's REPL to test policies:

```bash
# Start OPA REPL
opa run policies/

# Test pre-routing policy
> data.contextforge.pre_routing.allow with input as {
    "method": "tools/call",
    "name": "fetch_data",
    "user_email": "alice@example.com",
    "teams": ["team-alpha"],
    "virtual_server_tools": ["fetch_data"],
    "virtual_server_access_policy": {
      "allowed_teams": ["team-alpha"]
    }
  }
true
```

### Trace Filter Execution

Enable Praxis filter tracing:

```bash
# Enable filter tracing
export PRAXIS_TRACE_FILTERS=true

# View filter execution order and timing
curl http://localhost:8080/server/vs-123/mcp \
  -H "Authorization: Bearer eyJ..." \
  -H "X-Praxis-Trace: true" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list"}'
```