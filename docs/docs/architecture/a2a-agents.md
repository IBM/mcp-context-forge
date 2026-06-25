# A2A Agent Architecture

## Overview

Agent-to-Agent (A2A) agents enable ContextForge to federate and orchestrate downstream AI agents, creating complex agent chains and workflows. This document covers the architecture and key features of A2A agents.

## Core Concepts

### Agent Registration

A2A agents are registered with:
- **Name**: Unique identifier for the agent
- **Endpoint URL**: HTTP(S) endpoint where the agent is hosted
- **Protocol Version**: A2A protocol version (e.g., "1.0")
- **Authentication**: Optional auth configuration (bearer, basic, OAuth)
- **Team/Visibility**: Team scoping and access control

### Agent Invocation

Agents can be invoked via:
- `/a2a/{agent_name}/invoke` - Invoke by name
- `/a2a/agents/{agent_id}/invoke` - Invoke by ID

---

## Passthrough Headers

### Overview

Passthrough headers enable context propagation through agent chains. When an agent invokes a downstream agent, specific headers from the original request can be forwarded to maintain tenant context, request tracing, and custom metadata.

### Configuration

**Agent-Level Whitelist:**

Each A2A agent can specify which headers to forward via the `passthrough_headers` field:

```json
{
  "name": "downstream-agent",
  "endpoint_url": "https://agent.example.com/api",
  "passthrough_headers": ["X-Tenant-ID", "X-Request-ID", "X-Trace-ID"]
}
```

**Admin UI Configuration:**

Enter headers as comma-separated values (no quotes):
```
X-Tenant-ID, X-Request-ID, X-Trace-ID
```

### Behavior

**Whitelist Enforcement:**
- Only headers explicitly listed in `passthrough_headers` are forwarded
- Case-insensitive matching (e.g., "X-Tenant-ID" matches "x-tenant-id")
- Fail-closed: Empty or missing whitelist = no headers forwarded

**Example Flow:**

```
Client Request:
  Authorization: Bearer token123
  X-Tenant-ID: acme-corp
  X-Request-ID: req-456
  X-Custom: should-not-forward

Agent Config:
  passthrough_headers: ["X-Tenant-ID", "X-Request-ID"]

Downstream Receives:
  X-Tenant-ID: acme-corp        ✓ Forwarded
  X-Request-ID: req-456         ✓ Forwarded
  X-Correlation-ID: <generated> ✓ Auto-added
  Content-Type: application/json
```

### Sensitive Header Handling

**Default Behavior (ENABLE_SENSITIVE_HEADER_PASSTHROUGH=false):**

By default, sensitive headers are **blocked at the router level** even if whitelisted:

**Blocked Headers:**
- `Authorization`, `Proxy-Authorization`
- `X-API-Key`, `API-Key`, `APIKey`
- `Cookie`, `Set-Cookie`
- `X-{Auth|API|Access|Refresh|Client|Bearer|Session|Security}-{Token|Secret|Key}`

**Example:**
```json
{
  "passthrough_headers": ["Authorization", "X-Tenant-ID"]
}
```

With default settings:
- `Authorization`: ❌ Blocked (sensitive header)
- `X-Tenant-ID`: ✓ Forwarded

**Opt-In Sensitive Header Forwarding:**

Set `ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true` to allow whitelisted sensitive headers:

```bash
# .env
ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true
```

With this flag enabled:
- `Authorization`: ✓ Forwarded (if whitelisted)
- `X-Tenant-ID`: ✓ Forwarded

⚠️ **Security Note:** Only enable this flag if you need to forward credentials to downstream agents and trust those agents with sensitive headers.

### Plugin Hook Security

**Critical Security Invariant:**

Plugin hooks **NEVER** receive sensitive headers, regardless of the `ENABLE_SENSITIVE_HEADER_PASSTHROUGH` flag state.

**Why:** Plugin code runs with elevated privileges. Exposing credentials to plugins creates a security risk where compromised or malicious plugins could exfiltrate credentials.

**Architecture:**

```
Request Headers
      ↓
Router Filtering (conditional on flag)
      ↓
Service: Split Flows
      ↓
  ┌───┴───┐
  ↓       ↓
Plugin  Downstream
Headers Headers
(ALWAYS (Respects
filtered) flag)
```

**Example with Flag ON:**

```
Request: Authorization + X-Tenant-ID
Agent whitelist: ["Authorization", "X-Tenant-ID"]
Flag: ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true

Plugin Hook Receives:
  X-Tenant-ID: acme-corp  ✓ Only non-sensitive

Downstream Agent Receives:
  Authorization: Bearer token  ✓ Sensitive headers included
  X-Tenant-ID: acme-corp
```

### Plugin Header Modification Security

**Defense-in-Depth for Plugin-Returned Headers:**

When plugins modify headers via `modified_payload.headers` in pre-invoke hooks, the gateway re-applies **both** security layers before forwarding to downstream agents:

1. **Sensitive header filtering** (if `ENABLE_SENSITIVE_HEADER_PASSTHROUGH=false`)
2. **Agent's `passthrough_headers` whitelist**

This prevents malicious or compromised plugins from injecting sensitive headers into downstream requests, even though the plugin received sanitized headers initially.

**Example Attack Scenario (Prevented):**

```python
# Plugin receives sanitized headers (no Authorization)
plugin_headers = {"X-Custom-Header": "value"}  # Sensitive headers filtered out

# Malicious plugin attempts to inject Authorization in return payload
modified_payload.headers = {
    "Authorization": "Bearer malicious",  # ❌ Blocked by re-filtering
    "X-Custom-Header": "modified",       # ✓ Allowed (in whitelist)
}

# Actual headers sent downstream (after re-filtering)
downstream_headers = {"X-Custom-Header": "modified"}  # Authorization removed
```

**Security Guarantees:**

- Plugins cannot bypass the `ENABLE_SENSITIVE_HEADER_PASSTHROUGH` flag
- Plugins cannot inject headers not in the agent's `passthrough_headers` whitelist
- Security policy violations are logged with details for audit trails
- This defense applies even when `ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true` (flag only controls initial forwarding, not plugin injection)

**Related:** Issue #3621 Phase 1, PR #5183 security review fix

### Use Cases

**1. Multi-Tenant Context Propagation**

```json
{
  "name": "tenant-aware-agent",
  "passthrough_headers": ["X-Tenant-ID", "X-Org-ID"]
}
```

Ensures tenant context flows through agent chains for proper data isolation.

**2. Distributed Tracing**

```json
{
  "name": "traced-agent",
  "passthrough_headers": ["X-Trace-ID", "X-Request-ID", "X-Correlation-ID"]
}
```

Maintains trace context across agent boundaries for observability.

**3. Custom Metadata**

```json
{
  "name": "metadata-agent",
  "passthrough_headers": ["X-User-Role", "X-Feature-Flags", "X-Client-Version"]
}
```

Forwards application-specific metadata for downstream decision-making.

### Security Considerations

**Whitelist Carefully:**
- Only whitelist headers that downstream agents need
- Avoid wildcards or overly permissive patterns
- Review whitelists regularly

**Sensitive Headers:**
- Default: Sensitive headers are blocked (secure default)
- Only enable `ENABLE_SENSITIVE_HEADER_PASSTHROUGH` if necessary
- Understand that enabled flag allows credentials to flow to downstream agents

**Audit Logging:**
- All forwarded headers are logged (keys only, not values)
- Format: `A2A passthrough headers forwarded to downstream agent '<name>': ['x-tenant-id', 'x-request-id'] (user: <email>, agent_id: <id>)`

**Observability Metrics:**
When `OBSERVABILITY_ENABLED=true`, ContextForge records a counter metric for each A2A request with forwarded headers:

- **Metric Name:** `a2a.downstream_headers.forwarded`
- **Type:** Counter
- **Value:** Count of headers forwarded in the request
- **Attributes:**
  - `agent_name`: Name of the downstream A2A agent
  - `agent_id`: UUID of the downstream A2A agent
  - `user_email`: Email of the requesting user (or "anonymous")
  - `sensitive_passthrough_enabled`: Boolean indicating if sensitive header passthrough is enabled

Use these attributes for alerting, dashboards, and security auditing.

**Defense-in-Depth:**
- Router-level filtering (first line of defense)
- Service-level filtering (second line of defense)
- Plugin hook protection (always enforced)

### Configuration Reference

**Environment Variables:**

```bash
# Enable sensitive header passthrough (default: false)
ENABLE_SENSITIVE_HEADER_PASSTHROUGH=false
```

**Startup Warning:**
When `ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true`, ContextForge logs a security audit warning at startup:

```
🔐 SECURITY AUDIT: Sensitive Header Passthrough ENABLED - whitelisted sensitive headers
(Authorization, X-API-Key, etc.) will be forwarded to downstream A2A agents. Monitor metric
'a2a.downstream_headers.forwarded' for visibility (requires OBSERVABILITY_ENABLED=true).
Only enable when trusted A2A agents require upstream credentials.
```

This warning reminds operators that sensitive credentials can flow to downstream agents.

**Agent Schema:**

```json
{
  "name": "string",
  "endpoint_url": "string",
  "passthrough_headers": ["string"],  // Optional, default: null
  ...
}
```

**Validation:**
- `passthrough_headers`: Array of strings or null
- Empty array `[]` = explicit "no headers"
- `null` = no passthrough configuration
- Header names must be valid RFC 7230 tokens (alphanumeric plus `!#$%&'*+-.^_` + "`" + `|~`)

### Troubleshooting

**Headers Not Being Forwarded:**

1. Check agent configuration has `passthrough_headers` defined
2. Verify header names match exactly (case-insensitive)
3. Check if header is sensitive (blocked by default)
4. Review audit logs for forwarded headers

**Sensitive Headers Blocked:**

1. Verify `ENABLE_SENSITIVE_HEADER_PASSTHROUGH` flag state
2. Check header matches sensitive patterns
3. Consider using non-sensitive custom headers instead

**Plugin Hooks Not Receiving Headers:**

This is **expected behavior** for sensitive headers. Plugin hooks are intentionally protected from receiving credentials.

---

## Related Documentation

- [Security Features](security-features.md)
- [RBAC](../manage/rbac.md)
- [Multi-Tenancy](multitenancy.md)
