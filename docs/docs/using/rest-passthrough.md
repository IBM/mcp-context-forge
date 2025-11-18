# REST Passthrough Configuration

Advanced configuration options for REST tools, enabling fine-grained control over request routing, header/query mapping, timeouts, security policies, and plugin chains.

## Overview

REST passthrough fields provide comprehensive control over how REST tools interact with upstream APIs:

- **URL Mapping**: Automatic extraction of base URLs and path templates from tool URLs
- **Dynamic Parameters**: Query and header mapping for request customization
- **Security Controls**: Host allowlists and timeout configurations
- **Plugin Integration**: Pre and post-request plugin chain support
- **Flexible Configuration**: Per-tool timeout and exposure settings

## Passthrough Fields

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `base_url` | `string` | Base URL for REST passthrough (auto-extracted from `url`) | - |
| `path_template` | `string` | Path template for URL construction (auto-extracted) | - |
| `query_mapping` | `object` | JSON mapping for query parameters | `{}` |
| `header_mapping` | `object` | JSON mapping for headers | `{}` |
| `timeout_ms` | `integer` | Request timeout in milliseconds | `20000` |
| `expose_passthrough` | `boolean` | Enable/disable passthrough endpoint | `true` |
| `allowlist` | `array` | Allowed upstream hosts/schemes | `[]` |
| `plugin_chain_pre` | `array` | Pre-request plugin chain | `[]` |
| `plugin_chain_post` | `array` | Post-request plugin chain | `[]` |

## Field Details

### Base URL & Path Template

When creating a REST tool, the `base_url` and `path_template` are automatically extracted from the `url` field:

**Input:**
```json
{
  "url": "https://api.example.com/v1/users/{user_id}"
}
```

**Auto-extracted:**
```json
{
  "base_url": "https://api.example.com",
  "path_template": "/v1/users/{user_id}"
}
```

**Validation:**
- `base_url` must have a valid scheme (http/https) and netloc
- `path_template` must start with `/`

### Query Mapping

Map tool parameters to query string parameters:

```json
{
  "query_mapping": {
    "userId": "user_id",
    "includeDetails": "include_details",
    "format": "response_format"
  }
}
```

**Example Usage:**
When a tool is invoked with:
```json
{
  "userId": "123",
  "includeDetails": true,
  "format": "json"
}
```

The gateway constructs:
```
GET https://api.example.com/endpoint?user_id=123&include_details=true&response_format=json
```

### Header Mapping

Map tool parameters to HTTP headers:

```json
{
  "header_mapping": {
    "apiKey": "X-API-Key",
    "clientId": "X-Client-ID",
    "requestId": "X-Request-ID"
  }
}
```

**Example Usage:**
When a tool is invoked with:
```json
{
  "apiKey": "secret123",
  "clientId": "client-456",
  "requestId": "req-789"
}
```

The gateway sends:
```http
X-API-Key: secret123
X-Client-ID: client-456
X-Request-ID: req-789
```

### Timeout Configuration

Set per-tool timeout in milliseconds:

```json
{
  "timeout_ms": 30000
}
```

**Default Behavior:**
- For REST tools with `expose_passthrough: true`: `20000ms` (20 seconds)
- For other integration types: No default timeout

**Validation:**
- Must be a positive integer
- Recommended range: `5000-60000ms` (5-60 seconds)

### Expose Passthrough

Control whether the passthrough endpoint is exposed:

```json
{
  "expose_passthrough": false
}
```

**Use Cases:**
- `true` (default): Expose passthrough endpoint for direct REST invocation
- `false`: Hide passthrough, only allow invocation through gateway

### Allowlist

Restrict upstream hosts/schemes that tools can connect to:

```json
{
  "allowlist": [
    "api.example.com",
    "https://secure.api.com",
    "internal.company.net:8080"
  ]
}
```

**Validation:**
- Each entry must match hostname regex: `^(https?://)?([a-zA-Z0-9.-]+)(:[0-9]+)?$`
- Supports optional scheme prefix and port suffix

**Security Benefits:**
- Prevents SSRF (Server-Side Request Forgery) attacks
- Restricts tool access to approved endpoints only
- Enforces organizational security policies

### Plugin Chains

Configure pre and post-request plugin processing:

```json
{
  "plugin_chain_pre": ["deny_filter", "rate_limit", "pii_filter"],
  "plugin_chain_post": ["response_shape", "regex_filter"]
}
```

**Allowed Plugins:**
- `deny_filter` - Block requests matching deny patterns
- `rate_limit` - Rate limiting enforcement
- `pii_filter` - PII detection and filtering
- `response_shape` - Response transformation
- `regex_filter` - Regex-based content filtering
- `resource_filter` - Resource access control

**Execution Order:**
1. **Pre-request plugins** (`plugin_chain_pre`) execute before the REST call
2. REST call to upstream API
3. **Post-request plugins** (`plugin_chain_post`) execute after receiving response

## Setting Passthrough Fields via Admin UI

### Using the Advanced Button

1. Navigate to **Tools** section in the Admin UI
2. Click **Add Tool** or **Edit** on an existing tool
3. Select **Integration Type**: `REST`
4. Enter the **URL** (e.g., `https://api.example.com/v1/users`)
5. Click **Advanced: Add Passthrough** button
6. Configure passthrough fields in the expanded section:
   - **Query Mapping (JSON)**: `{"userId": "user_id"}`
   - **Header Mapping (JSON)**: `{"apiKey": "X-API-Key"}`
   - **Timeout MS**: `30000`
   - **Expose Passthrough**: `true` or `false`
   - **Allowlist**: `["api.example.com"]`
   - **Plugin Chain Pre**: `["rate_limit", "pii_filter"]`
   - **Plugin Chain Post**: `["response_shape"]`
7. Click **Save**

## Setting Passthrough Fields via API

### Complete Example with All Fields

```bash
curl -X POST /tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "user-management-api",
    "integration_type": "REST",
    "request_type": "GET",
    "url": "https://api.example.com/v1/users/{user_id}",
    "description": "Fetch user information from external API",
    "query_mapping": {
      "includeMetadata": "include_metadata",
      "fields": "response_fields"
    },
    "header_mapping": {
      "apiKey": "X-API-Key",
      "tenantId": "X-Tenant-ID"
    },
    "timeout_ms": 25000,
    "expose_passthrough": true,
    "allowlist": [
      "api.example.com",
      "https://backup-api.example.com"
    ],
    "plugin_chain_pre": ["rate_limit", "pii_filter"],
    "plugin_chain_post": ["response_shape"]
  }'
```

### Minimal Example (Defaults Applied)

```bash
curl -X POST /tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "simple-rest-tool",
    "integration_type": "REST",
    "request_type": "POST",
    "url": "https://api.example.com/v1/create"
  }'
```

**Auto-applied Defaults:**
- `base_url`: `https://api.example.com` (extracted)
- `path_template`: `/v1/create` (extracted)
- `timeout_ms`: `20000` (default for REST passthrough)
- `expose_passthrough`: `true`
- `query_mapping`: `{}`
- `header_mapping`: `{}`
- `allowlist`: `[]`
- `plugin_chain_pre`: `[]`
- `plugin_chain_post`: `[]`

### Updating Passthrough Fields

```bash
curl -X PUT /tools/{tool_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "timeout_ms": 30000,
    "allowlist": ["api.example.com", "api2.example.com"],
    "plugin_chain_pre": ["rate_limit", "deny_filter"]
  }'
```

## Common Use Cases

### 1. API Key Authentication via Headers

```json
{
  "name": "external-api-with-auth",
  "url": "https://api.service.com/data",
  "header_mapping": {
    "apiKey": "X-API-Key",
    "apiSecret": "X-API-Secret"
  },
  "allowlist": ["api.service.com"]
}
```

### 2. Search API with Query Parameters

```json
{
  "name": "search-api",
  "url": "https://search.example.com/query",
  "query_mapping": {
    "searchTerm": "q",
    "maxResults": "limit",
    "pageNumber": "page"
  },
  "timeout_ms": 15000
}
```

### 3. High-Security API with Plugins

```json
{
  "name": "sensitive-data-api",
  "url": "https://secure-api.company.internal/data",
  "allowlist": ["secure-api.company.internal"],
  "plugin_chain_pre": ["deny_filter", "rate_limit", "pii_filter"],
  "plugin_chain_post": ["response_shape", "pii_filter"],
  "timeout_ms": 10000
}
```

### 4. Multi-Tenant API with Dynamic Headers

```json
{
  "name": "multi-tenant-service",
  "url": "https://api.saas.com/v2/tenants/{tenant_id}/resources",
  "header_mapping": {
    "tenantApiKey": "X-Tenant-API-Key",
    "organizationId": "X-Organization-ID"
  },
  "query_mapping": {
    "includeArchived": "include_archived"
  },
  "timeout_ms": 20000
}
```

### 5. Rate-Limited Public API

```json
{
  "name": "public-api-with-limits",
  "url": "https://public-api.example.com/v1/data",
  "plugin_chain_pre": ["rate_limit"],
  "timeout_ms": 30000,
  "allowlist": ["public-api.example.com"]
}
```

## Validation Rules

### Enforced Constraints

1. **Integration Type Restriction**: Passthrough fields only valid for `integration_type: "REST"`
   ```json
   // ❌ Invalid - passthrough fields on non-REST tool
   {
     "integration_type": "MCP",
     "query_mapping": {...}  // Error!
   }
   ```

2. **Base URL Format**: Must include scheme and netloc
   ```json
   // ✅ Valid
   "base_url": "https://api.example.com"

   // ❌ Invalid
   "base_url": "api.example.com"  // Missing scheme
   ```

3. **Path Template Format**: Must start with `/`
   ```json
   // ✅ Valid
   "path_template": "/v1/users"

   // ❌ Invalid
   "path_template": "v1/users"  // Missing leading slash
   ```

4. **Timeout Range**: Must be positive integer
   ```json
   // ✅ Valid
   "timeout_ms": 25000

   // ❌ Invalid
   "timeout_ms": -1000  // Negative value
   ```

5. **Plugin Validation**: Only allowed plugins
   ```json
   // ✅ Valid
   "plugin_chain_pre": ["rate_limit", "pii_filter"]

   // ❌ Invalid
   "plugin_chain_pre": ["unknown_plugin"]  // Not in allowed list
   ```

## Security Best Practices

### 1. Always Use Allowlists for Production

```json
{
  "allowlist": [
    "api.production.com",
    "backup.production.com"
  ]
}
```

**Benefits:**
- Prevents SSRF attacks
- Enforces approved endpoints only
- Auditable security policy

### 2. Set Appropriate Timeouts

```json
{
  "timeout_ms": 15000  // 15 seconds for most APIs
}
```

**Guidelines:**
- Fast APIs: `5000-10000ms`
- Standard APIs: `15000-25000ms`
- Batch/Long-running: `30000-60000ms`

### 3. Use PII Filtering for Sensitive Data

```json
{
  "plugin_chain_pre": ["pii_filter"],
  "plugin_chain_post": ["pii_filter"]
}
```

**Protects:**
- Personally identifiable information
- Credit card numbers
- Social security numbers
- Email addresses

### 4. Rate Limit External APIs

```json
{
  "plugin_chain_pre": ["rate_limit"]
}
```

**Prevents:**
- API quota exhaustion
- DDoS to upstream services
- Unexpected billing charges

### 5. Validate Response Shapes

```json
{
  "plugin_chain_post": ["response_shape"]
}
```

**Ensures:**
- Consistent response formats
- Expected data structures
- Type safety

## Troubleshooting

### Common Issues

#### Issue: "Field 'query_mapping' is only allowed for integration_type 'REST'"

**Solution:** Ensure `integration_type: "REST"` is set:
```json
{
  "integration_type": "REST",
  "query_mapping": {...}
}
```

#### Issue: "base_url must be a valid URL with scheme and netloc"

**Solution:** Include `https://` or `http://` prefix:
```json
{
  "base_url": "https://api.example.com"  // Not "api.example.com"
}
```

#### Issue: "path_template must start with '/'"

**Solution:** Add leading slash:
```json
{
  "path_template": "/v1/users"  // Not "v1/users"
}
```

#### Issue: "Unknown plugin: custom_plugin"

**Solution:** Use only allowed plugins:
```json
{
  "plugin_chain_pre": [
    "deny_filter",
    "rate_limit",
    "pii_filter",
    "response_shape",
    "regex_filter",
    "resource_filter"
  ]
}
```

#### Issue: "timeout_ms must be a positive integer"

**Solution:** Provide valid positive number:
```json
{
  "timeout_ms": 20000  // Not -1, 0, or non-integer
}
```

## Migration from Previous Versions

### If you have existing REST tools without passthrough fields:

**Before (v0.9.0):**
```json
{
  "name": "my-rest-tool",
  "integration_type": "REST",
  "url": "https://api.example.com/v1/users"
}
```

**After (v0.9.0):**
```json
{
  "name": "my-rest-tool",
  "integration_type": "REST",
  "url": "https://api.example.com/v1/users",
  // Auto-extracted fields:
  "base_url": "https://api.example.com",
  "path_template": "/v1/users",
  // Auto-applied defaults:
  "timeout_ms": 20000,
  "expose_passthrough": true
}
```

**No action required** - existing tools will continue to work with auto-applied defaults.

## API Reference

### Tool Schema with Passthrough Fields

```typescript
interface ToolCreate {
  name: string;
  integration_type: "REST" | "MCP" | "A2A";
  request_type: string;
  url: string;
  description?: string;

  // REST Passthrough Fields (only for integration_type: "REST")
  base_url?: string;              // Auto-extracted from url
  path_template?: string;         // Auto-extracted from url
  query_mapping?: object;         // Default: {}
  header_mapping?: object;        // Default: {}
  timeout_ms?: number;            // Default: 20000 for REST
  expose_passthrough?: boolean;   // Default: true
  allowlist?: string[];           // Default: []
  plugin_chain_pre?: string[];    // Default: []
  plugin_chain_post?: string[];   // Default: []
}
```

## See Also

- [Tool Annotations](./tool-annotations.md) - Behavioral hints for tools
- [Plugin Framework](../plugins/index.md) - Plugin development and usage
- [Multi-Auth Headers](./multi-auth-headers.md) - Authentication header configuration
- [Reverse Proxy](./reverse-proxy.md) - Reverse proxy configuration
