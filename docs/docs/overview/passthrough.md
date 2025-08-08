# HTTP Header Passthrough

⚠️ **Security Notice**: HTTP Header Passthrough is **disabled by default** for security reasons. Only enable this feature if you understand the security implications and have reviewed which headers should be passed through to backing MCP servers.

The MCP Gateway supports **HTTP Header Passthrough**, allowing specific headers from incoming client requests to be forwarded to backing MCP servers. This feature is essential for maintaining authentication context and request tracing across the gateway infrastructure.

## Overview

When clients make requests through the MCP Gateway, certain headers (like authentication tokens or trace IDs) need to be preserved and passed to the underlying MCP servers. The header passthrough feature provides a configurable, secure way to forward these headers while preventing conflicts with existing authentication mechanisms.

## Key Features

- **🔒 Security by Default**: Feature disabled by default - must be explicitly enabled
- **🛡️ Header Validation**: Server-side and client-side header name and value validation
- **🧹 Sanitization**: Automatic removal of dangerous characters and length limits
- **Global Configuration**: Set default passthrough headers for all gateways
- **Per-Gateway Override**: Customize header passthrough on a per-gateway basis
- **Conflict Prevention**: Automatically prevents overriding existing authentication headers
- **Admin UI Integration**: Configure passthrough headers through the web interface
- **API Management**: Programmatic control via REST endpoints
- **Rate Limiting**: Built-in rate limiting for configuration endpoints

## Configuration

### ⚠️ Enable the Feature (Required)

**The header passthrough feature is disabled by default for security.** You must explicitly enable it:

```bash
# Enable the feature (disabled by default)
ENABLE_HEADER_PASSTHROUGH=true

# Or in .env file
ENABLE_HEADER_PASSTHROUGH=true
```

**Warning**: Only enable this feature if you:
- Understand the security implications
- Have reviewed which headers should be passed through
- Trust the backing MCP servers with the forwarded headers
- Have implemented proper network security

### Environment Variables

Set global default headers using the `DEFAULT_PASSTHROUGH_HEADERS` environment variable:

```bash
# JSON array format (recommended)
DEFAULT_PASSTHROUGH_HEADERS=["X-Tenant-Id", "X-Trace-Id"]

# Comma-separated format (also supported)
DEFAULT_PASSTHROUGH_HEADERS=X-Tenant-Id,X-Trace-Id

# Or in .env file
DEFAULT_PASSTHROUGH_HEADERS=["X-Tenant-Id", "X-Trace-Id"]
```

**Security Notes**:
- `Authorization` header is **not included in defaults** for security
- Only add `Authorization` if you fully understand the token leakage risks
- Header names are validated against pattern: `^[A-Za-z0-9-]+$`
- Header values are sanitized (newlines removed, length limited to 4KB)

### Admin UI Configuration

**Prerequisites**:
1. Set `ENABLE_HEADER_PASSTHROUGH=true` in your environment
2. Restart the MCP Gateway service

#### Global Configuration
Access the admin interface to set global passthrough headers that apply to all gateways by default.

🛡️ **Client-side validation** automatically checks:
- Header names match pattern `^[A-Za-z0-9-]+$`
- Header values don't contain newlines or excessive length
- Invalid headers are rejected with clear error messages

#### Per-Gateway Configuration
When creating or editing gateways:

1. Navigate to the **Gateways** section in the admin UI
2. Click **Add Gateway** or edit an existing gateway
3. In the **Passthrough Headers** field, enter a comma-separated list:
   ```
   X-Tenant-Id, X-Trace-Id, X-Request-Id
   ```
   **⚠️ Avoid including `Authorization` unless absolutely necessary**
4. Gateway-specific headers override global defaults
5. The UI validates headers in real-time and shows security warnings

### API Configuration

**Rate Limited**: Configuration endpoints are rate-limited (20-30 requests/minute) for security.

#### Get Global Configuration
```bash
GET /admin/config/passthrough-headers
Authorization: Bearer <your-jwt-token>
```

Response:
```json
{
  "passthrough_headers": ["X-Tenant-Id", "X-Trace-Id"]
}
```

#### Update Global Configuration
```bash
PUT /admin/config/passthrough-headers
Content-Type: application/json
Authorization: Bearer <your-jwt-token>

{
  "passthrough_headers": ["X-Tenant-Id", "X-Custom-Header"]
}
```

**Security Validation**: The API automatically:
- Validates header names against `^[A-Za-z0-9-]+$` pattern
- Rejects invalid characters and formats
- Sanitizes header values when used
- Logs all configuration changes for audit

## How It Works

### Header Processing Flow

1. **Client Request**: Client sends request with various headers
2. **Header Extraction**: Gateway extracts headers configured for passthrough
3. **Conflict Check**: System verifies no conflicts with existing auth headers
4. **Forwarding**: Allowed headers are added to requests sent to backing MCP servers

### Configuration Hierarchy

The system follows this priority order:

1. **Gateway-specific headers** (highest priority)
2. **Global configuration** (from database)
3. **Environment variable defaults** (lowest priority)

### Example Flow

```mermaid
graph LR
    A[Client Request] --> B[MCP Gateway]
    B --> C{Check Passthrough Config}
    C --> D[Extract Configured Headers]
    D --> E[Conflict Prevention Check]
    E --> F[Forward to MCP Server]

    G[Global Config] --> C
    H[Gateway Config] --> C
```

## Security Considerations

### 🛡️ Security-by-Default Features

**Feature Flag Protection**:
- Header passthrough is **disabled by default** (`ENABLE_HEADER_PASSTHROUGH=false`)
- Must be explicitly enabled with full awareness of security implications
- Can be disabled instantly by setting the flag to `false`

**Header Sanitization**:
- **Injection Prevention**: Removes newlines (`\r\n`) that could enable header injection attacks
- **Length Limiting**: Restricts header values to 4KB maximum to prevent DoS
- **Control Character Filtering**: Removes dangerous control characters (except tab)
- **Validation**: Header names must match `^[A-Za-z0-9-]+$` pattern

**Rate Limiting**:
- Configuration endpoints limited to 20-30 requests/minute
- Prevents automated attacks on configuration
- Configurable via existing rate limiting settings

### Conflict Prevention

The system automatically prevents header conflicts:

- **Basic Auth**: Skips `Authorization` header if gateway uses basic authentication
- **Bearer Auth**: Skips `Authorization` header if gateway uses bearer token authentication
- **Existing Headers**: Won't override pre-existing headers in base request
- **Warnings**: Logs warnings when headers are skipped due to conflicts

### Header Validation

- **Server-side validation**: Headers validated against security patterns
- **Client-side validation**: Admin UI provides real-time validation feedback
- **Case-insensitive matching**: Handles header case variations safely
- **Empty filtering**: Empty or invalid headers are filtered out
- **Explicit configuration**: Only explicitly configured headers are passed through

## Use Cases

### Authentication Context
⚠️ **Security Warning**: Be extremely careful when forwarding authentication tokens.

Forward authentication tokens to maintain user context:
```bash
# Client request includes
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...

# Forwarded to MCP server if configured
```

### Request Tracing
Maintain trace context across service boundaries:
```bash
# Client request includes
X-Trace-Id: abc123def456
X-Span-Id: span789

# Both forwarded to enable distributed tracing
```

### Multi-Tenant Systems
Pass tenant identification:
```bash
# Client request includes
X-Tenant-Id: tenant_12345
X-Organization: acme_corp

# Forwarded for tenant-specific processing
```

## Configuration Examples

### Basic Setup
```bash
# .env file (Authorization not recommended in defaults)
DEFAULT_PASSTHROUGH_HEADERS=["X-Tenant-Id"]
```

### Multi-Header Configuration
```bash
# .env file with multiple headers (safer defaults)
DEFAULT_PASSTHROUGH_HEADERS=["X-Tenant-Id", "X-Trace-Id", "X-Request-Id"]
```

### Gateway-Specific Override
```json
// Via Admin API for specific gateway
{
  "name": "secure-gateway",
  "url": "https://secure-mcp-server.example.com",
  "passthrough_headers": ["X-API-Key", "X-Client-Id"]
}
```

## Troubleshooting

### Common Issues

#### Headers Not Being Forwarded

**Most Common Cause - Feature Disabled**:
- ✅ **Check**: Is `ENABLE_HEADER_PASSTHROUGH=true` set in your environment?
- ✅ **Check**: Did you restart the gateway after setting the flag?
- ✅ **Check**: Are you seeing "Header passthrough is disabled" in debug logs?

**Other Causes**:
- Verify header names in configuration match exactly (case-insensitive matching)
- Check for authentication conflicts in logs
- Ensure gateway configuration overrides aren't blocking headers
- Verify header names pass validation (only letters, numbers, hyphens allowed)

#### Authentication Conflicts
If you see warnings like:
```
Skipping passthrough header 'Authorization' - conflicts with existing basic auth
```

**Solution**: Either:
1. Remove `Authorization` from passthrough headers for that gateway
2. Change the gateway to not use basic/bearer authentication
3. Use a different header name for custom auth tokens

#### Configuration Not Taking Effect
- Restart the gateway after environment variable changes
- Verify database migration has been applied
- Check admin API responses to confirm configuration is saved
- Verify rate limiting isn't blocking your configuration requests (20-30/min limit)

#### Header Validation Errors
If you see validation errors in the Admin UI or API:

**Header Name Validation**:
- Only letters, numbers, and hyphens allowed: `A-Za-z0-9-`
- Examples: ✅ `X-Tenant-Id`, `Authorization` ❌ `X_Tenant_ID`, `My Header`

**Header Value Issues**:
- No newlines (`\r` or `\n`) allowed in values
- Maximum length: 4KB per header value
- Control characters are automatically removed

### Debug Logging

Enable debug logging to see header processing:
```bash
LOG_LEVEL=DEBUG
```

Look for log entries containing:
- `Header passthrough is disabled` - Feature flag is off
- `Passthrough headers configured` - Headers are being processed
- `Skipping passthrough header` - Header blocked due to conflict
- `Adding passthrough header` - Header successfully forwarded
- `Invalid header name` - Header name validation failed
- `Header value became empty after sanitization` - Header value was sanitized away

## API Reference

### Data Models

#### GlobalConfig
```python
class GlobalConfig(Base):
    id: int
    passthrough_headers: Optional[List[str]]
```

#### Gateway
```python
class Gateway(Base):
    # ... other fields
    passthrough_headers: Optional[List[str]]
```

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/config/passthrough-headers` | Get global configuration |
| PUT | `/admin/config/passthrough-headers` | Update global configuration |
| POST | `/admin/gateways` | Create gateway with headers |
| PUT | `/admin/gateways/{id}` | Update gateway headers |

## Best Practices

1. **Minimal Headers**: Only configure headers you actually need to reduce overhead
2. **Security Review**: Regularly audit which headers are being passed through
3. **Environment Consistency**: Use consistent header configuration across environments
4. **Documentation**: Document which headers your MCP servers expect
5. **Monitoring**: Monitor logs for conflict warnings and adjust configuration accordingly

## Migration Notes

When upgrading to a version with header passthrough:

1. **Database Migration**: Ensure the migration `3b17fdc40a8d` has been applied
2. **Configuration Review**: Review existing authentication setup for conflicts
3. **Testing**: Test header forwarding in development before production deployment
4. **Monitoring**: Monitor logs for any unexpected behavior after deployment

## Testing with the Built-in Test Tool

The MCP Gateway admin interface includes a built-in test tool with passthrough header support:

### Using the Test Tool

1. **Access the Admin UI**: Navigate to the **Tools** section
2. **Select a Tool**: Click the **Test** button on any available tool
3. **Configure Headers**: In the test modal, scroll to the **Passthrough Headers** section
4. **Add Headers**: Enter headers in the format `Header-Name: Value` (one per line):
   ```
   Authorization: Bearer your-token-here
   X-Tenant-Id: tenant-123
   X-Trace-Id: abc-def-456
   ```
5. **Run Test**: Click **Run Tool** - the headers will be included in the request

### Example Test Scenarios

**Authentication Testing**:
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

**Multi-Tenant Testing**:
```
X-Tenant-Id: acme-corp
X-Organization-Id: org-12345
```

**Distributed Tracing**:
```
X-Trace-Id: trace-abc123
X-Span-Id: span-def456
X-Request-Id: req-789xyz
```

The test tool provides immediate feedback and allows you to verify that your passthrough header configuration is working correctly before deploying to production.
