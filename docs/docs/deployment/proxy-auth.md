# Proxy Authentication

This guide explains how to configure MCP Gateway to work with authentication proxies like OAuth2 Proxy, Authelia, Cloudflare Access, or enterprise API gateways.

## Overview

When MCP Gateway is deployed behind an authentication proxy, you can disable its built-in JWT authentication and trust the proxy to handle user authentication. This is common in enterprise environments where authentication is centralized.

## Architecture

```
User → Auth Proxy (OAuth/SAML) → MCP Gateway → MCP Servers
         ↓
    Identity Provider
    (Okta, Auth0, Azure AD)
```

## Configuration

### Environment Variables

To enable proxy authentication, configure these environment variables:

```bash
# Disable JWT authentication for MCP operations
MCP_CLIENT_AUTH_ENABLED=false

# REQUIRED: Explicitly trust proxy authentication
# Only set this when MCP Gateway is behind a trusted proxy!
TRUST_PROXY_AUTH=true

# Header containing the authenticated username from proxy
# Default: X-Authenticated-User
PROXY_USER_HEADER=X-Authenticated-User

# Keep admin UI authentication enabled (optional)
AUTH_REQUIRED=true
```

### Security Warning

⚠️ **IMPORTANT**: Only disable MCP client authentication when MCP Gateway is deployed behind a trusted authentication proxy. Setting `MCP_CLIENT_AUTH_ENABLED=false` without `TRUST_PROXY_AUTH=true` will log a warning, as this removes a critical security layer.

## Common Proxy Configurations

### OAuth2 Proxy

OAuth2 Proxy is a popular reverse proxy that provides authentication using OAuth2 providers.

```yaml
# docker-compose.yml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    ports:
      - "4180:4180"
    environment:
      OAUTH2_PROXY_CLIENT_ID: your-client-id
      OAUTH2_PROXY_CLIENT_SECRET: your-client-secret
      OAUTH2_PROXY_COOKIE_SECRET: your-cookie-secret
      OAUTH2_PROXY_UPSTREAMS: http://mcp-gateway:4444
      OAUTH2_PROXY_PASS_USER_HEADERS: true
      OAUTH2_PROXY_SET_XAUTHREQUEST: true
    
  mcp-gateway:
    image: ghcr.io/contingentai/mcp-gateway:latest
    environment:
      MCP_CLIENT_AUTH_ENABLED: false
      TRUST_PROXY_AUTH: true
      PROXY_USER_HEADER: X-Auth-Request-User
```

### Authelia

Authelia is a complete authentication and authorization server.

```yaml
# Example Authelia forward auth configuration
services:
  authelia:
    image: authelia/authelia
    volumes:
      - ./authelia:/config
    environment:
      TZ: America/New_York
  
  mcp-gateway:
    image: ghcr.io/contingentai/mcp-gateway:latest
    environment:
      MCP_CLIENT_AUTH_ENABLED: false
      TRUST_PROXY_AUTH: true
      PROXY_USER_HEADER: Remote-User
    labels:
      - "traefik.http.routers.mcp.middlewares=authelia@docker"
```

### Cloudflare Access

For Cloudflare Access, configure the gateway to read the authenticated user from Cloudflare's headers:

```bash
MCP_CLIENT_AUTH_ENABLED=false
TRUST_PROXY_AUTH=true
PROXY_USER_HEADER=Cf-Access-Authenticated-User-Email
```

### AWS API Gateway

When using AWS API Gateway with Lambda authorizers:

```bash
MCP_CLIENT_AUTH_ENABLED=false
TRUST_PROXY_AUTH=true
PROXY_USER_HEADER=X-Authenticated-User
```

Configure your Lambda authorizer to add the authenticated username to the context:

```python
# Lambda authorizer example
def lambda_handler(event, context):
    # Validate token...
    return {
        'principalId': user_id,
        'context': {
            'authenticatedUser': user_email
        }
    }
```

## Header Passthrough

When using proxy authentication, you may want to pass additional headers to downstream MCP servers:

```bash
# Enable header passthrough
ENABLE_HEADER_PASSTHROUGH=true

# Headers to pass through (JSON array)
DEFAULT_PASSTHROUGH_HEADERS='["X-Tenant-Id", "X-Request-Id", "X-Authenticated-User"]'
```

## Kubernetes with Istio

In a service mesh with Istio, you can use JWT validation at the mesh level:

```yaml
apiVersion: security.istio.io/v1beta1
kind: RequestAuthentication
metadata:
  name: mcp-gateway-auth
spec:
  selector:
    matchLabels:
      app: mcp-gateway
  jwtRules:
  - issuer: "https://your-issuer.com"
    jwksUri: "https://your-issuer.com/.well-known/jwks.json"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-gateway-config
data:
  MCP_CLIENT_AUTH_ENABLED: "false"
  TRUST_PROXY_AUTH: "true"
  PROXY_USER_HEADER: "X-User-Id"
```

## Testing Proxy Authentication

To test your proxy authentication setup:

1. **Without proxy headers (should fail or return anonymous):**
```bash
curl http://localhost:4444/tools
# Returns 401 or anonymous access depending on AUTH_REQUIRED
```

2. **With proxy headers:**
```bash
curl -H "X-Authenticated-User: john.doe@example.com" \
     http://localhost:4444/tools
# Should return tools list for authenticated user
```

3. **WebSocket with proxy auth:**
```javascript
const ws = new WebSocket('ws://localhost:4444/ws', {
  headers: {
    'X-Authenticated-User': 'john.doe@example.com'
  }
});
```

## Troubleshooting

### Warning: MCP auth disabled without trust

If you see this warning in logs:
```
WARNING - MCP client authentication is disabled but trust_proxy_auth is not set
```

**Solution**: Set `TRUST_PROXY_AUTH=true` to acknowledge you're using proxy authentication.

### Authentication still required

**Problem**: Getting 401 errors even with proxy headers.

**Check**:
1. Verify `MCP_CLIENT_AUTH_ENABLED=false`
2. Ensure `TRUST_PROXY_AUTH=true`
3. Confirm header name matches `PROXY_USER_HEADER`
4. Check proxy is actually sending the header

### WebSocket connections fail

**Problem**: WebSocket connections are rejected.

**Solution**: Ensure your proxy passes headers to WebSocket upgrade requests. Some proxies require special configuration for WebSocket support.

## Migration from JWT Authentication

To migrate from JWT to proxy authentication:

1. **Deploy proxy** alongside existing setup
2. **Test proxy** authentication with a subset of users
3. **Update environment**:
   ```bash
   MCP_CLIENT_AUTH_ENABLED=false
   TRUST_PROXY_AUTH=true
   PROXY_USER_HEADER=X-Authenticated-User
   ```
4. **Monitor logs** for authentication issues
5. **Remove JWT** token generation once stable

## Security Best Practices

1. **Never expose MCP Gateway directly** when proxy auth is enabled
2. **Use TLS** between proxy and gateway
3. **Validate proxy certificates** in production
4. **Monitor** authentication logs for anomalies
5. **Implement rate limiting** at the proxy level
6. **Use network policies** to ensure only the proxy can reach the gateway

## Example: Complete Setup with Traefik

```yaml
# docker-compose.yml
version: '3.8'

services:
  traefik:
    image: traefik:v2.10
    command:
      - "--providers.docker=true"
      - "--entrypoints.web.address=:80"
    ports:
      - "80:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    environment:
      OAUTH2_PROXY_CLIENT_ID: ${CLIENT_ID}
      OAUTH2_PROXY_CLIENT_SECRET: ${CLIENT_SECRET}
      OAUTH2_PROXY_COOKIE_SECRET: ${COOKIE_SECRET}
      OAUTH2_PROXY_PROVIDER: google
      OAUTH2_PROXY_EMAIL_DOMAINS: "*"
      OAUTH2_PROXY_UPSTREAMS: "http://mcp-gateway:4444/"
      OAUTH2_PROXY_HTTP_ADDRESS: "0.0.0.0:4180"
      OAUTH2_PROXY_PASS_USER_HEADERS: "true"
      OAUTH2_PROXY_SET_XAUTHREQUEST: "true"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.oauth2-proxy.rule=Host(`mcp.example.com`)"
      - "traefik.http.services.oauth2-proxy.loadbalancer.server.port=4180"

  mcp-gateway:
    image: ghcr.io/contingentai/mcp-gateway:latest
    environment:
      MCP_CLIENT_AUTH_ENABLED: "false"
      TRUST_PROXY_AUTH: "true"
      PROXY_USER_HEADER: "X-Auth-Request-Email"
      AUTH_REQUIRED: "true"  # Keep admin UI protected
      BASIC_AUTH_USER: ${ADMIN_USER}
      BASIC_AUTH_PASSWORD: ${ADMIN_PASSWORD}
    volumes:
      - ./data:/data
```

This configuration provides Google OAuth authentication for all MCP Gateway endpoints while maintaining separate admin UI authentication.