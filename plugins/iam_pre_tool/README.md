# IAM Pre-Tool Plugin

## Overview

The IAM Pre-Tool Plugin handles authentication and authorization requirements for MCP servers. It acquires access tokens, performs token exchange, and injects credentials into HTTP requests before they reach the target MCP server.

## Related Issues

- **Issue #1437**: Create IAM pre-tool plugin (this implementation)
- **Issue #1422**: EPIC - Agent and tool authentication and authorization plugin
- **Issue #1434**: Comprehensive OAuth2 base library (PR #2858 - dependency)
- **Issue #1438**: Enhance IAM pre-tool plugin (future enhancements)

## Features

### Phase 1 (Issue #1437)

- ✅ Token caching with configurable TTL
- ✅ Bearer token injection into Authorization headers
- ✅ Plugin framework integration with `http_pre_request` hook
- 🚧 OAuth2 client credentials flow (ready to integrate with PR #2858)

### Future (Issue #1438)

- ⏳ OAuth2 token exchange (RFC 8693) - will use `OAuth2BaseLibrary.exchange_token()`
- ⏳ Token refresh (RFC 6749) - will use `OAuth2BaseLibrary.refresh_token()`
- ⏳ Human-in-the-loop authorization flows
- ⏳ Enhanced OAuth2 flows (PKCE, device code)
- ⏳ Policy enforcement integration

## Configuration
```yaml
plugins:
  iam_pre_tool:
    enabled: true
    config:
      token_cache_ttl_seconds: 3600
      oauth2_client_credentials_enabled: false  # Enable when PR #2858 merges
      token_exchange_enabled: false
      inject_bearer_token: true
      server_credentials:
        server-id-1:
          client_id: "your-client-id"
          client_secret: "your-client-secret"  # Use Vault plugin in production
          token_endpoint: "https://auth.example.com/token"
          scope: "mcp:read mcp:write"
```

## How It Works

### Architecture Flow
```
┌─────────────────┐
│  MCP Client     │
│  (Agent/UI)     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  Transport Router           │
│  ┌─────────────────────┐   │
│  │ http_pre_request    │◄──┼─── IAM Pre-Tool Plugin
│  │ hook                │   │    (injects token)
│  └─────────────────────┘   │
└────────┬────────────────────┘
         │ Authorization: Bearer eyJhbGc...
         ▼
┌─────────────────┐
│  MCP Server     │
│  (with OAuth2)  │
└─────────────────┘
```

### Request Processing

1. **Request Interception**: Plugin registers for `http_pre_request` hook
2. **Server Identification**: Extracts `server_id` or `tool_id` from context
3. **Token Acquisition**:
   - Checks token cache for valid token
   - If miss/expired, acquires via OAuth2 client credentials (PR #2858)
   - Caches with configured TTL
4. **Credential Injection**: Adds `Authorization: Bearer <token>` header

## Integration with OAuth2 Base Library (PR #2858)

Once PR #2858 merges, this plugin will use:
```python
from mcpgateway.oauth2 import OAuth2BaseLibrary

# Token acquisition
oauth2_lib = OAuth2BaseLibrary()

# Client credentials flow (future)
token_response = await oauth2_lib.get_client_credentials_token(
    token_endpoint=server_creds["token_endpoint"],
    client_id=server_creds["client_id"],
    client_secret=server_creds["client_secret"],
    scope=server_creds.get("scope"),
)

# Token exchange (future - Issue #1438)
exchange_response = await oauth2_lib.exchange_token(request)

# Token refresh (future - Issue #1438)
refresh_response = await oauth2_lib.refresh_token(request)
```

## Security Considerations

### Credential Storage

⚠️ **Production Security**:
- Server credentials (client_id, client_secret) in plugin config are for **development only**
- **Production**: Integrate with **Vault plugin** (`plugins/vault/`) for secure secret storage
- Vault plugin provides dynamic secret retrieval from HashiCorp Vault

### Token Caching

- Tokens cached in-memory with expiration (60s safety buffer)
- For distributed deployments: consider Redis-backed cache
- Tokens never logged or exposed in errors

### Transport Security

- ✅ All OAuth2 flows MUST use HTTPS
- ✅ Token injection only over encrypted connections
- ✅ Validate server certificates in production

## Example Usage

### Scenario: Agent calling authenticated MCP server
```yaml
# Configure server with OAuth2
servers:
  - id: secure-mcp-server
    url: https://mcp.example.com
    auth_required: true

# Configure IAM plugin
plugins:
  iam_pre_tool:
    enabled: true
    config:
      oauth2_client_credentials_enabled: true
      server_credentials:
        secure-mcp-server:
          client_id: "agent-client"
          client_secret: "${VAULT:secret/mcp/client-secret}"
          token_endpoint: "https://auth.example.com/oauth/token"
          scope: "mcp:servers:read mcp:tools:execute"
```

### Request Flow
```
Agent Request → Transport Router → IAM Plugin
                                    ↓
                                    Check cache (miss)
                                    ↓
                                    OAuth2 client credentials
                                    ↓
                                    Cache token (TTL: 3600s)
                                    ↓
                                    Inject: Authorization: Bearer ...
                                    ↓
                                  MCP Server ✓ Authenticated
```

## Testing
```bash
# Run plugin tests
pytest tests/unit/plugins/test_iam_pre_tool.py -v

# Run with coverage
pytest tests/unit/plugins/test_iam_pre_tool.py --cov=plugins.iam_pre_tool --cov-report=term-missing

# Integration tests (future)
pytest tests/integration/test_iam_pre_tool_integration.py
```

## Dependencies

- Python 3.10+
- `pydantic` for configuration models
- Plugin framework: `mcpgateway.plugins.framework`
- **Future**: `mcpgateway.oauth2` (PR #2858)

## Roadmap

### ✅ Phase 1 (Current - Issue #1437)
- [x] Plugin structure and framework integration
- [x] Token caching mechanism
- [x] Bearer token injection
- [x] Basic configuration
- [ ] OAuth2 client credentials (blocked on PR #2858)
- [ ] Unit tests
- [ ] Documentation

### 🔜 Phase 2 (Issue #1438)
- [ ] Token exchange (RFC 8693)
- [ ] Token refresh (RFC 6749)
- [ ] Human-in-the-loop flows
- [ ] Enhanced OAuth2 flows
- [ ] Vault integration for secrets
- [ ] Redis cache for distributed deployments

## References

- [RFC 6749: OAuth 2.0](https://datatracker.ietf.org/doc/html/rfc6749)
- [RFC 8693: OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)
- [RFC 8707: Resource Indicators for OAuth 2.0](https://datatracker.ietf.org/doc/html/rfc8707)
- [MCP Auth Specification](https://spec.modelcontextprotocol.io/specification/draft/basic/authentication/)

## Authors

- Ioannis Ioannou (@yiannis2804)

## License

Apache-2.0
