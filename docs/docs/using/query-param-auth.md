# Query Parameter Authentication

## Overview

!!! warning "Security Warning"
    Query parameter authentication is **inherently insecure** (CWE-598). API keys in URLs may appear in proxy logs, browser history, and server access logs. Only use this authentication method when the upstream MCP server **requires** it (e.g., Tavily MCP).

MCP Gateway supports API key authentication via URL query parameters for upstream MCP servers that mandate this authentication method. This feature is disabled by default and requires explicit opt-in.

## Use Cases

Query parameter authentication is specifically designed for:

- **Tavily MCP Server**: Requires `tavilyApiKey` as a query parameter
- Other MCP servers that mandate query parameter authentication
- Legacy APIs that don't support header-based authentication

## Prerequisites

Before using query parameter authentication, you must:

1. **Enable the feature flag** in your environment
2. **Configure the host allowlist** (recommended for production)

### Environment Configuration

```bash
# Enable query parameter authentication (required)
INSECURE_ALLOW_QUERYPARAM_AUTH=true

# Restrict to specific hosts (recommended for production)
INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS=["mcp.tavily.com"]
```

!!! tip "Host Allowlist"
    Always configure `INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS` in production to restrict which upstream servers can use this authentication method. An empty list `[]` allows any host.

## Configuration

### Via Admin UI

1. Navigate to the Admin Panel at `http://localhost:8000/admin/`
2. Click on the "Gateways" tab
3. When adding or editing a gateway:
   - Select **"Query Parameter (INSECURE)"** as the Authentication Type
   - Read the security warning displayed
   - Enter the **Query Parameter Name** (e.g., `tavilyApiKey`)
   - Enter the **API Key Value**
   - Submit the form to save your configuration

![Query Parameter Auth UI](../assets/query-param-auth-ui.png)

### Via API

Send a POST request to `/admin/gateways` with query parameter authentication:

```json
{
  "name": "Tavily MCP",
  "url": "https://mcp.tavily.com",
  "transport": "sse",
  "auth_type": "query_param",
  "auth_query_param_key": "tavilyApiKey",
  "auth_query_param_value": "your-tavily-api-key"
}
```

### Via Python SDK

```python
from mcpgateway.schemas import GatewayCreate

gateway = GatewayCreate(
    name="Tavily MCP",
    url="https://mcp.tavily.com",
    transport="sse",
    auth_type="query_param",
    auth_query_param_key="tavilyApiKey",
    auth_query_param_value="your-tavily-api-key"
)
```

## How It Works

When a gateway is configured with query parameter authentication:

1. **Registration**: The API key is encrypted and stored in the database
2. **Connection**: The gateway appends the decrypted API key to the URL when connecting
3. **Tool Invocation**: Each request to the upstream server includes the API key in the URL
4. **Logging**: URLs are sanitized before logging to redact sensitive query parameters

```
Original URL:  https://mcp.tavily.com
With Auth:     https://mcp.tavily.com?tavilyApiKey=your-api-key
In Logs:       https://mcp.tavily.com?tavilyApiKey=REDACTED
```

## Security Considerations

### Risks

- **Proxy Logs**: API keys may appear in proxy server access logs
- **Browser History**: If URLs are exposed to browsers, keys may be stored in history
- **Server Logs**: Upstream servers may log the full URL including query parameters
- **Network Monitoring**: Network monitoring tools may capture the full URL

### Mitigations

1. **Feature Flag**: Disabled by default, requires explicit opt-in
2. **Host Allowlist**: Restrict which hosts can use this auth method
3. **Encrypted Storage**: API keys are encrypted at rest
4. **Log Sanitization**: Sensitive query parameters are redacted in gateway logs
5. **UI Warning**: Clear security warning displayed in the Admin UI

### Recommendations

- Configure your proxy servers to redact query strings from access logs
- Use the host allowlist to restrict this auth method to specific services
- Rotate API keys regularly
- Monitor for unauthorized access to your API keys

## Troubleshooting

### "Query parameter authentication is disabled"

**Cause**: The feature flag is not enabled.

**Solution**: Set `INSECURE_ALLOW_QUERYPARAM_AUTH=true` in your environment.

### "Host not in allowed hosts"

**Cause**: The upstream host is not in the configured allowlist.

**Solution**: Add the host to `INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS`:

```bash
INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS=["mcp.tavily.com", "api.example.com"]
```

### API key not being sent

**Cause**: The gateway may not have the auth_query_params configured correctly.

**Solution**: Verify the gateway configuration via the API:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/admin/gateways/{gateway_id}
```

Check that `auth_type` is `query_param` and `auth_query_param_key` is set.

## Example: Tavily MCP Server

Here's a complete example of configuring the Tavily MCP server:

### 1. Enable the Feature

```bash
# .env
INSECURE_ALLOW_QUERYPARAM_AUTH=true
INSECURE_QUERYPARAM_AUTH_ALLOWED_HOSTS=["mcp.tavily.com"]
```

### 2. Register the Gateway

```bash
curl -X POST http://localhost:4444/admin/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tavily Search",
    "url": "https://mcp.tavily.com",
    "transport": "sse",
    "auth_type": "query_param",
    "auth_query_param_key": "tavilyApiKey",
    "auth_query_param_value": "tvly-your-api-key-here"
  }'
```

### 3. Create a Virtual Server

```bash
curl -X POST http://localhost:4444/admin/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tavily Search Server",
    "gateway_ids": ["<gateway-id-from-step-2>"]
  }'
```

### 4. Use the Tools

The Tavily search tools are now available through your virtual server's MCP endpoint.

## Related Documentation

- [ADR-035: Query Parameter Authentication](../architecture/adr/035-query-parameter-authentication.md)
- [Multiple Authentication Headers](multi-auth-headers.md)
- [Gateway Configuration](../overview/ui.md)
