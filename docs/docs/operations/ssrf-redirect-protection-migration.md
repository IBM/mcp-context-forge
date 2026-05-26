

[BREAKING CHANGE]

SSRF Redirect Protection - Migration Guide

Overview

ContextForge now blocks HTTP redirects on all SSRF-sensitive outbound requests to prevent redirect-based SSRF attacks. This is a breaking change that may affect legitimate integrations relying on HTTP redirects.

Security Context: Previously, attacker with resource creation permissions could craft SSRF attacks by redirecting SSRF requests to internal resources. This was a critical security vulnerability.

Fix: All HTTP clients now have follow_redirects=False, returning 302/301 responses instead of following redirects.
Breaking Scenarios and Mitigations
1. REST Tool Invocations with Redirect-Based APIs
What Breaks

Scenario: REST tool registered with a URL that returns HTTP redirects (302/301/307/308).

Example:

{
  "name": "url-shortener-tool",
  "url": "https://short.link/abc123",
  "method": "GET"
}

Previous Behavior: ContextForge followed redirect to https://actual-destination.com/resource and returned final content.

New Behavior: ContextForge returns 302 response with Location header, does NOT fetch final destination.
Mitigation

Option 1: Register Final Destination URL (Recommended)

{
  "name": "url-shortener-tool",
  "url": "https://actual-destination.com/resource",
  "method": "GET"
}

Option 2: Update Upstream Service

Configure your upstream API to return final URLs directly instead of redirects.
2. Gateway Health Checks with Redirect-Based Endpoints
What Breaks

Scenario: MCP gateway URL returns redirect to actual health endpoint.

Example:

{
  "name": "my-mcp-gateway",
  "url": "https://gateway.example.com/mcp",
  "health_check_enabled": true
}

If https://gateway.example.com/mcp returns 302 → https://gateway.example.com/v2/mcp, health checks may fail.
Mitigation

Option 1: Register Final URL Directly

{
  "name": "my-mcp-gateway",
  "url": "https://gateway.example.com/v2/mcp",
  "health_check_enabled": true
}

Option 2: Update Gateway Configuration

Configure your MCP gateway to serve the endpoint directly without redirects.
3. SSE (Server-Sent Events) Gateway Connections
What Breaks

Scenario: MCP gateway SSE endpoint uses redirects for load balancing or versioning.

Example:

Client → https://gateway.example.com/sse
         ↓ 302 Location: https://gateway-node-1.example.com/sse
         ✗ Connection fails (redirect not followed)

Impact: Real-time MCP tool/resource updates via SSE stop working.
Mitigation

Option 1: Register Final SSE Endpoint

Determine actual SSE endpoint (after redirect) and register it directly:

{
  "name": "my-gateway",
  "url": "https://gateway-node-1.example.com/sse",
  "transport": "sse"
}

Option 2: Use Load Balancer with Stable URL

Configure load balancer to serve SSE on stable URL without redirects.
4. StreamableHTTP Gateway Connections
What Breaks

Scenario: StreamableHTTP endpoint redirects to different host or path.

Example:

POST https://api.example.com/stream
→ 307 Temporary Redirect: https://stream-api.example.com/v2/stream
✗ Request fails (redirect not followed)

Impact: Streaming tool responses (large payloads, incremental results) fail.
Mitigation

Register Final Streaming Endpoint:

{
  "url": "https://stream-api.example.com/v2/stream",
  "transport": "streamable_http"
}

5. A2A (Agent-to-Agent) Endpoint Invocations
What Breaks

Scenario: A2A agent endpoint uses redirects for routing or versioning.

Example:

{
  "name": "my-a2a-agent",
  "endpoint_url": "https://agents.example.com/agent/v1",
  "protocol": "http"
}

If endpoint returns 302 → https://agents.example.com/agent/v2, A2A calls fail.
Mitigation

Option 1: Register Final Agent URL

{
  "endpoint_url": "https://agents.example.com/agent/v2"
}

Option 2: Use UAID Cross-Gateway Routing

If agents are on different ContextForge instances:

{
  "protocol": "uaid",
  "uaid": "agent://other-gateway.example.com/my-agent"
}

Testing Your Integration After Upgrade
1. Test Tool Invocations

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

2. Test Gateway Health Checks

curl https://your-contextforge/admin/gateways \
  -H "Authorization: Bearer $TOKEN"

# Look for "health_status": "unhealthy" on gateways that previously worked

3. Test SSE Connections

curl -N https://your-contextforge/mcp/sse/your-server \
  -H "Authorization: Bearer $TOKEN"

# Should receive SSE events, not redirect response

4. Test A2A Invocations

curl -X POST https://your-contextforge/a2a/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "agent_id": "your-agent-id",
    "input": {"query": "test"}
  }'

# Check for errors indicating redirect failures

Why This Change Is Necessary
Attack Scenario (Before Fix)

    Attacker with tools.create permission registers tool:

    {
      "name": "malicious-tool",
      "url": "https://attacker.com/redirect"
    }

    ContextForge validates https://attacker.com/redirect (public URL, passes SSRF check).

    Attacker's server returns:

    HTTP/1.1 302 Found
    Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/

    Before fix: ContextForge follows redirect, fetches AWS credentials, returns them to attacker.

    After fix: ContextForge returns 302 response, does NOT fetch metadata.

Defense-in-Depth

This fix implements defense-in-depth:

    Layer 1: SSRF validation at registration (existing)
    Layer 2: Redirect blocking at invocation (new)

Even if Layer 1 is bypassed (e.g., DNS rebinding, TOCTOU), Layer 2 prevents exploitation.
Frequently Asked Questions
Q: Can I enable redirects for specific tools?

A: No. Redirect blocking is applied globally to all SSRF-sensitive HTTP clients for security. Allowing per-tool configuration would reintroduce the vulnerability.
Q: What about legitimate CDN redirects?

A: Register the final CDN URL directly. Most CDNs provide stable URLs that don't require redirects.
Q: Will this affect OAuth flows?

A: No. OAuth authorization flows use browser redirects, not server-side HTTP clients. The user's browser follows redirects naturally.
Q: How do I know if my integration uses redirects?

A: Test your registered URLs with curl -I:

curl -I https://your-tool-url
# If you see "HTTP/1.1 302 Found" or "HTTP/1.1 301 Moved Permanently", it uses redirects

Q: Is this a bug or a feature?

A: This is a security fix that changes behavior. While it may break some integrations, the previous behavior was a security vulnerability.
Rollback Plan (Not Recommended)

If you need to temporarily restore redirect-following behavior:
Pin to Pre-Fix Version

# Docker
docker pull ghcr.io/ibm/mcp-context-forge:v1.0.0

# Helm
helm install contextforge contextforge/mcp-stack --version 1.0.0

WARNING: This re-introduces the SSRF vulnerability. Only use in isolated environments.
Related Documentation

    SECURITY.md - SSRF Protection section
    CHANGELOG.md - Breaking Changes section

Last Updated: 2026-05-14
Applies To: ContextForge versions later than v1.0.1
