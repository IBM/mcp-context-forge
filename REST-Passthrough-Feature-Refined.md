# Feature Request: REST Passthrough APIs with Pre/Post Plugins

## Summary
Add first-class passthrough support for upstream REST APIs. When a REST API is registered as a tool, the gateway exposes a corresponding HTTP passthrough endpoint that forwards requests to the upstream, with plugin hooks before and after the call for validation, enrichment, filtering, transformation, and auditing.

## Current Implementation Status

### ✅ Already Implemented (Database & Schema Layer)

The following fields have been **successfully added** to the `Tool` model in `mcpgateway/db.py` (lines 2819-2828):

```python
# Passthrough REST fields
base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
path_template: Mapped[Optional[str]] = mapped_column(String, nullable=True)
query_mapping: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
header_mapping: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
timeout_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
expose_passthrough: Mapped[bool] = mapped_column(Boolean, default=True)
allowlist: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
plugin_chain_pre: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
plugin_chain_post: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
```

The corresponding Pydantic schemas in `mcpgateway/schemas.py` include:
- `ToolCreate` (lines 750-858): Full validation for all passthrough fields
- `ToolUpdate` (lines 860-1020): Partial update support for all passthrough fields
- Field validators for `allowlist`, `plugin_chain_pre`, `plugin_chain_post`, and `timeout_ms`

### ✅ Plugin Framework Available

The plugin framework is **fully implemented** (see `plugins/AGENTS.md`):
- Six production hooks: `prompt_pre_fetch`, `prompt_post_fetch`, `tool_pre_invoke`, `tool_post_invoke`, `resource_pre_fetch`, `resource_post_fetch`
- Plugin modes: `enforce`, `enforce_ignore_error`, `permissive`, `disabled`
- 42+ built-in plugins including: `pii_filter`, `deny_filter`, `regex_filter`, `resource_filter`, etc.
- Configuration via `plugins/config.yaml` with Jinja templating support
- External plugin support via MCP protocol

### ❌ Missing Implementation

The following components are **NOT yet implemented**:

1. **Passthrough Router** (`mcpgateway/routers/passthrough.py`)
   - No passthrough router exists (confirmed via file listing)
   - Need to create HTTP endpoints: `/passthrough/{namespace}/{tool_id}`
   - Support for path parameters, query strings, headers, and body forwarding

2. **Request Processing Pipeline**
   - URL construction from `base_url` + `path_template`
   - Query/header/body mapping logic
   - Pre-plugin execution before upstream call
   - HTTP client for upstream forwarding
   - Post-plugin execution after upstream response
   - Response transformation and streaming

3. **Security Guardrails**
   - Allowlist enforcement (field exists but no validation logic)
   - SSRF protection (private IP range blocking)
   - URL normalization and validation
   - Header redaction in logs

4. **Plugin Integration**
   - Reuse existing `tool_pre_invoke` and `tool_post_invoke` hooks for passthrough
   - Plugin chain resolution (tool-level vs. default)
   - Plugin context enrichment with passthrough metadata

5. **Configuration Defaults**
   - No `passthrough` section in `plugins/config.yaml`
   - Need default timeout, base path, and plugin chains

6. **Observability**
   - Tracing spans for passthrough pipeline
   - Metrics for upstream calls
   - Audit logging for passthrough requests

## Motivation

- **Unified consumption**: Use external REST services as both MCP tools and plain HTTP endpoints
- **Consistent cross-cutting concerns**: Apply auth, rate limiting, PII redaction, filtering via plugins
- **Reduce duplication**: Single registration for tool invocation and reverse proxy patterns
- **Discoverability**: Self-documented via OpenAPI (future enhancement)
- **JSONPath filtering**: Selective plugin application based on request/response content

## Proposed Implementation

### Phase 1: Router & Basic Pipeline (Priority: HIGH)

**File**: `mcpgateway/routers/passthrough.py`

```python
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from mcpgateway.db import get_db, Tool
from mcpgateway.plugins.framework import PluginManager

router = APIRouter(prefix="/passthrough", tags=["passthrough"])

@router.api_route("/{namespace}/{tool_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def passthrough_handler(
    namespace: str,
    tool_id: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db)
):
    # 1. Resolve tool by namespace/tool_id
    # 2. Validate expose_passthrough=True
    # 3. Construct upstream URL from base_url + path_template + path
    # 4. Apply query_mapping, header_mapping
    # 5. Run pre-plugin chain
    # 6. Forward to upstream with timeout_ms
    # 7. Run post-plugin chain
    # 8. Return response
    pass
```

**Acceptance Criteria**:
- [ ] Router handles all HTTP methods (GET, POST, PUT, DELETE, PATCH)
- [ ] Path parameters beyond `tool_id` are appended to `path_template`
- [ ] Query strings and headers are forwarded according to mappings
- [ ] Request body is forwarded for POST/PUT/PATCH
- [ ] Response status, headers, and body are returned to client

### Phase 2: Plugin Integration (Priority: HIGH)

**Approach**: Reuse existing `tool_pre_invoke` and `tool_post_invoke` hooks instead of creating new passthrough-specific hooks.

**Existing Hook Structures** (from `mcpgateway/plugins/framework/hooks/tools.py`):

```python
class ToolPreInvokePayload(PluginPayload):
    """Payload for tool pre-invoke hook."""
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class ToolPostInvokePayload(PluginPayload):
    """Payload for tool post-invoke hook."""
    name: str
    result: Dict[str, Any]
```

**Implementation Strategy**:
1. Passthrough requests will populate `ToolPreInvokePayload`:
   - `name`: Tool name/ID
   - `args`: Contains `method`, `url`, `headers`, `query_params`, `body` as dict entries
   
2. Passthrough responses will populate `ToolPostInvokePayload`:
   - `name`: Tool name/ID
   - `result`: Contains `status_code`, `headers`, `body`, `duration_ms` as dict entries

3. Plugins configured with `tool_pre_invoke` and `tool_post_invoke` hooks will automatically work for passthrough requests

**Acceptance Criteria**:
- [ ] Passthrough requests invoke `tool_pre_invoke` hook with properly formatted payload
- [ ] Passthrough responses invoke `tool_post_invoke` hook with properly formatted payload
- [ ] Existing plugins (pii_filter, deny_filter, etc.) work seamlessly with passthrough
- [ ] Plugins can mutate request args (headers, query, body) or block with violation
- [ ] Plugins can mutate response result (headers, body) or block with violation
- [ ] Plugin chain resolution: tool-level `plugin_chain_pre`/`plugin_chain_post` overrides defaults
- [ ] No new hook types needed—leverage existing 42+ plugins

### Phase 3: Security Guardrails (Priority: HIGH)

**File**: `mcpgateway/routers/passthrough.py` (security module)

```python
def validate_upstream_url(url: str, allowlist: List[str]) -> bool:
    # 1. Parse URL and extract host
    # 2. Check against allowlist (exact match or pattern)
    # 3. Block private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8)
    # 4. Normalize URL to prevent bypasses
    pass
```

**Acceptance Criteria**:
- [ ] Allowlist enforcement: reject requests to non-allowed hosts
- [ ] SSRF protection: block private IP ranges (configurable)
- [ ] URL normalization: prevent bypass via encoding, redirects
- [ ] Header redaction: sensitive headers not logged (Authorization, X-API-Key, etc.)
- [ ] JWT bearer auth required for passthrough endpoints (scope: `{namespace}:{tool_id}`)

### Phase 4: Configuration & Defaults (Priority: MEDIUM)

**File**: `plugins/config.yaml`

```yaml
passthrough:
  enabled: true
  base_path: "/passthrough"
  default_timeout_ms: 20000
  ssrf_protection:
    enabled: true
    block_private_ips: true
    block_loopback: true
  default_plugin_chains:
    pre: ["deny_filter", "regex_filter", "pii_filter"]
    post: ["pii_filter"]
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "PATCH"]
```

**Acceptance Criteria**:
- [ ] Configuration section parsed and validated at startup
- [ ] Default plugin chains applied when tool-level chains not specified
- [ ] Timeout defaults to 20000ms for REST tools with `expose_passthrough=true`
- [ ] SSRF protection configurable via settings

### Phase 5: Observability (Priority: MEDIUM)

**Integration**: OpenTelemetry spans, Prometheus metrics

```python
# Spans
with tracer.start_as_current_span("passthrough.request") as span:
    span.set_attribute("tool.id", tool_id)
    span.set_attribute("method", method)
    span.set_attribute("upstream.url", upstream_url)
    
    with tracer.start_as_current_span("passthrough.upstream"):
        # Forward request
        pass
```

**Acceptance Criteria**:
- [ ] Span: `passthrough.request` (attrs: tool.id, method, url, tenant, user)
- [ ] Span: `passthrough.upstream` (attrs: status_code, duration_ms, retries)
- [ ] Span: `passthrough.plugin_chain` (attrs: plugin_name, hook_type, duration_ms)
- [ ] Metrics: `passthrough_requests_total`, `passthrough_duration_seconds`, `passthrough_errors_total`
- [ ] Audit log: passthrough requests with redacted sensitive headers

### Phase 6: Error Handling & Edge Cases (Priority: MEDIUM)

**Scenarios**:
- Upstream timeouts → 504 Gateway Timeout
- Connection failures → 502 Bad Gateway
- Policy violations (plugin blocks) → 403 Forbidden or 422 Unprocessable Entity
- Tool not found → 404 Not Found
- `expose_passthrough=false` → 403 Forbidden
- Request/response body size limits → 413 Payload Too Large

**Acceptance Criteria**:
- [ ] Structured error responses with `error`, `message`, `details` fields
- [ ] Upstream errors preserve status code when possible
- [ ] Plugin violations return clear error messages
- [ ] Size limits configurable (default: 10MB request, 50MB response)

## Non-Goals (Deferred to Future)

- **OpenAPI generation**: Automatic OpenAPI entries for passthrough routes (defer to v0.8.0)
- **Multi-hop/mashups**: Composing multiple upstream calls (defer to compositor feature)
- **WebSocket upgrades**: Passthrough for WebSocket connections (defer to v0.9.0)
- **Response caching**: Cache upstream responses (use existing cache plugin)
- **Rate limiting**: Per-tool rate limits (use existing rate_limit plugin)

## Testing Requirements

### Unit Tests
- [ ] Router: path resolution, query/header mapping, body forwarding
- [ ] Security: allowlist validation, SSRF protection, URL normalization
- [ ] Plugin integration: pre/post hook execution, chain resolution
- [ ] Error handling: timeout, connection failure, policy violation

### Integration Tests
- [ ] End-to-end: register REST tool → call passthrough endpoint → verify response
- [ ] Plugin chains: verify pre/post plugins execute in correct order
- [ ] Security: verify SSRF protection blocks private IPs
- [ ] Auth: verify JWT bearer token required and scoped correctly

### Performance Tests
- [ ] Latency: passthrough adds <50ms overhead vs. direct upstream call
- [ ] Throughput: handle 1000 req/s with plugin chains enabled
- [ ] Memory: no memory leaks under sustained load

## Documentation Requirements

- [ ] API documentation: `/passthrough/{namespace}/{tool_id}` endpoint
- [ ] Configuration guide: `passthrough` section in `plugins/config.yaml`
- [ ] Security guide: allowlist, SSRF protection, auth requirements
- [ ] Plugin development: creating passthrough-aware plugins
- [ ] Examples: registering REST tool with passthrough enabled

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **SSRF attacks** | Strict allowlist + private IP blocking + URL normalization |
| **Secret leakage** | Header redaction in logs + post-filtering + audit logs |
| **Performance overhead** | Async plugin execution + connection pooling + response streaming |
| **Backwards compatibility** | Default `expose_passthrough=true` for new REST tools only |

## Success Metrics

- [ ] REST tools can be invoked via both `/tools/call` and `/passthrough/{namespace}/{tool_id}`
- [ ] Plugin chains execute successfully for passthrough requests
- [ ] Security guardrails prevent SSRF and unauthorized access
- [ ] Observability spans and metrics provide visibility into passthrough pipeline
- [ ] Documentation and examples enable users to register and use passthrough endpoints

## Related Issues

- Original issue: #[issue_number] (August 15, 2025)
- Plugin framework: Implemented (42+ plugins available)
- Database schema: Completed (all fields added to `Tool` model)

## Notes

- This feature complements existing federation/gateway features and stdio/SSE/WebSocket transports
- Keep scope focused on single-upstream REST calls; multi-hop/mashups handled by future compositor
- Leverage existing plugin framework (42+ plugins) for cross-cutting concerns
- Database schema and Pydantic validation already complete—focus on runtime implementation