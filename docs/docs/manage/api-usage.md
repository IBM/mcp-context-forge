# API Usage Guide

This guide provides comprehensive examples for using the MCP Gateway REST API via `curl` to perform common operations like managing gateways (MCP servers), tools, resources, prompts, and more.

## Prerequisites

Before using the API, you need to:

1. **Start the MCP Gateway server**:

    ```bash
    # Development server (port 8000, auto-reload)
    make dev

    # Production server (port 4444)
    make serve
    ```

2. **Generate a JWT authentication token**:

    ```bash
    # Generate token (replace secret with your JWT_SECRET_KEY from .env)
    export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
      --username admin@example.com \
      --exp 10080 \
      --secret my-test-key 2>/dev/null | head -1)

    # Verify token was generated
    echo "Token: ${TOKEN:0:50}..."
    ```

    !!! tip "Token Expiration"
        The `--exp` parameter sets token expiration in minutes. Use `--exp 0` for no expiration (development only).

3. **Set the base URL**:

    ```bash
    # Development server
    export BASE_URL="http://localhost:8000"

    # Production server
    export BASE_URL="http://localhost:4444"
    ```

## Authentication

All API requests require JWT Bearer token authentication:

```bash
curl -H "Authorization: Bearer $TOKEN" $BASE_URL/endpoint
```

## Pagination

!!! info "Default Pagination Behavior"
    For backward compatibility, **main API list endpoints return plain arrays by default**. Add `?include_pagination=true` to get paginated responses with cursor metadata. Admin API endpoints always return paginated responses.

### Pagination Methods

The API supports two pagination approaches:

1. **Cursor-based pagination** (Main API endpoints: `/tools`, `/servers`, `/gateways`, etc.)
   - Uses opaque cursors for efficient traversal
   - Best for real-time data and large datasets
   - No knowledge of total pages required

2. **Page-based pagination** (Admin API endpoints: `/admin/tools`, `/admin/servers`, etc.)
   - Uses page numbers and per-page limits
   - Provides total count and page information
   - Easier for UI components with page numbers

### Response Formats

**Main API (Cursor-based):**
```json
{
  "entities": [...],
  "nextCursor": "base64-encoded-cursor"
}
```

The entity key name matches the resource type: `tools`, `gateways`, `servers`, `resources`, `prompts`, or `agents`.

**Admin API (Page-based):**
```json
{
  "data": [...],
  "pagination": {
    "total_items": 150,
    "page": 1,
    "per_page": 50,
    "total_pages": 3
  },
  "links": {
    "first": "/admin/tools?page=1&per_page=50",
    "last": "/admin/tools?page=3&per_page=50",
    "next": "/admin/tools?page=2&per_page=50",
    "prev": null
  }
}
```

**Plain Array (default for Main API):**
```json
[...]
```

Add `?include_pagination=true` to main API endpoints to get paginated responses with cursor metadata.

### Pagination Parameters

**Main API (Cursor-based):**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `cursor` | Opaque pagination cursor for fetching next page | `null` (first page) |
| `limit` | Maximum items per page (0 = all) | 50 |
| `include_pagination` | Return paginated format with cursor | `false` |

**Admin API (Page-based):**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `page` | Page number (1-indexed) | 1 |
| `per_page` | Items per page | 50 |

### Examples

**Cursor-based pagination (Main API):**

```bash
# Default: plain array (first 50 items)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | jq '.'

# Enable pagination to get cursor metadata
curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/tools?include_pagination=true" | jq '.'

# Extract cursor and get next page
CURSOR=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/tools?include_pagination=true" | jq -r '.nextCursor')
curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/tools?include_pagination=true&cursor=$CURSOR" | jq '.'

# Get all items as plain array
curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/tools?limit=0" | jq '.'
```

**Page-based pagination (Admin API):**

```bash
# First page (default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/admin/tools | jq '.'

# Specific page with custom page size
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/tools?page=2&per_page=25" | jq '.'

# Loop through all pages
for page in {1..5}; do
  curl -s -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/admin/tools?page=$page&per_page=50" | jq '.data[]'
done
```

## Health & Status

### Check Server Health

```bash
# Basic health check
curl -s $BASE_URL/health | jq '.'
```

Expected output:

```json
{
  "status": "healthy"
}
```

### Check Readiness

```bash
# Readiness check (for load balancers)
curl -s $BASE_URL/ready | jq '.'
```

### Get Version Information

```bash
# Get server version and build info
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/version | jq '.'
```

## Gateway Management

Gateways represent upstream MCP servers or peer gateways that provide tools, resources, and prompts.

### List All Gateways

```bash
# First page - List gateways (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/gateways | jq '.'
```

**Response:**
```json
{
  "gateways": [
    {
      "id": "abc123",
      "name": "my-mcp-server",
      "url": "http://localhost:9000/mcp",
      "enabled": true,
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogImFiYzEyMyJ9"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/gateways?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogImFiYzEyMyJ9" | jq '.'

# Or loop through all pages programmatically
CURSOR=""
while true; do
  RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/gateways${CURSOR:+?cursor=$CURSOR}")
  echo "$RESPONSE" | jq '.gateways[]'
  CURSOR=$(echo "$RESPONSE" | jq -r '.nextCursor')
  [ "$CURSOR" == "null" ] && break
done
```

**Non-Paginated (Array Only):**
```bash
# Get simple array without pagination metadata
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/gateways?include_pagination=false" | jq '.'
```

### Get Gateway Details

```bash
# Get specific gateway by ID
export GATEWAY_ID="your-gateway-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/gateways/$GATEWAY_ID | jq '.'
```

### Register a New Gateway

```bash
# Register an MCP server gateway
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-mcp-server",
    "url": "http://localhost:9000/mcp",
    "description": "My custom MCP server",
    "transport": "STREAMABLEHTTP"
  }' \
  $BASE_URL/gateways | jq '.'
```

!!! note "Request Types"
    Supported `request_type` values:

    - `STREAMABLEHTTP`: HTTP/SSE-based MCP server
    - `SSE`: Server-Sent Events transport
    - `STDIO`: Standard I/O (for local processes)
    - `WEBSOCKET`: WebSocket transport

#### Complete Example: Registering a Gateway

```bash
# 1. Start an MCP server on port 9000 (in another terminal)
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000

# 2. Register the gateway
GATEWAY_RESPONSE=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "git-server",
    "url": "http://localhost:9000/mcp",
    "description": "Git operations MCP server",
    "transport": "STREAMABLEHTTP"
  }' \
  $BASE_URL/gateways)

# 3. Extract the gateway ID
export GATEWAY_ID=$(echo $GATEWAY_RESPONSE | jq -r '.id')
echo "Gateway ID: $GATEWAY_ID"
```

### Update Gateway

```bash
# Update gateway properties
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "updated-server-name",
    "description": "Updated description",
    "enabled": true
  }' \
  $BASE_URL/gateways/$GATEWAY_ID | jq '.'
```

### Enable/Disable Gateway

```bash
# Toggle gateway enabled status
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/gateways/$GATEWAY_ID/state?activate=false | jq '.'
```

### Delete Gateway

```bash
# Delete a gateway (warning: also deletes associated tools)
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/gateways/$GATEWAY_ID | jq '.'
```

## Tool Management

Tools are executable operations exposed by MCP servers through the gateway.

### List All Tools

```bash
# First page - List all available tools (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | jq '.'
```

**Response:**
```json
{
  "tools": [
    {
      "name": "get_weather",
      "description": "Get current weather",
      "gatewaySlug": "weather-api",
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInRvb2wxMjMifQ"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInRvb2wxMjMifQ" | jq '.'
```

**Non-Paginated (Array Only):**
```bash
# Get simple array without pagination metadata
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?include_pagination=false" | jq '.'

# Extract specific fields from array
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?include_pagination=false" | \
  jq '.[] | {name: .name, description: .description, gateway: .gatewaySlug}'
```

#### Filtering and Pagination

The `/tools` endpoint supports several query parameters for filtering and pagination:

| Parameter | Description |
|-----------|-------------|
| `gateway_id` | Filter by gateway ID. Use `null` to match tools without a gateway. |
| `tags` | Comma-separated list of tags to filter by (matches any). |
| `visibility` | Filter by visibility: `private`, `team`, or `public`. |
| `team_id` | Filter by team ID. |
| `include_inactive` | Include disabled tools (default: `false`). |
| `limit` | Maximum tools to return. Use `0` for all tools (no limit). Default: 50. |
| `cursor` | Pagination cursor for fetching the next page. |
| `include_pagination` | Return paginated format with cursor (default: `true`). Set to `false` for array only. |

**Examples:**

```bash
# Filter by gateway (paginated)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?gateway_id=<gateway-id>" | jq '.'

# Filter by tags (paginated)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?tags=api,data" | jq '.'

# Get up to 100 tools per page
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?limit=100" | jq '.'

# Get ALL tools (no pagination - returns all as array)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?limit=0&include_pagination=false" | jq '.'

# Navigate to next page using cursor
NEXT=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/tools" | jq -r '.nextCursor')
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?cursor=$NEXT" | jq '.'
```

### Get Tool Details

```bash
# Get specific tool by ID
export TOOL_ID="your-tool-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools/$TOOL_ID | jq '.'

# View tool's input schema
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools/$TOOL_ID | jq '.inputSchema'

# View tool's output schema
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools/$TOOL_ID | jq '.outputSchema'
```

### Register a Custom Tool

```bash
# Register a tool manually (for REST APIs, custom integrations)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": {
      "name": "weather-api",
      "description": "Get weather information for a city",
      "url": "https://api.weather.com/v1/current",
      "integration_type": "REST",
      "request_type": "POST",
      "input_schema": {
        "type": "object",
        "properties": {
          "city": {
            "type": "string",
            "description": "City name"
          }
        },
        "required": [
          "city"
        ]
      }
    }
  }' \
  $BASE_URL/tools | jq '.'
```

### Invoke a Tool

```bash
export TOOL_NAME="your-tool-name"
# Execute a tool with arguments
jq -n --arg name "$TOOL_NAME" --argjson args '{"param1":"value1","param2":"value2"}' \
  '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":$name,"arguments":$args}}' |
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- "$BASE_URL/rpc" | jq '.result.content[0].text'
```

#### Complete Example: Tool Invocation

```bash
# 1. List tools and find one to test
TOOLS=$(curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools)
export TOOL_ID=$(echo $TOOLS | jq -r '.[0].id')
export TOOL_NAME=$(echo $TOOLS | jq -r '.[0].name')

echo "Testing tool: $TOOL_NAME (ID: $TOOL_ID)"

# 2. View the tool's input schema
echo "Input schema:"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools/$TOOL_ID | jq '.inputSchema'

# 3. Invoke the tool
jq -n --arg name "$TOOL_NAME" --argjson args '{"param1":"test_value"}' \
  '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":$name,"arguments":$args}}' |
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- "$BASE_URL/rpc" | jq '.result.content[0].text'
```

### Update Tool

```bash
# Update tool properties
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated tool description",
    "enabled": true
  }' \
  $BASE_URL/tools/$TOOL_ID | jq '.'
```

### Enable/Disable Tool

```bash
# Toggle tool enabled status
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/tools/$TOOL_ID/state?activate=false | jq '.'
```

### Delete Tool

```bash
# Delete a tool
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/tools/$TOOL_ID | jq '.'
```

## Virtual Server Management

Virtual servers allow you to compose multiple MCP servers and tools into unified service endpoints.

### List All Servers

```bash
# First page - List all virtual servers (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/servers | jq '.'
```

**Response:**
```json
{
  "servers": [
    {
      "id": "server123",
      "name": "my-virtual-server",
      "description": "Combined MCP endpoints",
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInNlcnZlcjEyMyJ9"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/servers?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInNlcnZlcjEyMyJ9" | jq '.'
```

**Non-Paginated:**
```bash
# Get simple array
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/servers?include_pagination=false" | jq '.'
```

### Create Virtual Server

```bash
# Create a new virtual server
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
  "server": {
    "name": "my-virtual-server",
    "description": "Composed server with multiple tools",
    "associated_tools": ["'$TOOL_ID'"]
    }
  }' \
  $BASE_URL/servers | jq '.'
```

### Get Server Details

```bash
# Get specific server
export SERVER_ID="your-server-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/servers/$SERVER_ID | jq '.'
```



#### Complete Example: Virtual Server Creation

```bash
# 1. Get tools IDs to associate
TOOLS=$(curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools)
export TOOL1_ID=$(echo $TOOLS | jq -r '.[0].id')
export TOOL2_ID=$(echo $TOOLS | jq -r '.[1].id')

# 2. Create virtual server with multiple gateways
SERVER_RESPONSE=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
  "server": {
    "name": "my-virtual-server",
    "description": "Composed server with multiple tools",
    "associated_tools": ["'$TOOL1_ID'", "'$TOOL2_ID'"]
    }
  }' \
  $BASE_URL/servers)

export SERVER_ID=$(echo $SERVER_RESPONSE | jq -r '.id')
echo "Server ID: $SERVER_ID"
```

### List Server Tools

```bash
# Get all tools available through a server
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/tools | jq '.'
```

### List Server Resources

```bash
# Get all resources available through a server
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/resources | jq '.'
```

### List Server Prompts

```bash
# Get all prompts available through a server
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/prompts | jq '.'
```

### Connect to Server via SSE

```bash
# Connect to server using Server-Sent Events
curl -N -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/sse
```

### Update Server

```bash
# Update virtual server
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "updated-server",
    "description": "Updated description",
    "enabled": true
  }' \
  $BASE_URL/servers/$SERVER_ID | jq '.'
```

### Enable/Disable Server

```bash
# Toggle server enabled status
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/state?activate=false | jq '.'
```

### Delete Server

```bash
# Delete virtual server
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID | jq '.'
```

## Resource Management

Resources are data sources (files, documents, database queries) exposed by MCP servers.

### List All Resources

```bash
# First page - List all available resources (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/resources | jq '.'
```

**Paginated Response:**
```json
{
  "resources": [
    {
      "uri": "file:///data/config.json",
      "name": "Application Config",
      "mimeType": "application/json",
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInJlczEyMyJ9"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/resources?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInJlczEyMyJ9" | jq '.'
```

**Non-Paginated:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/resources?include_pagination=false" | jq '.'
```

### Register a Resource

```bash
# Register a new resource
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '
  {"resource":
    {
      "name": "config-file",
      "uri": "file:///etc/config.json",
      "description": "Application configuration file",
      "mime_type": "application/json",
      "content": "{'key': 'value'}"
    }
  }' \
  $BASE_URL/resources | jq '.'
```

### Get Resource Details

```bash
# Get specific resource
export RESOURCE_ID="your-resource-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/resources/$RESOURCE_ID | jq '.'
```


### Read Resource Content

```bash
# Get resource content
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/$RESOURCE_ID | jq '.text'
```

### Subscribe to Resource Updates

```bash
# Subscribe to resource change notifications
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/subscribe/$RESOURCE_ID | jq '.'
```

### List Resource Templates

```bash
# Get available resource templates
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/templates/list | jq '.'
```

### Update Resource

```bash
# Update resource metadata
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated description",
    "mime_type": "text/plain"
  }' \
  $BASE_URL/resources/$RESOURCE_ID | jq '.'
```

### Enable/Disable Resource

```bash
# Toggle resource enabled status
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/$RESOURCE_ID/state?activate=false | jq '.'
```

### Delete Resource

```bash
# Delete resource
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/$RESOURCE_ID | jq '.'
```

## Prompt Management

Prompts are reusable templates with arguments for AI interactions.

### List All Prompts

```bash
# First page - List all available prompts (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/prompts | jq '.'
```

**Paginated Response:**
```json
{
  "prompts": [
    {
      "name": "code_review",
      "description": "Review code for best practices",
      "arguments": [...],
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInByb21wdDEyMyJ9"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/prompts?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogInByb21wdDEyMyJ9" | jq '.'
```

**Non-Paginated:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/prompts?include_pagination=false" | jq '.'
```

### Register a Prompt

```bash
# Register a new prompt template
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": {
      "name": "code-review",
      "description": "Review code for best practices",
      "template": "Review the following code and suggest improvements:\n\n{{code}}",
      "arguments": [
        {
          "name": "code",
          "description": "Code to review",
          "required": true
        }
      ]
    }
  }' \
  $BASE_URL/prompts | jq '.'
```

### Get Prompt Details

```bash
# Get specific prompt
export PROMPT_ID="your-prompt-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/prompts/$PROMPT_ID | jq '.'
```

### Execute Prompt (Get Rendered Content)

```bash
# Execute prompt with arguments
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def hello():\n    print(\"Hello\")"
  }' \
  $BASE_URL/prompts/$PROMPT_ID | jq '.'
```

### Update Prompt

```bash
# Update prompt template
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated prompt description",
    "content": "New template: {{variable}}"
  }' \
  $BASE_URL/prompts/$PROMPT_ID | jq '.'
```

### Enable/Disable Prompt

```bash
# Toggle prompt enabled status
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/prompts/$PROMPT_ID/state?activate=false | jq '.'
```

### Delete Prompt

```bash
# Delete prompt
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/prompts/$PROMPT_ID | jq '.'
```

## Tag Management

Tags organize and categorize gateway resources.

### List All Tags

```bash
# List all available tags
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tags?entity_types=gateways%2Cservers%2Ctools%2Cresources%2Cprompts&include_entities=false" \
| jq '.'
```

### Get Tag Entities

```bash
# Get specific tag
export TAG_NAME="your-tag-name"
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tags/$TAG_NAME/entities" \
| jq '.'
```

## Bulk Operations

### Export Configuration

```bash
# Export all gateway configuration
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/export | jq '.' > gateway-export.json

# Export specific entities
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/export?types=tools%2Cgateways" | \
  jq '.' > partial-export.json
```

### Import Configuration

```bash
# Import configuration from file
payload=$(jq -n \
  --arg conflict "skip" \
  --argjson dry_run false \
  --argjson import_data "$(cat gateway-export.json)" '
  {
    conflict_strategy: $conflict,
    dry_run: $dry_run,
    import_data: $import_data
  }')

curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$BASE_URL/import" | jq '.'
```

### Bulk Import Tools

```bash
# Import multiple tools at once
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conflict_strategy": "update",
    "dry_run": false,
    "import_data": {
      "version": "2025-03-26",
      "exported_at": "2025-10-24T18:41:55.776238Z",
      "exported_by": "admin@example.com",
      "source_gateway": "http://0.0.0.0:4444",
      "encryption_method": "AES-256-GCM",
      "entities": {
        "tools": [
          {
            "name": "tool1",
            "displayName": "tool1",
            "url": "http://example.com/api1",
            "integration_type": "REST",
            "request_type": "POST",
            "description": "First tool",
            "headers": {},
            "input_schema": {
              "type": "object",
              "properties": {
                "param": { "type": "string", "description": "Parameter name" }
              },
              "required": ["param"]
            }
          },
          {
            "name": "tool2",
            "displayName": "tool2",
            "url": "http://example.com/api2",
            "integration_type": "REST",
            "request_type": "GET",
            "description": "Second tool",
            "headers": {},
            "input_schema": {
              "type": "object",
              "properties": {
                "query": { "type": "string", "description": "Query string" }
              },
              "required": ["query"]
            }
          }
        ]
      }
    },
    "rekey_secret": null
  }' \
  "$BASE_URL/import" | jq '.'
```

## A2A Agent Management

A2A (Agent-to-Agent) enables integration with external AI agents.

!!! note "A2A Feature Flag"
    A2A features must be enabled via `MCPGATEWAY_A2A_ENABLED=true` in your `.env` file.

### List All A2A Agents

```bash
# First page - List registered A2A agents (paginated response - default)
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/a2a | jq '.'
```

**Paginated Response:**
```json
{
  "agents": [
    {
      "id": "agent123",
      "name": "data-analyzer",
      "url": "https://agent.example.com/v1",
      ...
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogImFnZW50MTIzIn0"
}
```

```bash
# Second page - Use cursor from first response
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/a2a?cursor=eyJjcmVhdGVkX2F0IjogIjIwMjQtMDEtMDFUMTI6MDA6MDBaIiwgImlkIjogImFnZW50MTIzIn0" | jq '.'
```

**Non-Paginated:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/a2a?include_pagination=false" | jq '.'
```

### Register A2A Agent

```bash
# Register an OpenAI agent
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent": {
      "name": "openai-assistant",
      "agent_type": "openai",
      "endpoint_url": "https://api.openai.com/v1/chat/completions",
      "description": "OpenAI GPT-4 assistant",
      "auth_type": "bearer",
      "auth_value": "OPENAI_API_KEY"
    }
  }' \
  $BASE_URL/a2a | jq '.'
```

### Get A2A Agent Details

```bash
# Get specific agent
export A2A_ID="your-agent-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/a2a/$A2A_ID | jq '.'
```

### Invoke A2A Agent

```bash
# Execute agent with message
export A2A_NAME="openai-assistant"

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain quantum computing in simple terms"
  }' \
  $BASE_URL/a2a/$A2A_NAME/invoke | jq '.'
```

### Update A2A Agent

```bash
# Update agent configuration
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4-turbo",
    "description": "Updated to use GPT-4 Turbo"
  }' \
  $BASE_URL/a2a/$A2A_ID | jq '.'
```

### Delete A2A Agent

```bash
# Delete A2A agent
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/a2a/$A2A_ID | jq '.'
```

## OpenAPI Specification

### Get OpenAPI Schema

```bash
# Get full OpenAPI specification
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/openapi.json | jq '.'

# Save OpenAPI spec to file
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/openapi.json > openapi.json
```

### Interactive API Documentation

Access interactive Swagger UI documentation:

```
http://localhost:8000/docs
```

Access ReDoc documentation:

```
http://localhost:8000/redoc
```

## End-to-End Workflow Example

This complete example demonstrates a typical workflow: registering a gateway, discovering tools, and invoking them.

```bash
#!/bin/bash

# Configuration
export BASE_URL="http://localhost:8000"
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret my-test-key 2>/dev/null | head -1)

echo "=== MCP Gateway E2E Test ==="
echo

# 1. Check health
echo "1. Checking gateway health..."
curl -s $BASE_URL/health | jq '.'
echo

# 2. Register a new gateway
echo "2. Registering MCP server gateway..."
GATEWAY=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-server",
    "url": "http://localhost:9000/mcp",
    "description": "Test MCP server",
    "transport": "STREAMABLEHTTP"
  }' \
  $BASE_URL/gateways)

export GATEWAY_ID=$(echo $GATEWAY | jq -r '.id')
echo "Gateway ID: $GATEWAY_ID"
echo

# 3. List all gateways
echo "3. Listing all gateways..."
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/gateways | \
  jq '.[] | {id: .id, name: .name, enabled: .enabled}'
echo

# 4. Discover tools from the gateway
echo "4. Discovering tools..."
sleep 2  # Wait for gateway to sync
TOOLS=$(curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools)
export TOOL_ID=$(echo $TOOLS | jq -r '.[0].id')
export TOOL_NAME=$(echo $TOOLS | jq -r '.[0].name')
echo "Found tools:"
echo $TOOLS | jq '.[] | {name: .name, description: .description}' | head -20
echo

# 5. Get tool details
echo "5. Getting tool details for: $TOOL_ID"
TOOL_DETAILS=$(curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/tools/$TOOL_ID)
echo $TOOL_DETAILS | jq '{name: .name, description: .description, inputSchema: .inputSchema}'
echo

# 6. Invoke the tool
echo "6. Invoking tool: $TOOL_NAME"
RESULT=$(jq -n --arg name "$TOOL_NAME" --argjson args '{"param1":"test_value"}' \
  '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":$name,"arguments":$args}}' |
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- "$BASE_URL/rpc")
echo $RESULT | jq '.'
echo

# 7. Create a virtual server
echo "7. Creating virtual server..."
SERVER=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
  "server": {
    "name": "test-virtual-server",
    "description": "Unified server for testing",
    "associated_tools": ["'$TOOL_ID'"]
    }
  }' \
  $BASE_URL/servers)

export SERVER_ID=$(echo $SERVER | jq -r '.id')
echo "Server ID: $SERVER_ID"
echo

# 8. List server tools
echo "8. Listing tools available through virtual server..."
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/servers/$SERVER_ID/tools | \
  jq '.[] | {name: .name}' | head -10
echo

# 9. Export configuration
echo "9. Exporting gateway configuration..."
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/export | \
  jq '{gateways: .entities.gateways | length, tools: .entities.tools | length}' > export-summary.json
cat export-summary.json
echo

echo "=== E2E Test Complete ==="
```

## Error Handling

### Common Error Responses

#### 401 Unauthorized

```json
{
  "detail": "Authorization token required"
}
```

**Solution**: Ensure you're sending the `Authorization: Bearer $TOKEN` header.

#### 404 Not Found

```json
{
  "detail": "Tool not found"
}
```

**Solution**: Verify the resource ID exists using the list endpoint.

#### 422 Validation Error

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Solution**: Check request payload matches the required schema.

### Debug Mode

Enable verbose output for troubleshooting:

```bash
# Show full request/response including headers
curl -v -H "Authorization: Bearer $TOKEN" $BASE_URL/tools

# Save full response with headers
curl -i -H "Authorization: Bearer $TOKEN" $BASE_URL/tools > response.txt
```

## Best Practices

1. **Token Management**

    - Store tokens securely, never commit to version control
    - Use short expiration times in production
    - Rotate tokens regularly

2. **Error Handling**

    - Always check HTTP status codes
    - Parse error messages from response body
    - Implement retry logic for transient failures

3. **Performance**

    - Use pagination for large result sets
    - Cache frequently accessed data
    - Leverage HTTP compression (automatically enabled)

4. **Security**

    - Use HTTPS in production (not HTTP)
    - Validate SSL certificates
    - Never log sensitive tokens or API keys

5. **Testing**

    - Test against development server first
    - Use unique names for test resources
    - Clean up test data after experiments

## Advanced Usage

### Using jq for Advanced Filtering

```bash
# Get only enabled tools
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | \
  jq '[.[] | select(.enabled == true)]'

# Count tools by gateway
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | \
  jq 'group_by(.gatewaySlug) | map({gateway: .[0].gatewaySlug, count: length})'

# Extract specific fields
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | \
  jq '[.[] | {id, name, description, enabled}]'
```

### Batch Operations Script

```bash
#!/bin/bash
# batch-enable-tools.sh - Enable all tools from a specific gateway

export TOKEN="your-token"
export BASE_URL="http://localhost:8000"
export GATEWAY_SLUG="my-gateway"

# Get all tools from the gateway
TOOLS=$(curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | \
  jq -r '.[] | select(.gatewaySlug == "'$GATEWAY_SLUG'") | .id')

# Enable each tool
for TOOL_ID in $TOOLS; do
  echo "Enabling tool: $TOOL_ID"
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    $BASE_URL/tools/$TOOL_ID/state > /dev/null
done

echo "Done!"
```

## Related Documentation

- [Configuration Guide](configuration.md) - Environment variables and settings
- [Bulk Import](bulk-import.md) - Import large datasets
- [Export/Import](export-import.md) - Backup and migration
- [Securing the Gateway](securing.md) - Security best practices
- [OAuth Configuration](oauth.md) - OAuth 2.0 setup
- [SSO Integration](sso.md) - Single Sign-On setup

## Support

For issues or questions:

- [GitHub Issues](https://github.com/cmihai/mcp-context-forge/issues)
- [Documentation](https://mcpgateway.org)
- [API Reference](/openapi.json)
