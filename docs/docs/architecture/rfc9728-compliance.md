# RFC 9728 OAuth Protected Resource Metadata Compliance

## Overview

MCP Gateway implements [RFC 9728: OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728) to enable OAuth-protected MCP servers to advertise their authorization server configuration. This allows MCP clients (like Claude Desktop, MCP Inspector) to discover OAuth endpoints and initiate browser-based SSO flows.

## RFC 9728 Requirements

Per RFC 9728 Section 3.1, the well-known URI for OAuth Protected Resource Metadata is constructed by:

1. Taking the protected resource URL: `https://gateway.example.com/servers/{server_id}/mcp`
2. Removing any trailing slash
3. Inserting `/.well-known/oauth-protected-resource/` after the scheme and authority
4. Result: `https://gateway.example.com/.well-known/oauth-protected-resource/servers/{server_id}/mcp`

### Response Format

The metadata response fields (per RFC 9728 Section 2):

- `resource` (string, required): The protected resource identifier URL
- `authorization_servers` (array, optional per RFC 9728, required per MCP spec): JSON array of authorization server issuer URIs
- `bearer_methods_supported` (array, optional): Supported bearer token methods (e.g., `["header"]`)
- `scopes_supported` (array, optional): List of supported OAuth scopes

**Example Response (per RFC 9728 Section 3.2):**

```json
{
  "resource": "https://gateway.example.com/servers/abc-123/mcp",
  "authorization_servers": ["https://auth.example.com"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["read", "write"]
}
```

## Implementation

### Compliant Endpoint

**Path:** `/.well-known/oauth-protected-resource/servers/{server_id}/mcp`

**Method:** GET

**Authentication:** None required (per RFC 9728)

**Implementation:** [`mcpgateway/routers/well_known.py:118`](https://github.com/IBM/mcp-context-forge/blob/0c13cc9bcd78d4e70a4a62d00bb6785f7630eed6/mcpgateway/routers/well_known.py#L118)

**Features:**

- Path-based discovery (not query parameters)
- UUID validation for `server_id` (prevents path traversal)
- Returns `authorization_servers` field as JSON array (RFC 9728 Section 2)
- Includes `/mcp` suffix in resource URL
- Cache headers for performance
- Only exposes public servers with OAuth enabled

**Example Request:**

```bash
curl https://gateway.example.com/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp
```

**Example Response:**

```json
{
  "resource": "https://gateway.example.com/servers/550e8400-e29b-41d4-a716-446655440000/mcp",
  "authorization_servers": ["https://auth.example.com"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["openid", "profile", "email"]
}
```

### Service Layer

**Implementation:** [`mcpgateway/services/server_service.py:1913`](https://github.com/IBM/mcp-context-forge/blob/0c13cc9bcd78d4e70a4a62d00bb6785f7630eed6/mcpgateway/services/server_service.py#L1913)

The `get_oauth_protected_resource_metadata()` method:

- Returns RFC 9728 compliant metadata with `authorization_servers` field (JSON array)
- Reads `authorization_servers` (plural) from config as primary source
- Falls back to `authorization_server` (singular) from config for backward compatibility
- Only exposes metadata for public, enabled servers with OAuth configured
- Includes optional `scopes_supported` if configured

**Configuration Priority:**

1. `oauth_config.authorization_servers` (array, RFC 9728 compliant)
2. `oauth_config.authorization_server` (string, legacy fallback — wrapped in array)

### Security

**UUID Validation:**

The endpoint validates that `server_id` is a valid UUID using regex pattern matching. This prevents:

- Path traversal attacks (`../admin`)
- SQL injection attempts
- Arbitrary path access

**Access Control:**

- Only public servers expose OAuth metadata
- Disabled servers return 404
- Private/team servers return 404 (prevents information leakage)
- OAuth must be explicitly enabled on the server

**Implementation:** [`mcpgateway/routers/well_known.py:39`](https://github.com/IBM/mcp-context-forge/blob/0c13cc9bcd78d4e70a4a62d00bb6785f7630eed6/mcpgateway/routers/well_known.py#L39)

```python
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
```

## Deprecated Endpoints

### Query Parameter Endpoint (Deprecated)

**Path:** `/.well-known/oauth-protected-resource?server_id={id}`

**Status:** Returns 404 with deprecation message

**Reason:** Non-compliant with RFC 9728 (uses query parameters instead of path-based discovery)

**Migration:** Use `/.well-known/oauth-protected-resource/servers/{server_id}/mcp`

### Server-Scoped Endpoint (Deprecated)

**Path:** `/servers/{server_id}/.well-known/oauth-protected-resource`

**Status:** Returns 301 redirect to compliant endpoint

**Reason:** Non-compliant with RFC 9728 (appends well-known path instead of inserting it)

**Migration:** Automatically redirects to `/.well-known/oauth-protected-resource/servers/{server_id}/mcp`

## Configuration

### Server OAuth Configuration

To enable OAuth Protected Resource Metadata for a server, configure the server's `oauth_config`:

```json
{
  "oauth_enabled": true,
  "oauth_config": {
    "authorization_servers": ["https://auth.example.com"],
    "scopes_supported": ["openid", "profile", "email"],
    "client_id": "your-client-id",
    "client_secret": "your-client-secret"
  }
}
```

**Required Fields:**

- `authorization_servers` (array): JSON array of authorization server issuer URIs (at least one required per MCP spec)

**Optional Fields:**

- `scopes_supported` (array): List of supported OAuth scopes
- `client_id` (string): OAuth client ID (not exposed in metadata)
- `client_secret` (string): OAuth client secret (never exposed)

**Legacy Configuration:**

For backward compatibility, the system also accepts a singular string form:

```json
{
  "authorization_server": "https://auth.example.com"
}
```

This is automatically wrapped in an array in the response.

### Global Settings

**Environment Variables:**

- `WELL_KNOWN_ENABLED=true` - Enable well-known endpoints (default: true)
- `WELL_KNOWN_CACHE_MAX_AGE=3600` - Cache duration in seconds (default: 3600)

## Testing

### Unit Tests

Comprehensive test suite: [`tests/unit/mcpgateway/routers/test_well_known_rfc9728.py`](https://github.com/IBM/mcp-context-forge/blob/0c13cc9bcd78d4e70a4a62d00bb6785f7630eed6/tests/unit/mcpgateway/routers/test_well_known_rfc9728.py)

**Test Coverage:**

- RFC 9728 compliant endpoint success cases
- Path validation and security (UUID validation, path traversal prevention)
- Deprecated endpoint behavior (404 and 301 responses)
- Service layer RFC 9728 compliance
- Backward compatibility with legacy configurations
- Security validation (SQL injection, path traversal, access control)

**Run Tests:**

```bash
pytest tests/unit/mcpgateway/routers/test_well_known_rfc9728.py -v
```

### Manual Testing

**Test with curl:**

```bash
# RFC 9728 compliant endpoint
curl -i https://gateway.example.com/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp

# Verify response includes authorization_servers array
curl -s https://gateway.example.com/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp | jq .

# Test deprecated query-param endpoint (should return 404)
curl -i https://gateway.example.com/.well-known/oauth-protected-resource?server_id=550e8400-e29b-41d4-a716-446655440000

# Test deprecated server-scoped endpoint (should return 301)
curl -i https://gateway.example.com/servers/550e8400-e29b-41d4-a716-446655440000/.well-known/oauth-protected-resource
```

**Test with MCP Inspector:**

1. Configure an OAuth-enabled server in MCP Gateway
2. Open MCP Inspector
3. Connect to the server using the MCP endpoint: `https://gateway.example.com/servers/{server_id}/mcp`
4. MCP Inspector should automatically discover OAuth metadata via RFC 9728
5. Verify browser-based OAuth flow initiates correctly

## Migration Guide

### For MCP Gateway Administrators

**No action required.** The implementation maintains backward compatibility:

- Existing servers with `authorization_server` (singular string) continue to work
- The value is automatically wrapped in an array for the RFC 9728 response
- Deprecated endpoints provide clear migration guidance

**Recommended Actions:**

1. Update server configurations to use `authorization_servers` (plural array) field
2. Test OAuth flows with MCP clients
3. Monitor logs for deprecated endpoint usage

### For MCP Client Developers

**Update OAuth discovery logic:**

**Before (Non-compliant):**

```python
# Query parameter approach (deprecated)
metadata_url = f"{base_url}/.well-known/oauth-protected-resource?server_id={server_id}"
```

**After (RFC 9728 Compliant):**

```python
# Path-based approach (RFC 9728)
resource_url = f"{base_url}/servers/{server_id}/mcp"
# Insert /.well-known/oauth-protected-resource/ after scheme and authority
parsed = urlparse(resource_url)
metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{parsed.path}"
```

**Handle authorization_servers field:**

```python
# Parse metadata response
metadata = requests.get(metadata_url).json()

# RFC 9728 Section 2: authorization_servers is a JSON array
auth_servers = metadata["authorization_servers"]  # e.g., ["https://auth.example.com"]
```

## Compliance Checklist

- [x] Path-based discovery (not query parameters)
- [x] `authorization_servers` field as JSON array (RFC 9728 Section 2)
- [x] Resource URL includes `/mcp` suffix
- [x] No authentication required for metadata endpoint
- [x] Cache headers for performance
- [x] UUID validation for security
- [x] Only public servers exposed
- [x] Backward compatibility with legacy configs
- [x] Comprehensive test coverage
- [x] Deprecated endpoints provide migration guidance

## References

- [RFC 9728: OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)
- [MCP Specification: Authorization (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [IANA OAuth Protected Resource Metadata Registry](https://www.iana.org/assignments/oauth-parameters/oauth-parameters.xhtml)

## Related Documentation

- [OAuth Design](oauth-design.md) - Overall OAuth architecture
- [Multi-tenancy](multitenancy.md) - Team-based access control
- [RBAC](../manage/rbac.md) - Role-based permissions
