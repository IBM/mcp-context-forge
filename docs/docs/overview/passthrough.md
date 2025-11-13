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

# Optional: Enable overwriting of base headers (disabled by default)
ENABLE_OVERWRITE_BASE_HEADERS=false

# Or in .env file
ENABLE_HEADER_PASSTHROUGH=true
ENABLE_OVERWRITE_BASE_HEADERS=false
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

### Base Headers Override (Advanced)

By default, passthrough headers **cannot override** existing base headers set by the gateway (like `Content-Type`, `Authorization`, etc.). This prevents conflicts with essential gateway functionality.

```bash
# Enable overwriting of base headers (⚠️ Advanced usage only)
ENABLE_OVERWRITE_BASE_HEADERS=true
```

**⚠️ Warning**: Only enable this if you:

- Understand the implications of overriding gateway headers
- Need specific headers from client requests to take precedence
- Have thoroughly tested the impact on gateway functionality

**Use Cases**:

- Custom authentication schemes that require client-provided `Authorization` headers
- Specialized content negotiation requiring client `Content-Type` override
- Advanced proxy scenarios with specific header requirements

**Conflicts Still Prevented**:

- Gateway authentication conflicts are still detected and logged
- Invalid headers are still rejected and sanitized

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


## Usage with One-Time Auth

The One-Time Authentication feature enables integration with an authenticated MCP server without persisting server credentials in the database. Authentication is performed using a one-time token during initial registration, combined with passthrough headers to securely forward authentication context for subsequent requests.

### Workflow Overview

The one-time auth workflow consists of three main steps:

1. **Register the Gateway** - Authenticate once to discover tools, then discard credentials
2. **Create Virtual Servers** - Expose selected tools through virtual server endpoints
3. **Connect MCP Clients** - Use passthrough headers to authenticate requests

```mermaid
graph LR
    A[User] --> B["Add MCP Server"]
    B --> C{"Enable One-Time Authentication?"}
    C -->|Yes| D["Do Not Store Credentials in DB"]
    C -->|No| E["Store Credentials in DB"]
    D --> F["Configure Passthrough Headers (X-Upstream-Authorization)"]
    F --> G["Create Virtual Server"]
    G --> H["Link to MCP Server"]
    H --> I["Add Authentication Headers"]
    I --> J["Test Connection"]
    J --> K["Successful Authentication"]
    E --> L["Create Virtual Server with Stored Credentials"]

    %% Define styling for steps (Dark mode colors)
    classDef step fill:#1e1e1e,stroke:#ffffff,stroke-width:2px,color:#f5f5f5;
    class A,B,C,D,E,F,G,H,I,J,K,L step;
```

### Step 1: Register Gateway with One-Time Authentication

Register an MCP server with authentication details and enable one-time auth. The gateway will:
- Use the provided credentials **once** to connect to the MCP server
- Discover and retrieve all available tools and metadata
- **Discard the authentication details** without storing them in the database

**API Request:**

```bash
POST /gateways
Content-Type: application/json
Authorization: Bearer <your-gateway-token>

{
  "name": "my-server",
  "url": "http://localhost:8005/mcp",
  "description": "Authenticated MCP server with one-time auth",
  "transport": "STREAMABLEHTTP",
  "passthrough_headers": [
    "X-Upstream-Authorization"
  ],
  "auth_type": "bearer",
  "auth_token": "super-secret-123",
  "one_time_auth": true
}
```

**Key Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier for the gateway |
| `url` | Yes | MCP server endpoint URL |
| `transport` | Yes | Transport protocol (`STREAMABLEHTTP` or `SSE`) |
| `passthrough_headers` | Yes | Use include `X-Upstream-Authorization` for `Authorization` headers, for other headers, use as it is |
| `auth_type` | Yes | Authentication scheme (`bearer` or `basic`, etc) |
| `auth_token` | Yes | Token used **only once** for initial connection |
| `one_time_auth` | Yes | Set to `true` to enable one-time authentication |

**What Happens:**

1. Gateway connects to the MCP server using `auth_token`
2. Tool discovery is performed, retrieving all available tools
3. Tool metadata and schemas are stored in the database
4. **Credentials are immediately discarded** - not saved anywhere
5. Gateway registration completes successfully
6. Health checks are automatically disabled (no stored credentials available)

### Step 2: Create Virtual Servers

After gateway registration, create virtual servers to expose selected tools from the authenticated MCP server. Virtual servers act as proxies that use passthrough headers for authentication.

**API Request:**

```bash
POST /servers
Content-Type: application/json
Authorization: Bearer <your-gateway-token>

{
  "server": {
    "name": "my-virtual-server",
    "description": "Virtual server exposing authenticated tools",
    "associated_tools": [
      "1a4712afecbf44408960da065c5183e3"
    ],
    "visibility": "public"
  }
}
```

**Response:**

The API returns the virtual server details including its unique ID (e.g., `aa9980f23d2c45d5a07727993565e9c8`), which is used to construct the MCP endpoint URL.

### Step 3: Connect MCP Clients with Passthrough Headers

Connect any MCP-compatible client to the virtual server, providing authentication via passthrough headers. The client must supply:

1. **Gateway Authentication** - Token to authenticate with Context Forge Gateway (`Authorization` header)
2. **MCP Server Authentication** - Token forwarded to the upstream MCP server (`X-Upstream-Authorization` header)

#### Example: Claude Desktop Configuration

Add the following configuration to Claude Desktop's MCP settings:

```json
{
  "mcpServers": {
    "new-virtual-server": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:4444/servers/aa9980f23d2c45d5a07727993565e9c8/mcp",
        "--header",
        "Authorization:${GATEWAY_AUTH_TOKEN}",
        "--header",
        "X-Upstream-Authorization:${MCP_SERVER_AUTH_TOKEN}"
      ],
      "env": {
        "GATEWAY_AUTH_TOKEN": "Bearer <context_forge_gateway_token>",
        "MCP_SERVER_AUTH_TOKEN": "Bearer <mcp_server_bearer_token>"
      }
    }
  }
}
```

**Configuration Breakdown:**

| Component | Purpose |
|-----------|---------|
| `mcp-remote` | NPM package for remote MCP connections |
| `http://localhost:4444/servers/...` | Virtual server endpoint URL |
| `Authorization` header | Authenticates with Context Forge Gateway |
| `X-Upstream-Authorization` header | Forwarded to the upstream MCP server |
| `GATEWAY_AUTH_TOKEN` | JWT or Bearer token for gateway access |
| `MCP_SERVER_AUTH_TOKEN` | Bearer token for the authenticated MCP server |

**Environment Variables:**

Replace the placeholder tokens with actual values:

```bash
# Gateway authentication token (obtained from Context Forge)
GATEWAY_AUTH_TOKEN="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# MCP server authentication token (your server's auth token)
MCP_SERVER_AUTH_TOKEN="Bearer super-secret-123"
```

### Authentication Flow Diagram

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Gateway as Context Forge Gateway
    participant MCP as MCP Server

    Note over Gateway,MCP: Step 1: One-Time Registration
    Gateway->>MCP: Connect with auth_token (one-time)
    MCP-->>Gateway: Return tools & metadata
    Note over Gateway: Store tools, discard credentials

    Note over Client,MCP: Step 2: Runtime Requests
    Client->>Gateway: Request with Authorization header
    Note over Gateway: Validate gateway auth
    Client->>Gateway: Include X-Upstream-Authorization header
    Gateway->>MCP: Forward request with Authorization header
    Note over Gateway: Map X-Upstream-Authorization → Authorization
    MCP-->>Gateway: Return response
    Gateway-->>Client: Forward response
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
