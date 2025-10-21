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
# List all registered gateways
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/gateways | jq '.'
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
    "enabled": true,
    "request_type": "STREAMABLEHTTP"
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
    "enabled": true,
    "request_type": "STREAMABLEHTTP"
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
  $BASE_URL/gateways/$GATEWAY_ID/toggle | jq '.'
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
# List all available tools
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | jq '.'

# List tools with pretty formatting
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tools | \
  jq '.[] | {name: .name, description: .description, gateway: .gatewaySlug}'
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
    "name": "weather-api",
    "description": "Get weather information for a city",
    "url": "https://api.weather.com/v1/current",
    "request_type": "REST",
    "integration_type": "REST",
    "input_schema": {
      "type": "object",
      "properties": {
        "city": {
          "type": "string",
          "description": "City name"
        }
      },
      "required": ["city"]
    }
  }' \
  $BASE_URL/tools | jq '.'
```

### Invoke a Tool

```bash
# Execute a tool with arguments
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "param1": "value1",
      "param2": "value2"
    }
  }' \
  $BASE_URL/tools/$TOOL_ID | jq '.'
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
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "param1": "test_value"
    }
  }' \
  $BASE_URL/tools/$TOOL_ID | jq '.'
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
  $BASE_URL/tools/$TOOL_ID/toggle | jq '.'
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
# List all virtual servers
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/servers | jq '.'
```

### Get Server Details

```bash
# Get specific server
export SERVER_ID="your-server-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/servers/$SERVER_ID | jq '.'
```

### Create Virtual Server

```bash
# Create a new virtual server
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-virtual-server",
    "description": "Composed server with multiple tools",
    "associated_gateways": ["'$GATEWAY_ID'"],
    "enabled": true
  }' \
  $BASE_URL/servers | jq '.'
```

#### Complete Example: Virtual Server Creation

```bash
# 1. Get gateway IDs to associate
GATEWAYS=$(curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/gateways)
export GW1_ID=$(echo $GATEWAYS | jq -r '.[0].id')
export GW2_ID=$(echo $GATEWAYS | jq -r '.[1].id')

# 2. Create virtual server with multiple gateways
SERVER_RESPONSE=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "unified-server",
    "description": "Combines multiple MCP servers",
    "associated_gateways": ["'$GW1_ID'", "'$GW2_ID'"],
    "enabled": true
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
  $BASE_URL/servers/$SERVER_ID/toggle | jq '.'
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
# List all available resources
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/resources | jq '.'
```

### Get Resource Details

```bash
# Get specific resource
export RESOURCE_ID="your-resource-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/resources/$RESOURCE_ID | jq '.'
```

### Register a Resource

```bash
# Register a new resource
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "config-file",
    "uri": "file:///etc/config.yaml",
    "description": "Application configuration file",
    "mime_type": "application/yaml"
  }' \
  $BASE_URL/resources | jq '.'
```

### Read Resource Content

```bash
# Get resource content
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/resources/$RESOURCE_ID | jq '.content'
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
  $BASE_URL/resources/$RESOURCE_ID/toggle | jq '.'
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
# List all available prompts
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/prompts | jq '.'
```

### Get Prompt Details

```bash
# Get specific prompt
export PROMPT_ID="your-prompt-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/prompts/$PROMPT_ID | jq '.'
```

### Register a Prompt

```bash
# Register a new prompt template
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-review",
    "description": "Review code for best practices",
    "content": "Review the following code and suggest improvements:\n\n{{code}}",
    "arguments": [
      {
        "name": "code",
        "description": "Code to review",
        "required": true
      }
    ]
  }' \
  $BASE_URL/prompts | jq '.'
```

### Execute Prompt (Get Rendered Content)

```bash
# Execute prompt with arguments
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "code": "def hello():\n    print(\"Hello\")"
    }
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
  $BASE_URL/prompts/$PROMPT_ID/toggle | jq '.'
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
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tags | jq '.'
```

### Create Tag

```bash
# Create a new tag
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production",
    "description": "Production-ready tools",
    "color": "#00FF00"
  }' \
  $BASE_URL/tags | jq '.'
```

### Get Tag Details

```bash
# Get specific tag
export TAG_ID="your-tag-id"
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/tags/$TAG_ID | jq '.'
```

### Update Tag

```bash
# Update tag
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated description",
    "color": "#FF0000"
  }' \
  $BASE_URL/tags/$TAG_ID | jq '.'
```

### Delete Tag

```bash
# Delete tag
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/tags/$TAG_ID | jq '.'
```

## Bulk Operations

### Export Configuration

```bash
# Export all gateway configuration
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/export | jq '.' > gateway-export.json

# Export specific entities
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/export?include_tools=true&include_gateways=true" | \
  jq '.' > partial-export.json
```

### Import Configuration

```bash
# Import configuration from file
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @gateway-export.json \
  $BASE_URL/import | jq '.'
```

### Bulk Import Tools

```bash
# Import multiple tools at once
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tools": [
      {
        "name": "tool1",
        "description": "First tool",
        "url": "http://example.com/api1"
      },
      {
        "name": "tool2",
        "description": "Second tool",
        "url": "http://example.com/api2"
      }
    ]
  }' \
  $BASE_URL/bulk-import | jq '.'
```

## A2A Agent Management

A2A (Agent-to-Agent) enables integration with external AI agents.

!!! note "A2A Feature Flag"
    A2A features must be enabled via `MCPGATEWAY_A2A_ENABLED=true` in your `.env` file.

### List All A2A Agents

```bash
# List registered A2A agents
curl -s -H "Authorization: Bearer $TOKEN" $BASE_URL/a2a | jq '.'
```

### Register A2A Agent

```bash
# Register an OpenAI agent
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "openai-assistant",
    "agent_type": "openai",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "api_key": "sk-...",
    "model": "gpt-4",
    "description": "OpenAI GPT-4 assistant"
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
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain quantum computing in simple terms"
  }' \
  $BASE_URL/a2a/$A2A_ID/invoke | jq '.'
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
    "enabled": true,
    "request_type": "STREAMABLEHTTP"
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
echo "6. Invoking tool..."
RESULT=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "param1": "test_value"
    }
  }' \
  $BASE_URL/tools/$TOOL_ID)
echo $RESULT | jq '.'
echo

# 7. Create a virtual server
echo "7. Creating virtual server..."
SERVER=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-virtual-server",
    "description": "Unified server for testing",
    "associated_gateways": ["'$GATEWAY_ID'"],
    "enabled": true
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
  jq '{gateways: .gateways | length, tools: .tools | length}' > export-summary.json
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

### Pagination and Filtering

```bash
# Get first 10 tools
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?limit=10&offset=0" | jq '.'

# Filter by tag
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?tag=production" | jq '.'

# Search by name
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/tools?search=weather" | jq '.'
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
    $BASE_URL/tools/$TOOL_ID/toggle > /dev/null
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
