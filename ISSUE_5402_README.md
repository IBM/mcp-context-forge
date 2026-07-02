# Issue #5402: Vault Plugin Direct Integration

**Complete Documentation Package for Implementation**

---

## ⚠️ IMPORTANT: Architecture Decision Update

**Date**: 2026-07-02  
**Decision**: Architect approved **stateless approach** - NO `vault_credential_alias` database field

## 📋 Authoritative Design Document

**🎯 START HERE**: **[ISSUE_5402_FINAL_DESIGN.md](./ISSUE_5402_FINAL_DESIGN.md)** ← **CURRENT SPEC**

This is the **ONLY authoritative specification** reflecting the architect's approved design:
- ✅ Stateless (no database storage)
- ✅ `required_domain` computed property
- ✅ Agent sends credential name in each request
- ✅ Users choose their own credential names

---

## ⚠️ Legacy Documents (Outdated)

The following documents describe an **earlier approach** that was **NOT approved**:

| Document | Status | Note |
|----------|--------|------|
| ~~[ISSUE_5402_SUMMARY.md](./ISSUE_5402_SUMMARY.md)~~ | ⚠️ **OUTDATED** | References `vault_credential_alias` field (rejected) |
| ~~[ISSUE_5402_ANALYSIS_AND_PLAN.md](./ISSUE_5402_ANALYSIS_AND_PLAN.md)~~ | ⚠️ **OUTDATED** | Database schema section superseded |
| ~~[ISSUE_5402_ARCHITECTURE.md](./ISSUE_5402_ARCHITECTURE.md)~~ | ⚠️ **OUTDATED** | Shows `vault_credential_alias` in flows |
| ~~[ISSUE_5402_AGENT_CHANGES.md](./ISSUE_5402_AGENT_CHANGES.md)~~ | ⚠️ **OUTDATED** | Agent design superseded |

**DO NOT USE** these for implementation. They are kept for historical reference only.

---

## 📚 Current Document Index

| Document | Purpose | Status | Audience |
|----------|---------|--------|----------|
| **[ISSUE_5402_FINAL_DESIGN.md](./ISSUE_5402_FINAL_DESIGN.md)** | **AUTHORITATIVE SPEC** | ✅ **CURRENT** | **ALL** |
| **[ISSUE_5402_PLUGIN_ARCHITECTURE.md](./ISSUE_5402_PLUGIN_ARCHITECTURE.md)** | Separate plugin approach | ✅ **CURRENT** | Architects, Developers |
| [ISSUE_5402_CHECKLIST.md](./ISSUE_5402_CHECKLIST.md) | Task checklist | ⚠️ Needs update | Implementers |
| [ISSUE_5402_GIT_WORKFLOW.md](./ISSUE_5402_GIT_WORKFLOW.md) | Git workflow | ✅ Still valid | All developers |
| [ISSUE_5402_AGENT_CODE_LOCATIONS.md](./ISSUE_5402_AGENT_CODE_LOCATIONS.md) | Code locations | ⚠️ Needs update | Developers (Agent) |

---

## 🎯 Problem Statement

The vault plugin currently uses a **fragile tag-based credential injection system** that:

- ❌ Requires manual coordination across 3 config points (token keys, gateway tags, auth header tags)
- ❌ Fails silently when tags don't match
- ❌ Forces agent runtime to access vault-proxy in legacy mode (security risk)
- ❌ Doesn't scale as MCP servers increase

**Impact**: Configuration drift, silent failures, support burden, security concerns.

---

## ✨ Approved Solution (Stateless Direct Integration)

**Vault Plugin Direct Integration**: Agent sends credential name in request, plugin extracts domain from gateway URL, resolves credential from vault-proxy on-demand.

### Key Changes (Architect Approved)

1. **Context Forge** (mcp-context-forge):
   - ✅ Add `required_domain` computed property to Gateway (NO database storage)
   - ✅ Implement `VaultProxyClient` for wrap/unwrap operations
   - ✅ Create separate `vault_direct` plugin (leaves legacy plugin untouched)
   - ✅ Extract credential name from `request.tokens[gateway.required_domain]`

2. **Agent Runtime** (agent_langchain_mcp):
   - ✅ Query gateway API to get `required_domain`
   - ✅ Maintain user config: `domain → credential_name` mappings
   - ✅ Send credential name in request: `tokens: {domain: credential_name}`
   - ✅ Pass `vault_token` and `vault_entity_id` to Context Forge

### Benefits

- ✅ **Stateless**: No database storage, no coordination needed
- ✅ **Flexible**: Users choose their own credential names
- ✅ **Security**: Agent no longer needs vault-proxy access
- ✅ **Simple**: Context Forge provides domain, agent sends credential name
- ✅ **Reliability**: Explicit errors, no silent failures

---

## 🏗️ Architecture (Approved Design)

### Before (Tag-Based - Legacy)

```
Agent → Vault-Proxy (resolve ALL credentials upfront)
    ↓
X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_abc"}
    ↓
Context Forge → Match tags → Inject header
    ↓
MCP Server
```

**3 coordination points**: Token key ↔ Gateway tag ↔ Auth header tag

### After (Stateless Direct - NEW)

```
Agent → Get gateway info (includes required_domain: "github.com")
    ↓
Agent → Load user config (github.com → "github-personal")
    ↓
Agent → Context Forge
    Request: {
      vault_token: "...",
      vault_entity_id: "user@example.com",
      tokens: {"github.com": "github-personal"}
    }
    ↓
Vault Plugin → Extract: domain = gateway.required_domain
                        credential_name = request.tokens[domain]
    ↓
Vault-Proxy (resolve ONE credential by name)
    ↓
{secretValue, authType, headerName} → Inject header
    ↓
MCP Server
```

**0 coordination points**: Everything derived from request + URL

---

## 📊 Implementation Phases (Approved Design)

### Context Forge (mcp-context-forge)

| Phase | Component | Effort |
|-------|-----------|--------|
| **Phase 1** | Add `required_domain` property to Gateway | 1-2h |
| **Phase 2** | Vault Client (VaultProxyClient) | 4-6h |
| **Phase 3** | New `vault_direct` plugin | 4-6h |
| **Phase 4** | Plugin routing logic | 2-3h |
| **Phase 5** | Testing | 6-8h |
| **Phase 6** | Documentation | 3-4h |
| **Total** | | **20-29h (2.5-3.5 days)** |

### Agent Runtime (agent_langchain_mcp)

| Phase | Component | Effort |
|-------|-----------|--------|
| **Phase 1** | Feature Flag | 1h |
| **Phase 2** | Vault Utility | 3h |
| **Phase 3** | Router Updates | 4h |
| **Phase 4** | Testing | 6h |
| **Phase 5** | Documentation | 2h |
| **Total** | | **16h (2 days)** |

**Overall Project**: ~6-8 weeks (development + testing + phased rollout)

---

## 🚀 Migration Path

### Week 1-2: Development

- Context Forge: Phases 1-3
- Agent Runtime: Phases 1-2
- Both repos in parallel

### Week 3: Testing + Documentation

- Context Forge: Phases 4-5
- Agent Runtime: Phases 3-4
- Integration testing

### Week 4: Code Review

- PR review and iterations
- Integration testing
- Documentation review

### Week 5: Staging Deployment (Flags OFF)

- Deploy both systems
- Verify backward compatibility
- Run smoke tests

### Week 6: Enable on Staging (Flags ON)

- Update gateway configs
- Enable feature flags
- Full validation

### Week 7-8: Production Rollout

- Phased deployment: 10% → 25% → 50% → 100%
- Monitor at each step
- Roll back if issues

---

## 🔒 Security Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Agent vault access** | ✅ Required | ❌ Not required |
| **Credentials exposed** | All upfront | One per gateway |
| **Attack surface** | Broader | Reduced |
| **Principle of least privilege** | ❌ No | ✅ Yes |

---

## 📝 Configuration Examples (Approved Design)

### Gateway Configuration

**No changes to Gateway schema!** Just computed property:

```json
{
  "id": "gw-123",
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"  ← Computed from URL (automatic)
}
```

### Agent User Configuration

**~/.agent/vault_credentials.yaml**:
```yaml
credentials:
  github.com: github-personal      # User's choice!
  github.ibm.com: github-work       # User's choice!
  gitlab.company.com: my-gitlab     # User's choice!
```

### Agent Request Format

```json
{
  "gateway_id": "gw-123",
  "tool_name": "list-repos",
  "vault_entity_id": "user@example.com",
  "vault_token": "vault_token_abc",
  "tokens": {
    "github.com": "github-personal"  ← From user config
  }
}
```

### Environment Variables

**Context Forge**:
```bash
VAULT_PROXY_URL=http://localhost:8080
VAULT_PROXY_TIMEOUT=5.0

# No feature flags needed!
```

**Agent Runtime**:
```bash
VAULT_DIRECT_MODE_ENABLED=false  # Feature flag (default: OFF)
```

---

## 🧪 Testing Strategy

### Unit Tests

**Context Forge**:
- ✅ Vault client (wrap, unwrap, resolve, errors)
- ✅ Plugin direct mode (all auth types)
- ✅ Plugin legacy mode (backward compatibility)

**Agent Runtime**:
- ✅ Feature flag behavior
- ✅ Direct mode skips vault resolution
- ✅ Passthrough headers added correctly
- ✅ Legacy mode preserved

### Integration Tests

**Both Systems**:
- ✅ End-to-end: gateway creation → tool invocation → vault resolution
- ✅ Error scenarios: credential not found, vault unavailable
- ✅ Mode switching via feature flags

### Manual Testing

- ✅ Direct mode enabled: Test all auth types
- ✅ Legacy mode enabled: Test tag-based matching
- ✅ Error handling: Verify clear error messages
- ✅ Performance: Measure latency impact

---

## 📈 Success Metrics

### Functional Metrics

- ✅ Direct mode resolves credentials for all auth types (PAT, OAuth2, JWT, Custom)
- ✅ Error messages clear when credentials missing
- ✅ Legacy mode continues to work
- ✅ Zero silent failures

### Performance Metrics

- ✅ Vault-proxy latency: <100ms p95
- ✅ Tool invocation latency increase: <50ms p95
- ✅ Agent runtime: No vault-proxy calls

### Operational Metrics

- ✅ Configuration drift incidents: 0
- ✅ Support tickets: -50%
- ✅ Time to add MCP server: -60%
- ✅ Debugging time: -70%

---

## 🔄 Rollback Plan

### Context Forge

1. Set `VAULT_DIRECT_RESOLUTION_ENABLED=false`
2. System reverts to legacy tag-based mode
3. No data loss (dual-mode coexists)

### Agent Runtime

1. Set `VAULT_DIRECT_MODE_ENABLED=false`
2. Agent reverts to local vault resolution
3. Instant rollback (no persistence)

**Safety**: Both systems can rollback independently.

---

## ❓ Open Questions

Before starting implementation, answer these:

1. **Vault metadata format**: Does vault-proxy return `{secretValue, authType, headerName}`?
   - If not, when can this be added?

2. **Header naming**: Approve `X-Vault-Token` and `X-User-Name`?
   - Or use different names?

3. **Error handling**: 401 Unauthorized or 400 Bad Request for missing credentials?

4. **Caching**: Cache vault resolutions per request?
   - Reduces vault-proxy load

5. **Deprecation timeline**: When to remove legacy mode?
   - Recommendation: 6 months (2-3 release cycles)

---

## 📞 Contact & Ownership

| Component | Owner | Repository |
|-----------|-------|------------|
| Context Forge | [Team/Person] | `mcp-context-forge` |
| Agent Runtime | [Team/Person] | `agent_langchain_mcp` |
| Vault-Proxy | [Team/Person] | `ica-vault-proxy` |
| PM/Coordination | [PM/Lead] | All |

---

## 🔗 Related Issues & PRs

- **GitHub Issue**: #5402
- **Context Forge PR**: TBD (create after approval)
- **Agent Runtime PR**: TBD (create after approval)

---

## 📖 Additional Resources

- **Vault Plugin README**: [plugins/vault/README.md](./plugins/vault/README.md)
- **AGENTS.md**: [AGENTS.md](./AGENTS.md)
- **MCP Specification**: [MCP Protocol Docs](https://github.com/modelcontextprotocol/specification)

---

## ✅ Next Steps

### For PM/Lead

1. ✅ Review [ISSUE_5402_SUMMARY.md](./ISSUE_5402_SUMMARY.md)
2. ✅ Answer open questions (see above)
3. ✅ Approve approach and timeline
4. ✅ Assign implementation tasks

### For Developers (Context Forge)

1. ✅ **Read [ISSUE_5402_FINAL_DESIGN.md](./ISSUE_5402_FINAL_DESIGN.md)** ← START HERE
2. ✅ Read [ISSUE_5402_PLUGIN_ARCHITECTURE.md](./ISSUE_5402_PLUGIN_ARCHITECTURE.md) for plugin design
3. ✅ Use [ISSUE_5402_GIT_WORKFLOW.md](./ISSUE_5402_GIT_WORKFLOW.md) for branching

### For Developers (Agent Runtime)

1. ✅ **Read [ISSUE_5402_FINAL_DESIGN.md](./ISSUE_5402_FINAL_DESIGN.md)** ← START HERE
2. ✅ See "Agent Implementation" section for complete details
3. ✅ Use [ISSUE_5402_GIT_WORKFLOW.md](./ISSUE_5402_GIT_WORKFLOW.md) for branching

---

## 📅 Timeline Summary

| Week | Milestone | Status |
|------|-----------|--------|
| **W1-2** | Development (both repos) | 🔵 Not Started |
| **W3** | Testing + Documentation | 🔵 Not Started |
| **W4** | Code Review | 🔵 Not Started |
| **W5** | Staging Deployment (flags OFF) | 🔵 Not Started |
| **W6** | Enable Staging (flags ON) | 🔵 Not Started |
| **W7-8** | Production Rollout | 🔵 Not Started |

**Total Duration**: ~8 weeks

**Effort**: 
- Context Forge: 26-36 hours
- Agent Runtime: 16 hours
- **Total**: 42-52 hours

---

## 🎉 Expected Outcomes

After successful implementation:

1. ✅ **Zero configuration drift incidents**
2. ✅ **50% reduction in support tickets** (credential issues)
3. ✅ **60% faster MCP server onboarding**
4. ✅ **70% faster credential debugging**
5. ✅ **Improved security posture** (agent no longer needs vault access)
6. ✅ **Clear error messages** (no silent failures)
7. ✅ **Single source of truth** (gateway configuration)

---

## 📄 Document Changelog

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-07-01 | 1.0 | Initial documentation package | [Author] |

---

## 🤝 Contributing

For questions or feedback on this implementation plan:

1. Comment on GitHub Issue #5402
2. Contact the project lead
3. Join the implementation sync meetings

---

**Ready to implement? Start with [ISSUE_5402_CHECKLIST.md](./ISSUE_5402_CHECKLIST.md)**
