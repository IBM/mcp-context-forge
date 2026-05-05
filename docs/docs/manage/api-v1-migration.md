# API v1 Migration Guide

## Overview

ContextForge has implemented API versioning with all backend routes now available under the `/v1` prefix. Legacy unversioned routes remain available for backward compatibility until **May 13, 2026**.

## Quick Migration

For most clients, migration is a simple find-and-replace operation:

```bash
# Before
/tools → /v1/tools
/servers → /v1/servers
/gateways → /v1/gateways
```

## Versioned Routes

All backend API routes are now available under `/v1`:

| Category | Legacy Path | New Path |
|----------|-------------|----------|
| **MCP Protocol** | `/protocol/*` | `/v1/protocol/*` |
| **Tools** | `/tools/*` | `/v1/tools/*` |
| **Resources** | `/resources/*` | `/v1/resources/*` |
| **Prompts** | `/prompts/*` | `/v1/prompts/*` |
| **Gateways** | `/gateways/*` | `/v1/gateways/*` |
| **Roots** | `/roots/*` | `/v1/roots/*` |
| **Servers** | `/servers/*` | `/v1/servers/*` |
| **Metrics** | `/metrics/*` | `/v1/metrics/*` |
| **Tags** | `/tags/*` | `/v1/tags/*` |
| **Export/Import** | `/export`, `/import/*` | `/v1/export`, `/v1/import/*` |
| **A2A Agents** | `/a2a/*` | `/v1/a2a/*` |
| **Admin UI/API** | `/admin/*` | `/v1/admin/*` |
| **Authentication** | `/auth/*`, `/teams/*`, `/tokens/*`, `/rbac/*` | `/v1/auth/*`, `/v1/teams/*`, `/v1/tokens/*`, `/v1/rbac/*` |
| **LLM Features** | `/llmchat/*`, `/llm/*` | `/v1/llmchat/*`, `/v1/llm/*` |
| **Observability** | `/observability/*` | `/v1/observability/*` |
| **Reverse Proxy** | `/reverse-proxy/*` | `/v1/reverse-proxy/*` |
| **Tool Cancellation** | `/cancellation/*` | `/v1/cancellation/*` |
| **Tool Operations** | `/toolops/*` | `/v1/toolops/*` |

## Permanently Unversioned Routes

These routes remain at the root level and **do not** require migration:

### Infrastructure & Health
- `/health` - Health check endpoint
- `/ready` - Readiness probe
- `/health/security` - Security health check
- `/version` - Version information

### MCP Protocol
- `/mcp` - MCP protocol endpoint (fixed by MCP spec)
- `/_internal/mcp/transport` - Internal MCP bridge

### OAuth 2.0
- `/oauth/**` - OAuth endpoints (RFC 6749 standard location)

### Well-Known URIs
- `/.well-known/**` - RFC 8615 well-known URIs
- `/servers/{id}/.well-known/**` - Server-specific well-known URIs

### Static Assets
- `/static/**` - Static files
- `/` - Root redirect (to `/v1/admin/` when UI enabled)
- `/favicon.ico` - Favicon

### Internal APIs
- `/api/logs/**` - Log search (internal structured-logging query)
- `/api/metrics/**` - Metrics maintenance (cleanup/rollup operations)

### LLM Proxy
- `{llm_api_prefix}` - Runtime-configurable LLM proxy prefix (default `/v1`)

## Deprecation Headers

Legacy routes return the following deprecation headers:

```http
Sunset: Wed, 13 May 2026 00:00:00 GMT
Deprecation: true
Link: </v1/path>; rel="successor-version"
X-Deprecated-Endpoint: This endpoint is deprecated. Please use /v1/path instead. This endpoint will be removed on Wed, 13 May 2026 00:00:00 GMT.
```

## Migration Timeline

### Phase 1: Dual Operation (Current - May 13, 2026)
- Both `/v1/*` and legacy routes are active
- Legacy routes return deprecation headers
- Clients can migrate at their own pace
- **Action Required**: Update your clients to use `/v1` prefix

### Phase 2: Legacy Deprecation (May 13, 2026)
- Legacy routes will be disabled via `LEGACY_API_ENABLED=false`
- Legacy routes will return `404 Not Found`
- Only `/v1/*` routes will remain active
- Excluded routes continue at root level

## Configuration

### Enable/Disable Legacy Routes

```bash
# Enable legacy routes (default)
LEGACY_API_ENABLED=true

# Disable legacy routes (after migration)
LEGACY_API_ENABLED=false
```

### Customize Sunset Date

```bash
# RFC 8594 format
LEGACY_API_SUNSET_DATE="Wed, 13 May 2026 00:00:00 GMT"
```

## Client Examples

### cURL

```bash
# Before
curl http://localhost:4444/tools

# After
curl http://localhost:4444/v1/tools
```

### Python

```python
# Before
response = requests.get("http://localhost:4444/tools")

# After
response = requests.get("http://localhost:4444/v1/tools")
```

### JavaScript

```javascript
// Before
fetch('http://localhost:4444/tools')

// After
fetch('http://localhost:4444/v1/tools')
```

## OpenAPI Schema

The OpenAPI schema automatically reflects the `/v1` prefix. Access it at:

```bash
# Swagger UI
http://localhost:4444/docs

# OpenAPI JSON
http://localhost:4444/openapi.json
```

Legacy routes are not included in the OpenAPI schema by design.

## Testing Your Migration

### Check for Deprecation Headers

```bash
curl -I http://localhost:4444/tools
# Should include:
# Sunset: Wed, 13 May 2026 00:00:00 GMT
# Deprecation: true
# Link: </v1/tools>; rel="successor-version"
```

### Verify v1 Routes Work

```bash
curl http://localhost:4444/v1/tools
# Should return 200 without deprecation headers
```

### Test with Legacy Disabled

```bash
# Set in .env
LEGACY_API_ENABLED=false

# Restart server
make serve

# Test legacy route (should 404)
curl http://localhost:4444/tools
# Expected: 404 Not Found

# Test v1 route (should work)
curl http://localhost:4444/v1/tools
# Expected: 200 OK
```

## Troubleshooting

### Issue: Getting 404 on v1 routes

**Solution**: Ensure you're using the correct `/v1` prefix and the feature is enabled for that route.

### Issue: Not seeing deprecation headers

**Solution**: Check that:
1. You're calling a legacy route (without `/v1` prefix)
2. `LEGACY_API_ENABLED=true` (default)
3. The route is not in the excluded list

### Issue: Admin UI not loading

**Solution**: The admin UI is now at `/v1/admin/`. Update your bookmarks or use the root redirect at `/`.

## FAQ

### Q: Do I need to update my MCP client configuration?

**A**: No, the `/mcp` endpoint remains unversioned as required by the MCP protocol specification.

### Q: What happens to my existing API tokens?

**A**: API tokens work with both legacy and `/v1` routes. No changes needed.

### Q: Can I use both legacy and v1 routes during migration?

**A**: Yes, both routes are active until May 13, 2026. This allows gradual migration.

### Q: Will the OpenAPI schema include legacy routes?

**A**: No, the OpenAPI schema only includes `/v1` routes. Legacy routes are for backward compatibility only.

### Q: What if I can't migrate by May 13, 2026?

**A**: Contact the ContextForge team to discuss extension options. However, we strongly recommend migrating as soon as possible.

## Support

For migration assistance:
- GitHub Issues: [https://github.com/IBM/mcp-context-forge/issues](https://github.com/IBM/mcp-context-forge/issues)
- Documentation: [https://ibm.github.io/mcp-context-forge/](https://ibm.github.io/mcp-context-forge/)
