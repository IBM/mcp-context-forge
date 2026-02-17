# ADR-0041: GraphQL to MCP Translation

- *Status:* Accepted
- *Date:* 2026-02-17
- *Deciders:* Mihai Criveti

## Context

MCP Gateway already supports REST passthrough and gRPC-to-MCP translation (ADR-0038-style experimental feature). Many organizations expose their APIs via GraphQL, which provides a self-describing schema through its introspection system. To allow MCP clients to interact with GraphQL services without manual tool definitions, the gateway needs a GraphQL translation layer analogous to the existing gRPC support.

Key requirements:

- **Auto-discovery**: Use GraphQL's built-in introspection to discover queries, mutations, and their argument/return types automatically.
- **Dual-mode operation**: Support both a standalone CLI bridge (`translate_graphql.py`) and direct tool registration via `integration_type=GRAPHQL`.
- **Feature-flagged**: Follow the gRPC pattern — disabled by default, opt-in via `MCPGATEWAY_GRAPHQL_ENABLED`.
- **Depth control**: GraphQL schemas can be deeply nested; auto-generated field selections need a configurable depth limit.
- **Authentication**: Support bearer tokens, basic auth, and custom headers for upstream GraphQL endpoints.

## Decision

### 1. GraphQL Introspection → MCP Tool Mapping

The `GraphQLToMcpTranslator` class sends a standard introspection query to the GraphQL endpoint and:

- Extracts all `Query` and `Mutation` fields (optionally `Subscription`)
- Generates JSON Schema for each operation's input arguments using `GRAPHQL_SCALAR_TYPE_MAP`
- Builds optimized field selections respecting `max_depth` via `QueryBuilder`
- Exposes each operation as an MCP tool with name, description, and input schema

### 2. Dual-Mode Architecture

**CLI Bridge** (`python -m mcpgateway.translate_graphql`):

- Standalone process that introspects a GraphQL endpoint and serves discovered tools via HTTP/SSE
- Useful for quick integration without modifying gateway configuration
- Can be registered as an MCP gateway via `POST /gateways`

**Direct Registration** (`POST /tools` with `integration_type=GRAPHQL`):

- Register individual GraphQL operations as MCP tools
- Uses `graphql_operation`, `graphql_operation_type`, and `graphql_variables_mapping` fields
- Validated by schema-level validators that enforce field constraints per integration type

### 3. Database Schema Extension

New nullable columns on the `tools` table:

- `graphql_operation` (Text): The GraphQL query/mutation string
- `graphql_variables_mapping` (JSON): Maps MCP argument names to GraphQL variable names
- `graphql_field_selection` (Text): Auto-generated or custom field selection
- `graphql_operation_type` (String): `query`, `mutation`, or `subscription`

All columns are nullable and only populated for `integration_type=GRAPHQL`. An idempotent Alembic migration adds these columns.

### 4. Feature Flags

| Setting | Default | Purpose |
|---------|---------|---------|
| `MCPGATEWAY_GRAPHQL_ENABLED` | `false` | Master switch for GraphQL support |
| `MCPGATEWAY_GRAPHQL_INTROSPECTION_ENABLED` | `true` | Enable schema introspection by default |
| `MCPGATEWAY_GRAPHQL_MAX_DEPTH` | `3` | Maximum field selection depth |
| `MCPGATEWAY_GRAPHQL_TIMEOUT` | `30` | Default operation timeout (seconds) |
| `MCPGATEWAY_GRAPHQL_INCLUDE_MUTATIONS` | `true` | Include mutations in discovery |

## Consequences

### Positive

- **Seamless integration**: GraphQL APIs can be exposed as MCP tools with zero manual schema work
- **Consistent pattern**: Follows the established gRPC experimental feature pattern (feature flags, CLI bridge, direct registration)
- **Low risk**: Disabled by default; no impact on existing functionality
- **Self-describing**: Leverages GraphQL's introspection rather than requiring external schema files

### Negative

- **Introspection dependency**: Requires the upstream GraphQL server to have introspection enabled (many production servers disable it)
- **Depth trade-off**: Auto-generated field selections may be too shallow or too deep for specific use cases
- **No streaming**: GraphQL subscriptions (WebSocket-based) are not fully supported in this initial implementation
- **httpx dependency**: Uses `httpx` for HTTP, which is already a project dependency but adds to the GraphQL code path

## Alternatives Considered

### Manual Schema Registration Only

Register GraphQL tools manually via `POST /tools` with hand-written operations. Rejected because it eliminates the auto-discovery benefit and creates high friction for services with many operations.

### GraphQL Relay / SDL Parsing

Parse `.graphql` SDL files instead of using introspection. Rejected because it requires users to provide schema files separately, while introspection is always available at runtime and reflects the actual deployed schema.

### Proxy to Existing GraphQL Client Libraries

Use a full GraphQL client library (e.g., `gql`, `sgqlc`). Rejected because the translation layer needs only introspection and simple HTTP POST — `httpx` is sufficient and avoids heavy dependencies.

## Files Changed

- `mcpgateway/translate_graphql.py` — CLI bridge and translation logic
- `mcpgateway/schemas.py` — `GRAPHQL` integration type, GraphQL-specific fields, validators
- `mcpgateway/db.py` — GraphQL columns on `Tool` ORM model
- `mcpgateway/services/tool_service.py` — GraphQL field persistence in tool CRUD
- `mcpgateway/config.py` — Feature flag settings
- `mcpgateway/alembic/versions/x7h8i9j0k1l2_add_graphql_fields_to_tools.py` — Migration
- `tests/unit/mcpgateway/test_translate_graphql.py` — Unit tests
