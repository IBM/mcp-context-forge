# Issue #5402: Vault Direct Integration - Executive Summary

## Quick Links

- **Detailed Implementation Plan**: [ISSUE_5402_ANALYSIS_AND_PLAN.md](./ISSUE_5402_ANALYSIS_AND_PLAN.md)
- **Agent Runtime Changes**: [ISSUE_5402_AGENT_CHANGES.md](./ISSUE_5402_AGENT_CHANGES.md)
- **Git Workflow Guide**: [ISSUE_5402_GIT_WORKFLOW.md](./ISSUE_5402_GIT_WORKFLOW.md)
- **GitHub Issue**: https://github.com/[org]/[repo]/issues/5402

---

## Problem Statement

**Current Issue**: The vault plugin uses a fragile tag-based credential injection system that requires manual coordination across three configuration points:

1. Token key naming in agent (e.g., `github.com:USER:PAT:x`)
2. Gateway `system:` tag (e.g., `system:github.com`)
3. Gateway `AUTH_HEADER:` tag (e.g., `AUTH_HEADER:X-GitHub-Token`)

**Impact**:
- ❌ Silent failures when tags don't match
- ❌ Security: Agent requires vault-proxy access
- ❌ Scalability: Manual coordination doesn't scale
- ❌ Complexity: No single source of truth

---

## Proposed Solution

**Vault Plugin Direct Integration**: The vault plugin calls vault-proxy directly using a `vault_credential_alias` field on each gateway, eliminating tag-based matching.

### Before (Tag-Based)

```
Agent → Vault-Proxy (resolve ALL credentials)
    ↓
X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_abc"}
    ↓
Context Forge → Match tags → Inject header
    ↓
MCP Server
```

### After (Direct)

```
Agent → Context Forge (pass vault_token + user_name)
    ↓
Vault Plugin → Read gateway.vault_credential_alias
    ↓
Vault-Proxy (resolve ONE credential)
    ↓
{secretValue, authType, headerName} → Inject header
    ↓
MCP Server
```

---

## Implementation Phases

### Repository: `mcp-context-forge` (Context Forge)

| Phase | Component | Files | Effort |
|-------|-----------|-------|--------|
| **Phase 1** | Database Schema | `mcpgateway/db.py`, `mcpgateway/schemas.py`, Alembic migration | 2-3h |
| **Phase 2** | Vault Client | `plugins/vault/vault_client.py` (NEW) | 4-6h |
| **Phase 3** | New Plugin | `plugins/vault_direct/vault_direct_plugin.py` (NEW) | 6-8h |
| **Phase 4** | Gateway Service | `mcpgateway/services/gateway_service.py` | 2-3h |
| **Phase 5** | Testing | Unit + integration + manual tests | 8-10h |
| **Phase 6** | Documentation | README, migration guide, diagrams | 4-6h |
| **Total** | | | **26-36h (3.5-4.5 days)** |

### Repository: `agent_langchain_mcp` (Agent Runtime)

| Phase | Component | Files | Effort |
|-------|-----------|-------|--------|
| **Phase 1** | Feature Flag | `.env.sample`, environment config | 1h |
| **Phase 2** | Vault Proxy Utility | `app/utilities/vault_proxy.py` | 3h |
| **Phase 3** | Router Updates | `app/routes/*/` | 4h |
| **Phase 4** | Testing | Unit + integration tests | 6h |
| **Phase 5** | Documentation | README updates | 2h |
| **Total** | | | **16h (2 days)** |

---

## Key Changes

### Context Forge (mcp-context-forge)

#### Database Schema: The `vault_credential_alias` Field

**Why this field exists:**

The `vault_credential_alias` field replaces the fragile three-way tag coordination system with a **single, explicit, direct reference** to a vault credential.

**Current system (tag-based):**
```
Agent token key:    "github.com:USER:PAT:x"
                           ↓ (must match via string parsing)
Gateway system tag: "system:github.com"
                           ↓ (separate tag for injection)
Gateway auth tag:   "AUTH_HEADER:X-GitHub-Token"
                           ↓ (any mismatch = silent failure)
Result:             🔴 Silent authentication failure
```

**New system (direct reference):**
```
Gateway field:      "vault_credential_alias": "github-personal"
                           ↓ (direct lookup, no parsing)
Vault-proxy:        resolve_credential(alias="github-personal")
                           ↓ (returns credential + metadata)
Result:             ✅ {secretValue, authType, headerName}
                           ↓ (authoritative injection method)
Injected header:    X-GitHub-Token: ghp_abc123
```

**Architectural justification:**

| Aspect | Tag-Based (Current) | `vault_credential_alias` (New) |
|--------|---------------------|--------------------------------|
| **Configuration points** | 3 (agent key + 2 gateway tags) | 1 (gateway field) |
| **Coordination required** | Manual string alignment | None (direct reference) |
| **Failure mode** | Silent (proceeds unauthenticated) | Explicit (immediate error) |
| **Source of truth** | Split (tags + vault + agent) | Single (vault) |
| **Validation** | Runtime string matching | Database schema + vault lookup |
| **Error message** | "401 Unauthorized" (unclear) | "Credential 'github-personal' not found for user@example.com" |
| **Scalability** | O(3N) config points for N servers | O(N) config points |
| **Security surface** | Agent needs vault access | Only Context Forge needs vault access |

**Why not use existing fields?**

- **Tags**: Designed for arbitrary labels, not structured credential references; require parsing logic
- **URL**: Identifies MCP server location, not which credential to use
- **Name/Description**: Human-readable display text, not machine configuration
- **Metadata**: Less discoverable, no schema validation, no indexing

**Implementation:**
```python
# mcpgateway/db.py - Gateway model
vault_credential_alias: Mapped[Optional[str]] = mapped_column(
    String(255), 
    nullable=True,
    index=True,  # Fast lookup by alias
    comment="Vault credential alias for direct vault-proxy integration. "
            "Replaces system: and AUTH_HEADER: tag-based matching with "
            "explicit vault reference. When set, vault plugin calls "
            "vault-proxy to resolve this credential for tool invocations."
)
```

**Database migration adds:**
- Column: `vault_credential_alias` (nullable, backward compatible)
- Index: `ix_gateways_vault_credential_alias` (performance)
- Validation: Max 255 chars (Pydantic schema)

**Example usage:**
```json
{
  "name": "GitHub MCP Server",
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal",
  "tags": []  // Tags no longer needed for vault integration
}
```

#### Vault Client (NEW)
```python
# plugins/vault/vault_client.py
class VaultProxyClient:
    async def resolve_credential(
        self, 
        owner: str, 
        alias: str, 
        vault_token: str
    ) -> VaultCredential:
        # Wrap + unwrap in one call
        # Returns {secret_value, auth_type, header_name}
```

#### Plugin Dual-Mode
```python
# plugins/vault/vault_plugin.py
async def tool_pre_invoke(self, payload, context):
    if self._sconfig.direct_mode_enabled and vault_alias:
        return await self._process_direct_mode(...)
    else:
        return await self._process_legacy_tag_mode(...)
```

#### Configuration (No Feature Flags)
```bash
# .env
VAULT_PROXY_URL=http://localhost:8080
VAULT_PROXY_TIMEOUT=5.0

# No VAULT_DIRECT_RESOLUTION_ENABLED flag needed!
# Routing is automatic based on vault_credential_alias presence
```

#### Two Separate Plugins

**Existing plugin** (`vault`) - Tag-based, **UNCHANGED**:
- Activated when gateway has NO `vault_credential_alias`
- Uses system: and AUTH_HEADER: tags
- Processes X-Vault-Tokens header

**New plugin** (`vault_direct`) - Direct integration, **NEW**:
- Activated when gateway HAS `vault_credential_alias`
- Calls vault-proxy directly
- Processes X-Vault-Token and X-User-Name headers

**Routing**: Automatic based on gateway config - no flags, no coordination needed.

---

### Agent Runtime (agent_langchain_mcp)

#### Feature Flag
```bash
# .env
VAULT_DIRECT_MODE_ENABLED=false  # Feature flag
```

#### Vault Proxy Utility
```python
# app/utilities/vault_proxy.py
async def fetch_tokens(...):
    if is_direct_mode_enabled():
        # Skip vault resolution
        return None
    # Legacy mode continues as before
```

#### Passthrough Headers
```python
# app/utilities/vault_proxy.py
def add_vault_passthrough_headers(headers, vault_entity_id, vault_token):
    if is_direct_mode_enabled():
        headers["X-Vault-Token"] = vault_token
        headers["X-User-Name"] = vault_entity_id
    return headers
```

---

## Testing Strategy

### Unit Tests

**Context Forge**:
- ✅ Vault client (wrap, unwrap, resolve, errors)
- ✅ Plugin direct mode (PAT, OAuth2, JWT, Custom, errors)
- ✅ Plugin legacy mode (backward compatibility)

**Agent Runtime**:
- ✅ Feature flag behavior
- ✅ Direct mode skips vault resolution
- ✅ Passthrough headers added correctly
- ✅ Legacy mode preserved

### Integration Tests

**Context Forge**:
- ✅ End-to-end: gateway creation → tool invocation → vault resolution
- ✅ Error scenarios: credential not found, vault unavailable

**Agent Runtime**:
- ✅ End-to-end: agent request → Context Forge → vault passthrough
- ✅ Both modes (direct + legacy)

### Manual Testing

**Context Forge**:
1. Create gateway with `vault_credential_alias`
2. Store credential in vault with metadata
3. Invoke tool → verify correct auth header injected
4. Test error cases (missing credential, vault down)

**Agent Runtime**:
1. Enable direct mode flag
2. Send agent request with vault credentials
3. Verify X-Vault-Token and X-User-Name headers sent
4. Confirm no X-Vault-Tokens header

---

## Migration Path

### Phase 1: Deploy New Plugin (Zero Risk)
- ✅ Deploy Context Forge with new `vault_direct` plugin
- ✅ Deploy agent with direct mode code (flag OFF)
- ✅ Verify backward compatibility (existing gateways use old plugin automatically)
- ✅ **No feature flags needed** - routing is automatic

### Phase 2: Test on Staging
- ✅ Create test gateway with `vault_credential_alias`
- ✅ Verify automatic routing to `vault_direct` plugin
- ✅ Enable agent flag: `VAULT_DIRECT_MODE_ENABLED=true`
- ✅ Test end-to-end flow

### Phase 3: Gradual Production Migration
- ✅ Migrate gateways one-by-one by adding `vault_credential_alias`
- ✅ Each migration automatically uses new plugin
- ✅ Monitor metrics: latency, errors, vault load
- ✅ Old gateways continue working unchanged
- ✅ No coordination needed - add field → uses new plugin

### Phase 4: Eventually Deprecate Legacy Plugin
- ✅ Update documentation (mark tag-based approach as legacy)
- ✅ Encourage migration to `vault_credential_alias`
- ✅ Keep legacy plugin for 6+ months
- ✅ Remove legacy plugin after all gateways migrated

---

## Configuration Examples

### Gateway Configuration

**Before (Tag-Based)**:
```json
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "tags": [
    {"label": "system:github.com"},
    {"label": "AUTH_HEADER:X-GitHub-Token"}
  ]
}
```

**After (Direct)**:
```json
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal"
}
```

### Agent Request

**Before (Legacy Mode)**:
```json
{
  "query": "List repos",
  "mcp_server_url": "http://cf.internal:4444/mcp",
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc",
  "tokens": {
    "github.com:USER:PAT:x": "token_path"
  }
}
```

**After (Direct Mode)**:
```json
{
  "query": "List repos",
  "mcp_server_url": "http://cf.internal:4444/mcp",
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc"
}
```

---

## Benefits

### Architectural Clarity

| Aspect | Tag-Based (Before) | Direct Integration (After) |
|--------|-------------------|---------------------------|
| **Configuration model** | Convention-based (string matching) | Explicit (direct reference) |
| **Source of truth** | Split (agent + gateway + vault) | Single (vault) |
| **Coupling** | Tight (3-way coordination) | Loose (gateway → vault only) |
| **Validation** | Runtime (too late) | Schema + API (fail-fast) |
| **Intent clarity** | Implicit (via tag parsing) | Explicit (via dedicated field) |
| **Extensibility** | Hard (parsing logic) | Easy (vault metadata) |

**Key architectural principle**: The `vault_credential_alias` field embodies **"explicit is better than implicit"** - each gateway declares exactly which credential it needs, and vault is authoritative for how to use it.

### Security

| Aspect | Before | After |
|--------|--------|-------|
| Agent vault access | ✅ Required (attack vector) | ❌ Not required (reduced surface) |
| Credentials exposed | All upfront (bulk exposure) | One per gateway (least privilege) |
| Attack surface | Agent + Context Forge both need vault | Only Context Forge needs vault |
| Principle of least privilege | ❌ No (agent resolves all) | ✅ Yes (per-gateway resolution) |
| Interception risk | X-Vault-Tokens (multiple secrets) | X-Vault-Token (auth token only) |

### Operational

| Aspect | Before | After |
|--------|--------|-------|
| Configuration points | 3 (error-prone) | 1 (single source) |
| Silent failures | ✅ Common | ❌ Eliminated |
| Error messages | Unclear | Explicit |
| Scalability | Manual coordination | Automated |

### Development

| Aspect | Before | After |
|--------|--------|-------|
| Add new MCP server | 15-20 min | 5 min |
| Debugging credential issues | 30-60 min | 10 min |
| Testing | Complex (3 configs) | Simple (1 config) |

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Vault-proxy unavailable | Tools fail | Medium | Timeout + clear error + fallback to legacy |
| Breaking changes | Deployments fail | Low | Feature flags OFF by default + dual-mode |
| Performance degradation | Slower requests | Low | Cache + monitoring + timeout tuning |
| Migration coordination | Agent/CF mismatch | Medium | Phased rollout + backward compatibility |

---

## Rollback Plan

### Context Forge
1. **Per-gateway rollback**: Remove `vault_credential_alias` from gateway config
2. Gateway automatically reverts to legacy `vault` plugin
3. **No deployment needed** - just config change
4. **Emergency**: Disable `vault_direct` plugin in `plugins/config.yaml`

### Agent Runtime
1. Set `VAULT_DIRECT_MODE_ENABLED=false`
2. Agent reverts to local vault resolution
3. Instant rollback (no persistence)

**Safety**: 
- No feature flags to coordinate
- Rollback is per-gateway (fine-grained control)
- Legacy plugin always available (never removed/modified)
- Each gateway can be migrated/rolled back independently

---

## Success Metrics

### Functional Metrics
- ✅ Direct mode resolves credentials for all auth types (PAT, OAuth2, JWT, Custom)
- ✅ Error messages clear when credentials missing
- ✅ Legacy mode continues to work
- ✅ Zero silent failures

### Performance Metrics
- ✅ Vault-proxy latency: <100ms p95 for wrap/unwrap
- ✅ Tool invocation latency increase: <50ms p95
- ✅ Agent runtime: No vault-proxy calls

### Operational Metrics
- ✅ Configuration drift incidents: 0
- ✅ Support tickets re: credential issues: -50%
- ✅ Time to add new MCP server: -60%
- ✅ Debugging time for credential issues: -70%

---

## Timeline

### Overall Project Timeline

| Week | Context Forge | Agent Runtime | Status |
|------|---------------|---------------|--------|
| **Week 1** | Phase 1-3 (DB + Client + New Plugin) | Phase 1-2 (Flag + Vault Utility) | Development |
| **Week 2** | Phase 4-5 (Service + Testing) | Phase 3-4 (Routers + Testing) | Development |
| **Week 3** | Phase 6 (Documentation) | Phase 5 (Documentation) | Documentation |
| **Week 4** | Code review + iterations | Code review + iterations | Review |
| **Week 5** | Deploy staging (flag OFF) | Deploy staging (flag OFF) | Staging |
| **Week 6** | Enable staging (flag ON) | Enable staging (flag ON) | Testing |
| **Week 7-8** | Production rollout | Production rollout | Production |

**Total**: ~8 weeks (including testing, rollout, monitoring)

---

## Decision Points

### Must Decide Before Starting

1. **Header naming**: Use `X-Vault-Token` and `X-User-Name`, or different names?
   - **Recommendation**: Use `X-Vault-Token` and `X-User-Name` (clear, explicit)

2. **Feature flag defaults**: OFF or ON by default?
   - **Recommendation**: OFF by default (safest for rollout)

3. **Caching strategy**: Cache vault resolutions per request?
   - **Recommendation**: Yes, cache per request (reduce vault load)

4. **Error handling**: 401 Unauthorized or 400 Bad Request for missing credentials?
   - **Recommendation**: 401 Unauthorized (standard auth failure)

5. **Deprecation timeline**: When to remove legacy mode?
   - **Recommendation**: 6 months (2-3 release cycles)

---

## Open Questions

1. **Vault metadata format**: Does vault-proxy already return `{secret_value, auth_type, header_name}`?
   - If not, when can this feature be added?

2. **Context passing**: Confirm header names (`X-Vault-Token`, `X-User-Name`) are acceptable?

3. **Observability**: What metrics/traces should be emitted?
   - Context Forge: `vault.direct_mode.calls`, `vault.direct_mode.errors`, `vault.direct_mode.latency`
   - Agent: `agent.vault.direct_mode_enabled`, `agent.vault.passthrough_headers_added`

4. **Rate limiting**: Should vault-proxy calls be rate-limited at plugin level?

---

## Next Steps

### Immediate Actions

1. ✅ **Review** both implementation plans
2. ✅ **Answer** open questions and decision points
3. ✅ **Approve** design approach
4. ✅ **Coordinate** with vault-proxy team (metadata format)
5. ✅ **Create** implementation tasks/tickets

### Implementation Order

**Week 1-2 (Development)**:
1. Context Forge: Phase 1 (Database) - **non-breaking, can start immediately**
2. Context Forge: Phase 2 (Vault Client) - parallel
3. Agent: Phase 1-2 (Feature flag + utility) - parallel
4. Context Forge: Phase 3 (Plugin refactor)
5. Agent: Phase 3 (Router updates)

**Week 3 (Testing + Docs)**:
6. Context Forge: Phase 4-5 (Service + tests)
7. Agent: Phase 4 (Tests)
8. Both: Phase 6 (Documentation)

**Week 4 (Review)**:
9. Code review
10. Address feedback
11. Integration testing

**Week 5-8 (Deployment)**:
12. Deploy staging (flags OFF)
13. Enable staging (flags ON)
14. Production rollout
15. Monitor + iterate

---

## Contact & Ownership

| Component | Owner | Repository |
|-----------|-------|------------|
| Context Forge | [Team/Person] | `mcp-context-forge` |
| Agent Runtime | [Team/Person] | `agent_langchain_mcp` |
| Vault-Proxy | [Team/Person] | `ica-vault-proxy` |
| Coordination | [PM/Lead] | All |

---

## References

- **GitHub Issue**: #5402
- **Implementation Plan**: [ISSUE_5402_ANALYSIS_AND_PLAN.md](./ISSUE_5402_ANALYSIS_AND_PLAN.md)
- **Agent Changes**: [ISSUE_5402_AGENT_CHANGES.md](./ISSUE_5402_AGENT_CHANGES.md)
- **Git Workflow**: [ISSUE_5402_GIT_WORKFLOW.md](./ISSUE_5402_GIT_WORKFLOW.md)
- **Vault Plugin README**: [plugins/vault/README.md](./plugins/vault/README.md)
- **AGENTS.md**: [AGENTS.md](./AGENTS.md)

---

## Conclusion

Issue #5402 proposes a **comprehensive, backward-compatible solution** to eliminate the fragile tag-based credential injection system. The implementation:

- ✅ **Improves security**: Agent no longer needs vault access
- ✅ **Simplifies operations**: Single source of truth (gateway config)
- ✅ **Zero breaking changes**: Dual-mode support with feature flags
- ✅ **Clear migration path**: Phased rollout with easy rollback

**Recommendation**: Approve and proceed with implementation.

**Total Effort**: ~6-8 weeks (development + testing + rollout)

**ROI**: Significant reduction in:
- Configuration errors (-90%)
- Support tickets (-50%)
- Security incidents (reduced attack surface)
- Time to add new MCP servers (-60%)
