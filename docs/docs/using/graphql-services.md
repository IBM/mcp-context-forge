# GraphQL Services (Experimental)

!!! warning "Experimental Feature"
    GraphQL support is an **experimental opt-in feature** that is disabled by default. It requires `httpx` and explicit enablement via feature flag.

MCP Gateway supports automatic translation of GraphQL APIs into MCP tools via GraphQL's built-in introspection system. This enables seamless integration of GraphQL services into your MCP ecosystem without manual schema definition.

## Installation & Setup

### 1. Install Dependencies

GraphQL support uses `httpx` for HTTP communication. It is included in the default installation:

```bash
# httpx is included by default
pip install mcp-contextforge-gateway

# Or explicitly with uv
uv pip install httpx
```

### 2. Enable the Feature

Set the environment variable to enable GraphQL support:

```bash
# In .env file
MCPGATEWAY_GRAPHQL_ENABLED=true

# Or export in shell
export MCPGATEWAY_GRAPHQL_ENABLED=true

# Or set in docker-compose.yml
environment:
  - MCPGATEWAY_GRAPHQL_ENABLED=true
```

### 3. Restart the Gateway

After enabling the feature, restart MCP Gateway:

```bash
# Development mode
make dev

# Production mode
mcpgateway

# Or with Docker
docker restart mcpgateway
```

## Overview

The GraphQL-to-MCP translation feature allows you to:

- **Automatically discover** GraphQL queries and mutations via schema introspection
- **Expose GraphQL operations** as MCP tools with zero configuration
- **Translate protocols** between GraphQL and MCP/JSON
- **Control field depth** to limit response size and complexity
- **Support authentication** via bearer tokens, basic auth, or custom headers

## Quick Start

### 1. CLI: Expose a GraphQL API

The simplest way to expose a GraphQL API is via the CLI bridge:

```bash
# Basic usage - expose GraphQL API as MCP tools via SSE at :9001
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql --port 9001

# With bearer token authentication
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --auth-type bearer --auth-value "your-token" --port 9001

# With field depth control and no mutations
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --max-depth 4 --no-include-mutations --port 9001
```

### 2. Direct Registration: POST /tools

Register a GraphQL tool directly via the REST API:

```bash
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "name": "get-users",
    "description": "Fetch users from the GraphQL API",
    "integration_type": "GRAPHQL",
    "url": "https://api.example.com/graphql",
    "request_type": "POST",
    "graphql_operation": "query GetUsers($limit: Int) { users(limit: $limit) { id name email } }",
    "graphql_operation_type": "query",
    "graphql_variables_mapping": {"limit": "limit"},
    "inputSchema": {
      "type": "object",
      "properties": {
        "limit": {"type": "integer", "description": "Maximum number of users to return"}
      }
    }
  }'
```

## How It Works

### Schema Introspection

When you use the CLI bridge, the translator:

1. **Connects** to the GraphQL endpoint
2. **Sends** a standard introspection query to discover the schema
3. **Parses** query and mutation types, their arguments, and return types
4. **Generates** JSON Schema for each operation's input parameters
5. **Builds** optimized field selections respecting the configured max depth
6. **Exposes** each operation as an MCP tool via HTTP/SSE

### Protocol Translation

```
┌─────────────┐         ┌──────────────┐         ┌─────────────────┐
│  MCP Client │────────▶│  MCP Gateway │────────▶│ GraphQL Server  │
│  (JSON)     │  HTTP   │  (Translate) │  HTTP   │ (GraphQL)       │
└─────────────┘         └──────────────┘         └─────────────────┘
                              │
                              ▼
                        [Introspection]
                        Discover queries,
                        mutations, types
```

**Request Flow:**

1. Client calls MCP tool: `query_users`
2. Gateway looks up the GraphQL operation and field selections
3. Gateway constructs the GraphQL query with variables from tool arguments
4. Gateway sends HTTP POST to the GraphQL endpoint
5. Gateway extracts the data from the GraphQL response
6. Gateway returns JSON result to MCP client

## Configuration

### Environment Variables

```bash
# Enable/disable GraphQL support globally
MCPGATEWAY_GRAPHQL_ENABLED=true

# Enable schema introspection by default
MCPGATEWAY_GRAPHQL_INTROSPECTION_ENABLED=true

# Maximum field selection depth (controls query complexity)
MCPGATEWAY_GRAPHQL_MAX_DEPTH=3

# Default timeout for GraphQL operations (seconds)
MCPGATEWAY_GRAPHQL_TIMEOUT=30

# Include mutations when discovering tools
MCPGATEWAY_GRAPHQL_INCLUDE_MUTATIONS=true
```

### Tool Registration Fields

When registering GraphQL tools directly via `POST /tools`, the following fields are available:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `integration_type` | string | Yes | Must be `"GRAPHQL"` |
| `url` | string | Yes | GraphQL endpoint URL |
| `graphql_operation` | string | No | GraphQL operation string (query/mutation) |
| `graphql_operation_type` | string | No | `"query"`, `"mutation"`, or `"subscription"` |
| `graphql_variables_mapping` | object | No | Maps MCP argument names to GraphQL variable names |
| `request_type` | string | Yes | Must be `"POST"` for GraphQL |

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--endpoint` | (required) | GraphQL endpoint URL |
| `--port` | `9001` | HTTP/SSE port to listen on |
| `--host` | `127.0.0.1` | Bind address |
| `--auth-type` | (none) | Authentication type: `bearer`, `basic`, or `header` |
| `--auth-value` | (none) | Authentication credential value |
| `--max-depth` | `3` | Max field selection depth |
| `--include-mutations` | `true` | Include mutations as tools |
| `--no-include-mutations` | - | Exclude mutations |
| `--include-subscriptions` | `false` | Include subscriptions as tools |
| `--cache-ttl` | `3600` | Introspection cache TTL in seconds |
| `--log-level` | `INFO` | Log level |

## Security Considerations

### Authentication Headers

Pass authentication credentials to the GraphQL endpoint:

```bash
# Bearer token
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --auth-type bearer --auth-value "your-jwt-token"

# Basic auth
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --auth-type basic --auth-value "user:password"

# Custom header
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --auth-type header --auth-value "X-API-Key: secret"
```

### TLS

GraphQL endpoints using HTTPS are supported natively via `httpx`. Ensure the server's TLS certificate is valid or configure custom CA certificates as needed.

### Depth Limiting

Use `--max-depth` (CLI) or `MCPGATEWAY_GRAPHQL_MAX_DEPTH` (env) to control how deep field selections go. Lower values reduce response size and prevent overly complex queries against the upstream GraphQL server.

## Examples

### Example 1: Expose a Public GraphQL API

```bash
# Expose the SpaceX GraphQL API as MCP tools
python3 -m mcpgateway.translate_graphql \
    --endpoint https://spacex-production.up.railway.app/graphql \
    --port 9001

# Now accessible at:
# http://localhost:9001/sse
```

### Example 2: Register a Specific Query as a Tool

```bash
# Register a single GraphQL query as an MCP tool
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "search-repositories",
    "description": "Search GitHub repositories via GraphQL",
    "integration_type": "GRAPHQL",
    "url": "https://api.github.com/graphql",
    "request_type": "POST",
    "graphql_operation": "query SearchRepos($query: String!) { search(query: $query, type: REPOSITORY, first: 10) { nodes { ... on Repository { name description stargazerCount } } } }",
    "graphql_operation_type": "query",
    "graphql_variables_mapping": {"query": "query"},
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query string"}
      },
      "required": ["query"]
    }
  }'
```

### Example 3: Auto-Discover and Register via Gateway

```bash
# 1. Start the GraphQL bridge
python3 -m mcpgateway.translate_graphql \
    --endpoint https://api.example.com/graphql \
    --auth-type bearer --auth-value "token" \
    --port 9001

# 2. Register the bridge as a gateway
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "graphql-service",
    "url": "http://localhost:9001/sse",
    "description": "GraphQL API exposed as MCP tools"
  }'
```

## Limitations

### Current Limitations

1. **Subscriptions**: GraphQL subscriptions are not fully supported (WebSocket transport)
2. **File Uploads**: GraphQL multipart uploads are not supported
3. **Fragments**: Complex fragment spreads may have limited support in auto-discovery
4. **Unions/Interfaces**: Inline fragments on union/interface types use simplified field selection

### Planned Enhancements

- Admin UI tab for GraphQL service management
- WebSocket subscription support
- Advanced type mapping for unions and interfaces
- Batch query support
- Schema change detection and auto-reload

## Related Documentation

- [mcpgateway.translate CLI](mcpgateway-translate.md)
- [gRPC Services (Experimental)](grpc-services.md)
- [Configuration Reference](../manage/configuration.md)
- [REST API Reference](../manage/api-usage.md)
