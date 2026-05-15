# HTTP Redirect Handling - Migration Guide

## Overview

As part of ongoing security hardening, ContextForge now disables HTTP redirect following on all outbound requests. This is a **breaking change** that may affect integrations relying on HTTP redirects.

**Change**: All HTTP clients now have `follow_redirects=False`, returning 302/301 responses instead of following redirects.

**Rationale**: This change implements defense-in-depth security by ensuring all outbound requests go to explicitly registered destinations, preventing unintended request routing.

---

## Breaking Scenarios and Mitigations

### 1. REST Tool Invocations with Redirect-Based APIs

#### What Changes

**Scenario**: REST tool registered with a URL that returns HTTP redirects (302/301/307/308).

**Example**:
```json
{
  "name": "url-shortener-tool",
  "url": "https://short.link/abc123",
  "method": "GET"
}
```

**Previous Behavior**: ContextForge followed redirect to `https://actual-destination.com/resource` and returned final content.

**New Behavior**: ContextForge returns 302 response with `Location` header, does NOT fetch final destination.

#### Mitigation

**Option 1: Register Final Destination URL (Recommended)**
```json
{
  "name": "url-shortener-tool",
  "url": "https://actual-destination.com/resource",
  "method": "GET"
}
```

**Option 2: Update Upstream Service**

Configure your upstream API to return final URLs directly instead of redirects.

---

### 2. Gateway Health Checks with Redirect-Based Endpoints

#### What Changes

**Scenario**: MCP gateway URL returns redirect to actual health endpoint.

**Example**:
```json
{
  "name": "my-mcp-gateway",
  "url": "https://gateway.example.com/mcp",
  "health_check_enabled": true
}
```

If `https://gateway.example.com/mcp` returns `302 → https://gateway.example.com/v2/mcp`, health checks may fail.

#### Mitigation

**Option 1: Register Final URL Directly**
```json
{
  "name": "my-mcp-gateway",
  "url": "https://gateway.example.com/v2/mcp",
  "health_check_enabled": true
}
```

**Option 2: Update Gateway Configuration**

Configure your MCP gateway to serve the endpoint directly without redirects.

---

### 3. SSE (Server-Sent Events) Gateway Connections

#### What Changes

**Scenario**: MCP gateway SSE endpoint uses redirects for load balancing or versioning.

**Example**:
```
Client → https://gateway.example.com/sse
         ↓ 302 Location: https://gateway-node-1.example.com/sse
         ✗ Connection fails (redirect not followed)
```

**Impact**: Real-time MCP tool/resource updates via SSE stop working.

#### Mitigation

**Option 1: Register Final SSE Endpoint**

Determine actual SSE endpoint (after redirect) and register it directly:
```json
{
  "name": "my-gateway",
  "url": "https://gateway-node-1.example.com/sse",
  "transport": "sse"
}
```

**Option 2: Use Load Balancer with Stable URL**

Configure load balancer to serve SSE on stable URL without redirects.

---

### 4. StreamableHTTP Gateway Connections

#### What Changes

**Scenario**: StreamableHTTP endpoint redirects to different host or path.

**Example**:
```
POST https://api.example.com/stream
→ 307 Temporary Redirect: https://stream-api.example.com/v2/stream
✗ Request fails (redirect not followed)
```

**Impact**: Streaming tool responses (large payloads, incremental results) fail.

#### Mitigation

**Register Final Streaming Endpoint**:
```json
{
  "url": "https://stream-api.example.com/v2/stream",
  "transport": "streamable_http"
}
```

---

### 5. A2A (Agent-to-Agent) Endpoint Invocations

#### What Changes

**Scenario**: A2A agent endpoint uses redirects for routing or versioning.

**Example**:
```json
{
  "name": "my-a2a-agent",
  "endpoint_url": "https://agents.example.com/agent/v1",
  "protocol": "http"
}
```

If endpoint returns `302 → https://agents.example.com/agent/v2`, A2A calls fail.

#### Mitigation

**Option 1: Register Final Agent URL**
```json
{
  "endpoint_url": "https://agents.example.com/agent/v2"
}
```

**Option 2: Use UAID Cross-Gateway Routing**

If agents are on different ContextForge instances:
```json
{
  "protocol": "uaid",
  "uaid": "agent://other-gateway.example.com/my-agent"
}
```

---

## Testing Your Integration After Upgrade

### 1. Test Tool Invocations

```bash
curl -X POST https://your-contextforge/rpc \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {"name": "your-tool", "arguments": {}},
    "id": 1
  }'

# Check for 302 responses in tool output
# If you see "status_code": 302, the tool uses redirects
```

### 2. Test Gateway Health Checks

```bash
curl https://your-contextforge/admin/gateways \
  -H "Authorization: Bearer $TOKEN"

# Look for "health_status": "unhealthy" on gateways that previously worked
```

### 3. Test SSE Connections

```bash
curl -N https://your-contextforge/mcp/sse/your-server \
  -H "Authorization: Bearer $TOKEN"

# Should receive SSE events, not redirect response
```

### 4. Test A2A Invocations

```bash
curl -X POST https://your-contextforge/a2a/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "agent_id": "your-agent-id",
    "input": {"query": "test"}
  }'

# Check for errors indicating redirect failures
```

---

## Security Hardening Benefits

### Defense-in-Depth Architecture

This change implements **defense-in-depth** security:

1. **Layer 1**: URL validation at registration (existing)
2. **Layer 2**: Redirect blocking at invocation (new)

By disabling redirect following, ContextForge ensures that all outbound requests go to explicitly registered and validated destinations. This prevents unintended request routing and strengthens the overall security posture.

### Best Practices

- **Explicit Destinations**: Register final destination URLs directly
- **Stable Endpoints**: Configure services to use stable URLs without redirects
- **Load Balancer Configuration**: Use load balancers that provide stable URLs
- **Regular Testing**: Verify integrations after upgrades to catch redirect-related issues

---

## Frequently Asked Questions

### Q: Can I enable redirects for specific tools?

**A**: No. Redirect blocking is applied globally to all HTTP clients as part of our security hardening. This ensures consistent security behavior across all integrations.

### Q: What about legitimate CDN redirects?

**A**: Register the final CDN URL directly. Most CDNs provide stable URLs that don't require redirects.

### Q: Will this affect OAuth flows?

**A**: No. OAuth authorization flows use **browser redirects**, not server-side HTTP clients. The user's browser follows redirects naturally.

### Q: How do I know if my integration uses redirects?

**A**: Test your registered URLs with `curl -I`:
```bash
curl -I https://your-tool-url
# If you see "HTTP/1.1 302 Found" or "HTTP/1.1 301 Moved Permanently", it uses redirects
```

### Q: Is this a bug or a feature?

**A**: This is a **security hardening enhancement** that changes behavior. While it may require updates to some integrations, it strengthens the overall security posture of ContextForge.

---

## Rollback Plan (Not Recommended)

If you need to temporarily restore redirect-following behavior for testing:

### Pin to Previous Version

```bash
# Docker
docker pull ghcr.io/ibm/mcp-context-forge:v1.0.0

# Helm
helm install contextforge contextforge/mcp-stack --version 1.0.0
```

**Note**: Rolling back removes the security hardening. Only use in isolated test environments.

---

## Related Documentation

- [SECURITY.md](../../../SECURITY.md) - SSRF Protection section
- [CHANGELOG.md](../../../CHANGELOG.md) - Breaking Changes section

---

**Last Updated**: 2026-05-15
**Applies To**: ContextForge versions later than v1.0.1
