# Tool Annotations

Tool annotations provide metadata hints about tool behavior, helping clients and UIs make informed decisions about how to present and use tools. MCP Gateway supports the standard MCP annotation types for enhanced tool interaction.

## Overview

Tool annotations are optional metadata that can be attached to tools to provide behavioral hints such as:

- **Safety indicators**: Whether a tool is read-only or potentially destructive
- **Execution hints**: Whether a tool is idempotent or operates in an open-world assumption
- **UI hints**: How tools should be presented in user interfaces

## Supported Annotation Types

| Annotation | Type | Description |
|------------|------|-------------|
| `readOnlyHint` | `boolean` | Indicates the tool only reads data and doesn't modify state |
| `destructiveHint` | `boolean` | Warns that the tool may cause irreversible changes |
| `idempotentHint` | `boolean` | Indicates the tool can be called multiple times safely |
| `openWorldHint` | `boolean` | Suggests the tool operates under open-world assumptions |

## Setting Annotations via Admin UI

Use the Admin UI to set tool annotations through the web interface:

1. Navigate to **Tools** section in the Admin UI
2. Click **Edit** on the desired tool
3. In the **Annotations** field, enter JSON:

```json
{
  "readOnlyHint": true,
  "destructiveHint": false,
  "idempotentHint": true,
  "openWorldHint": false
}
```

4. Click **Save** to persist the annotations

## Setting Annotations via API

### Complete Annotation Example

Here's a comprehensive example showing all available annotation types:

```bash
curl -X POST /tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "file-reader",
    "url": "http://example.com/api/read-file",
    "description": "Safely reads file contents",
    "annotations": {
      "readOnlyHint": true,
      "destructiveHint": false,
      "idempotentHint": true,
      "openWorldHint": false
    }
  }'
```

### Individual Annotation Examples

#### Read-Only Tool
```json
{
  "name": "get-user-info",
  "url": "http://api.example.com/users",
  "annotations": {
    "readOnlyHint": true
  }
}
```

#### Destructive Tool
```json
{
  "name": "delete-file",
  "url": "http://api.example.com/files/delete",
  "annotations": {
    "destructiveHint": true,
    "idempotentHint": false
  }
}
```

#### Idempotent Tool
```json
{
  "name": "create-user",
  "url": "http://api.example.com/users",
  "annotations": {
    "idempotentHint": true,
    "readOnlyHint": false
  }
}
```

### Updating Existing Tool Annotations

```bash
curl -X PUT /tools/{tool_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "annotations": {
      "readOnlyHint": true,
      "destructiveHint": false
    }
  }'
```

## Gateway-Discovered Tools

When registering MCP servers via `/gateways`, tools are automatically discovered. To add annotations:

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

Set a base URL for the gateway API:

```bash
export BASE_URL="http://localhost:4444"
# export BASE_URL="http://localhost:8080"  # docker-compose with nginx
```

### Step 1: Register the Gateway
```bash
curl -X POST $BASE_URL/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "my-mcp-server",
    "url": "http://localhost:8080/sse"
  }'
```

### Step 2: Add Annotations to Discovered Tools
```bash
# First, get the tool ID from the tools list
curl -H "Authorization: Bearer $TOKEN" $BASE_URL/tools

# Then update the specific tool with annotations
curl -X PUT $BASE_URL/tools/{discovered_tool_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "annotations": {
      "readOnlyHint": true,
      "destructiveHint": false,
      "idempotentHint": true
    }
  }'
```

## Complex Annotation Scenarios

### Mixed Safety Tool
A tool that reads configuration but may modify cache:

```json
{
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  }
}
```

### High-Risk Administrative Tool
A tool that performs system-level operations:

```json
{
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "idempotentHint": false,
    "openWorldHint": false
  }
}
```

### Information Gathering Tool
A tool that queries external APIs safely:

```json
{
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  }
}
```

## Best Practices

### 1. **Be Conservative with Safety Hints**
- Default to `destructiveHint: true` if uncertain
- Only set `readOnlyHint: true` for genuinely safe operations

### 2. **Consider Idempotency Carefully**
- Set `idempotentHint: true` only if multiple calls are truly safe
- Database writes are typically not idempotent unless using upsert patterns

### 3. **Use Open-World Hints Appropriately**
- Set `openWorldHint: true` for tools that query external data sources
- Set `openWorldHint: false` for tools operating on known, closed datasets

### 4. **Combine Annotations Logically**
```json
// ✅ Good: Read-only tool that's safe to retry
{
  "readOnlyHint": true,
  "destructiveHint": false,
  "idempotentHint": true
}

// ❌ Avoid: Contradictory annotations
{
  "readOnlyHint": true,
  "destructiveHint": true  // Contradicts read-only
}
```

## Viewing Annotations

Annotations appear in tool JSON responses:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:4444/tools/{tool_id}
```

Response:
```json
{
  "id": "tool_123",
  "name": "file-reader",
  "url": "http://example.com/api/read-file",
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": false
  },
  "description": "Safely reads file contents",
  ...
}
```

## Integration with Clients

Many MCP clients use annotations to:

- **Show warning dialogs** for destructive tools
- **Enable auto-retry** for idempotent tools
- **Cache results** from read-only tools
- **Adjust UI presentation** based on safety hints

Properly annotated tools provide better user experiences and safer AI agent interactions.
