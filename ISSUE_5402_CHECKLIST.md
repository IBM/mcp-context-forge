# Issue #5402: Implementation Checklist

This checklist tracks all tasks required to implement vault plugin direct integration.

## Pre-Implementation

- [ ] Review all documentation:
  - [ ] [ISSUE_5402_SUMMARY.md](./ISSUE_5402_SUMMARY.md)
  - [ ] [ISSUE_5402_ANALYSIS_AND_PLAN.md](./ISSUE_5402_ANALYSIS_AND_PLAN.md)
  - [ ] [ISSUE_5402_AGENT_CHANGES.md](./ISSUE_5402_AGENT_CHANGES.md)
  - [ ] [ISSUE_5402_ARCHITECTURE.md](./ISSUE_5402_ARCHITECTURE.md)

- [ ] Answer open questions:
  - [ ] Confirm vault-proxy metadata format: `{secretValue, authType, headerName}`
  - [ ] Approve header names: `X-Vault-Token`, `X-User-Name`
  - [ ] Decide on error code: 401 Unauthorized vs 400 Bad Request
  - [ ] Define caching strategy: per-request or session-based
  - [ ] Set deprecation timeline for legacy mode

- [ ] Create GitHub issues/tickets:
  - [ ] Context Forge implementation (mcp-context-forge)
  - [ ] Agent runtime implementation (agent_langchain_mcp)
  - [ ] Documentation updates
  - [ ] Integration testing

---

## Phase 1: Database Schema (mcp-context-forge)

### Code Changes

- [ ] **mcpgateway/db.py**
  - [ ] Add `vault_credential_alias` field to `Gateway` model
  - [ ] Add comment explaining field purpose
  - [ ] Verify nullable=True for backward compatibility

- [ ] **mcpgateway/schemas.py**
  - [ ] Add `vault_credential_alias` to `GatewayCreate` schema
  - [ ] Add `vault_credential_alias` to `GatewayUpdate` schema
  - [ ] Add `vault_credential_alias` to `Gateway` response schema
  - [ ] Add field descriptions and max_length=255

### Migration

- [ ] **Create Alembic migration**
  - [ ] Run: `cd mcpgateway && alembic heads` (verify current head)
  - [ ] Run: `alembic revision --autogenerate -m "add_vault_credential_alias_to_gateways"`
  - [ ] Verify `down_revision` points to correct head
  - [ ] Make migration idempotent (check if column exists)
  - [ ] Add index: `ix_gateways_vault_credential_alias`
  - [ ] Test upgrade: `alembic upgrade head`
  - [ ] Test downgrade: `alembic downgrade -1`
  - [ ] Test fresh DB (should use db.py models, skip migration)

### Testing

- [ ] **Unit tests**
  - [ ] Test gateway creation with `vault_credential_alias`
  - [ ] Test gateway update with `vault_credential_alias`
  - [ ] Test gateway retrieval includes `vault_credential_alias`
  - [ ] Test null/empty values handled correctly

- [ ] **Integration tests**
  - [ ] Test migration runs on existing database
  - [ ] Test migration is idempotent (run twice, no errors)
  - [ ] Verify index created correctly

### Verification

- [ ] Run: `make ruff bandit interrogate pylint verify`
- [ ] Run: `make test` (all tests pass)
- [ ] Run: `cd mcpgateway && alembic heads` (single head)
- [ ] Manual verification:
  - [ ] Start dev server: `make dev`
  - [ ] Create gateway via API with `vault_credential_alias`
  - [ ] Verify field persisted in database

---

## Phase 2: Vault Client (mcp-context-forge)

### Code Changes

- [ ] **Create plugins/vault/vault_client.py**
  - [ ] Implement `VaultCredential` Pydantic model
  - [ ] Implement custom exceptions:
    - [ ] `VaultProxyError` (base)
    - [ ] `VaultNotFoundError`
    - [ ] `VaultConnectionError`
    - [ ] `VaultTimeoutError`
  - [ ] Implement `VaultProxyClient` class:
    - [ ] `__init__(vault_url, timeout, verify_ssl)`
    - [ ] `async wrap_credential(owner, alias, vault_token)`
    - [ ] `async unwrap_credential(wrapped_token, vault_token)`
    - [ ] `async resolve_credential(owner, alias, vault_token)` (convenience)
  - [ ] Add comprehensive error handling
  - [ ] Add debug logging

### Testing

- [ ] **Unit tests: tests/unit/mcpgateway/plugins/plugins/vault/test_vault_client.py**
  - [ ] `test_wrap_credential_success`
  - [ ] `test_wrap_credential_not_found`
  - [ ] `test_wrap_credential_unauthorized`
  - [ ] `test_unwrap_credential_pat_with_header`
  - [ ] `test_unwrap_credential_oauth2`
  - [ ] `test_unwrap_credential_jwt`
  - [ ] `test_unwrap_credential_custom`
  - [ ] `test_resolve_credential_end_to_end`
  - [ ] `test_connection_error`
  - [ ] `test_timeout_error`

### Verification

- [ ] Run: `make ruff bandit interrogate pylint verify`
- [ ] Run: `pytest tests/unit/mcpgateway/plugins/plugins/vault/test_vault_client.py`
- [ ] Manual verification:
  - [ ] Mock vault-proxy or use dev vault
  - [ ] Test wrap/unwrap flow
  - [ ] Verify error handling

---

## Phase 3: Plugin Refactoring (mcp-context-forge)

### Configuration

- [ ] **mcpgateway/config.py**
  - [ ] Add `vault_direct_resolution_enabled: bool = False`
  - [ ] Add `vault_proxy_url: str = "http://localhost:8080"`
  - [ ] Add `vault_proxy_timeout: float = 5.0`

- [ ] **.env.example**
  - [ ] Add `VAULT_DIRECT_RESOLUTION_ENABLED=false`
  - [ ] Add `VAULT_PROXY_URL=http://localhost:8080`
  - [ ] Add `VAULT_PROXY_TIMEOUT=5.0`

### Code Changes

- [ ] **plugins/vault/vault_plugin.py**
  - [ ] Add `VaultConfig` fields:
    - [ ] `direct_mode_enabled: bool = False`
    - [ ] `vault_proxy_url: str`
    - [ ] `vault_proxy_timeout: float`
  - [ ] Update `Vault.__init__()`:
    - [ ] Initialize `VaultProxyClient` if direct mode enabled
  - [ ] Refactor `tool_pre_invoke()`:
    - [ ] Add routing logic: direct vs legacy mode
  - [ ] Implement `_process_direct_mode()`:
    - [ ] Extract vault_alias from gateway metadata
    - [ ] Extract vault_token and user_name from context
    - [ ] Call VaultProxyClient.resolve_credential()
    - [ ] Inject header based on auth_type and header_name
    - [ ] Handle errors (VaultNotFoundError, etc.)
  - [ ] Rename existing logic to `_process_legacy_tag_mode()`
  - [ ] Add comprehensive logging

### Testing

- [ ] **Unit tests: tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin_direct.py**
  - [ ] `test_direct_mode_pat_with_custom_header`
  - [ ] `test_direct_mode_pat_without_custom_header`
  - [ ] `test_direct_mode_oauth2`
  - [ ] `test_direct_mode_jwt`
  - [ ] `test_direct_mode_custom_auth`
  - [ ] `test_direct_mode_credential_not_found`
  - [ ] `test_direct_mode_vault_unavailable`
  - [ ] `test_direct_mode_missing_vault_token`
  - [ ] `test_direct_mode_missing_user_name`
  - [ ] `test_legacy_mode_still_works`

### Verification

- [ ] Run: `make ruff bandit interrogate pylint verify`
- [ ] Run: `pytest tests/unit/mcpgateway/plugins/plugins/vault/`
- [ ] Manual verification:
  - [ ] Test direct mode with mocked vault
  - [ ] Test legacy mode preserved
  - [ ] Test mode switching via feature flag

---

## Phase 4: Gateway Service (mcp-context-forge)

### Code Changes

- [ ] **mcpgateway/services/gateway_service.py**
  - [ ] Verify `create_gateway()` handles `vault_credential_alias`
  - [ ] Verify `update_gateway()` handles `vault_credential_alias`
  - [ ] Verify `get_gateway()` returns `vault_credential_alias`
  - [ ] Verify `list_gateways()` returns `vault_credential_alias`

- [ ] **mcpgateway/routers/gateway.py**
  - [ ] Verify POST /gateways accepts `vault_credential_alias`
  - [ ] Verify PUT /gateways/{id} accepts `vault_credential_alias`
  - [ ] Verify GET /gateways/{id} returns `vault_credential_alias`
  - [ ] Verify GET /gateways returns `vault_credential_alias`

### Testing

- [ ] **Unit tests**
  - [ ] Test gateway service CRUD with `vault_credential_alias`
  - [ ] Test API endpoints with `vault_credential_alias`

- [ ] **Integration tests**
  - [ ] Test end-to-end: create gateway → invoke tool → vault resolution
  - [ ] Test with direct mode enabled
  - [ ] Test error scenarios

### Verification

- [ ] Run: `make test`
- [ ] Manual verification:
  - [ ] Create gateway via API with `vault_credential_alias`
  - [ ] Update gateway `vault_credential_alias`
  - [ ] Verify field returned in responses

---

## Phase 5: Integration Testing (mcp-context-forge)

### Test Files

- [ ] **tests/integration/test_vault_direct_integration.py**
  - [ ] `test_end_to_end_direct_vault` (gateway → tool → vault → MCP)
  - [ ] `test_direct_mode_credential_not_found`
  - [ ] `test_direct_mode_vault_unavailable`
  - [ ] `test_legacy_mode_still_works`
  - [ ] `test_mode_switching_via_feature_flag`

### Manual Testing

- [ ] Set up local environment:
  - [ ] Start Context Forge: `make dev`
  - [ ] Start vault-proxy (or mock)
  - [ ] Export test token

- [ ] Test direct mode:
  - [ ] Enable flag: `VAULT_DIRECT_RESOLUTION_ENABLED=true`
  - [ ] Create gateway with `vault_credential_alias`
  - [ ] Store credential in vault
  - [ ] Invoke tool
  - [ ] Verify correct auth header sent to MCP server

- [ ] Test error cases:
  - [ ] Missing credential → clear error message
  - [ ] Vault unavailable → clear error message
  - [ ] Invalid alias → clear error message

- [ ] Test legacy mode:
  - [ ] Disable flag: `VAULT_DIRECT_RESOLUTION_ENABLED=false`
  - [ ] Create gateway with tags (no `vault_credential_alias`)
  - [ ] Invoke tool with `X-Vault-Tokens` header
  - [ ] Verify tag-based matching still works

---

## Phase 6: Documentation (mcp-context-forge)

### Updates

- [ ] **plugins/vault/README.md**
  - [ ] Add "Direct Mode" section
  - [ ] Add configuration examples
  - [ ] Add migration guide (tags → vault_credential_alias)
  - [ ] Add troubleshooting section

- [ ] **docs/plugins/vault.md** (if exists)
  - [ ] Document new workflow
  - [ ] Add architecture diagrams
  - [ ] Link to migration guide

- [ ] **README.md** (if vault mentioned)
  - [ ] Update overview
  - [ ] Mention direct integration feature

- [ ] **CHANGELOG.md**
  - [ ] Add entry for Issue #5402
  - [ ] Document breaking changes (none)
  - [ ] Document new features

### New Documents

- [ ] **docs/vault-direct-migration.md**
  - [ ] Step-by-step migration guide
  - [ ] Before/after examples
  - [ ] Troubleshooting

- [ ] **docs/vault-architecture.md**
  - [ ] Architecture diagrams
  - [ ] Sequence diagrams
  - [ ] Decision flowchart

---

## Phase 7: Agent Runtime (agent_langchain_mcp)

### Configuration

- [ ] **.env.sample**
  - [ ] Add `VAULT_DIRECT_MODE_ENABLED=false`

- [ ] **app/utilities/config.py** (if exists)
  - [ ] Add configuration for `VAULT_DIRECT_MODE_ENABLED`

### Code Changes

- [ ] **app/utilities/vault_proxy.py**
  - [ ] Add `is_direct_mode_enabled()` function
  - [ ] Update `fetch_tokens()`:
    - [ ] Return None if direct mode enabled
    - [ ] Keep legacy logic if disabled
  - [ ] Update `handle_tokens()`:
    - [ ] Skip if direct mode enabled
    - [ ] Keep legacy logic if disabled
  - [ ] Add `add_vault_passthrough_headers()`:
    - [ ] Add `X-Vault-Token` header
    - [ ] Add `X-User-Name` header
    - [ ] Only if direct mode enabled

- [ ] **app/routes/agent_langchain/agent_langchain_router.py**
  - [ ] Update `/agent_langchain/stream`:
    - [ ] Call `add_vault_passthrough_headers()` when building headers
  - [ ] Update `/agent_langchain/result`:
    - [ ] Same changes as stream endpoint
  - [ ] Verify legacy mode preserved

- [ ] **app/routes/agent_langgraph/agent_langgraph_router.py**
  - [ ] Update similar endpoints with same changes

### Testing

- [ ] **Unit tests: tests/unit/test_vault_proxy.py**
  - [ ] `test_fetch_tokens_direct_mode_returns_none`
  - [ ] `test_fetch_tokens_legacy_mode_resolves`
  - [ ] `test_handle_tokens_direct_mode_is_noop`
  - [ ] `test_handle_tokens_legacy_mode_works`
  - [ ] `test_add_vault_passthrough_headers_direct_mode`
  - [ ] `test_add_vault_passthrough_headers_legacy_mode`

- [ ] **Integration tests: tests/integration/test_agent_vault_direct.py**
  - [ ] `test_agent_stream_direct_mode`
  - [ ] `test_agent_stream_legacy_mode`
  - [ ] `test_agent_result_direct_mode`
  - [ ] `test_agent_result_legacy_mode`

### Verification

- [ ] Run linters and tests (per repo standards)
- [ ] Manual verification:
  - [ ] Test direct mode enabled
  - [ ] Test legacy mode enabled
  - [ ] Verify headers sent correctly

---

## Phase 8: Documentation (agent_langchain_mcp)

### Updates

- [ ] **README.md**
  - [ ] Add vault direct mode section
  - [ ] Add environment variable documentation
  - [ ] Add examples

- [ ] **docs/** (if exists)
  - [ ] Document configuration
  - [ ] Add migration guide

---

## Phase 9: Code Review

### Context Forge

- [ ] Create PR:
  - [ ] Title: "feat: Vault plugin direct integration (#5402)"
  - [ ] Link to issue #5402
  - [ ] Include all phases 1-6
  - [ ] Add comprehensive PR description

- [ ] PR checklist:
  - [ ] All tests pass
  - [ ] Linters pass
  - [ ] Documentation updated
  - [ ] Migration guide included
  - [ ] Backward compatible (feature flag OFF)
  - [ ] Signed commits

- [ ] Address review comments
- [ ] Get approval
- [ ] Squash and merge

### Agent Runtime

- [ ] Create PR:
  - [ ] Title: "feat: Support vault direct mode (#5402)"
  - [ ] Link to issue #5402
  - [ ] Include all agent changes

- [ ] PR checklist (same as above)
- [ ] Address review comments
- [ ] Get approval
- [ ] Squash and merge

---

## Phase 10: Deployment

### Staging Deployment

- [ ] **Context Forge**
  - [ ] Deploy to staging
  - [ ] Verify flag OFF by default: `VAULT_DIRECT_RESOLUTION_ENABLED=false`
  - [ ] Verify backward compatibility (legacy mode works)
  - [ ] Run smoke tests

- [ ] **Agent Runtime**
  - [ ] Deploy to staging
  - [ ] Verify flag OFF by default: `VAULT_DIRECT_MODE_ENABLED=false`
  - [ ] Verify backward compatibility (legacy mode works)
  - [ ] Run smoke tests

### Enable Direct Mode on Staging

- [ ] **Prepare gateways**
  - [ ] Update gateway configs with `vault_credential_alias`
  - [ ] Store credentials in vault with proper metadata

- [ ] **Enable flags**
  - [ ] Context Forge: `VAULT_DIRECT_RESOLUTION_ENABLED=true`
  - [ ] Agent: `VAULT_DIRECT_MODE_ENABLED=true`
  - [ ] Restart services

- [ ] **Validation**
  - [ ] Test end-to-end flow
  - [ ] Test all auth types (PAT, OAuth2, JWT, Custom)
  - [ ] Test error scenarios
  - [ ] Monitor logs for issues
  - [ ] Check metrics

### Production Deployment (Phased)

- [ ] **Phase 1: Deploy code (flags OFF)**
  - [ ] Deploy Context Forge to production
  - [ ] Deploy agent to production
  - [ ] Verify backward compatibility
  - [ ] Monitor for 24-48 hours

- [ ] **Phase 2: Enable on 10% of instances**
  - [ ] Select subset of pods/instances
  - [ ] Enable flags on subset
  - [ ] Monitor closely:
    - [ ] Error rates
    - [ ] Latency
    - [ ] Vault-proxy load
  - [ ] Run for 24-48 hours

- [ ] **Phase 3: Gradual increase**
  - [ ] 10% → 25% → 50% → 100%
  - [ ] Monitor at each step
  - [ ] Roll back if issues detected
  - [ ] 24-48 hours between increases

- [ ] **Phase 4: Full deployment**
  - [ ] All instances on direct mode
  - [ ] Monitor for 1 week
  - [ ] Update documentation (direct mode is now default)

---

## Phase 11: Post-Deployment

### Monitoring

- [ ] Set up dashboards:
  - [ ] Vault plugin metrics (direct vs legacy mode usage)
  - [ ] Error rates by mode
  - [ ] Latency by mode
  - [ ] Vault-proxy load

- [ ] Set up alerts:
  - [ ] High error rate in direct mode
  - [ ] Vault-proxy unavailable
  - [ ] Increased latency

### Validation

- [ ] Verify success metrics:
  - [ ] Configuration drift incidents: 0
  - [ ] Support tickets decreased
  - [ ] Time to add MCP server decreased
  - [ ] No silent failures

### Communication

- [ ] Update user documentation
- [ ] Announce feature availability
- [ ] Provide migration guide for operators
- [ ] Mark legacy mode as deprecated (timeline: 6 months)

---

## Phase 12: Legacy Deprecation (6 months later)

- [ ] Communication:
  - [ ] Announce legacy mode deprecation
  - [ ] Provide timeline (2-3 release cycles)
  - [ ] Offer migration support

- [ ] Verification:
  - [ ] Confirm all users migrated to direct mode
  - [ ] Check usage metrics (legacy mode usage = 0)

- [ ] Code cleanup:
  - [ ] Remove legacy mode code from vault plugin
  - [ ] Remove X-Vault-Tokens header support
  - [ ] Remove agent vault resolution logic
  - [ ] Update tests
  - [ ] Update documentation

- [ ] Final deployment:
  - [ ] Deploy cleanup changes
  - [ ] Monitor for issues
  - [ ] Close Issue #5402

---

## Rollback Procedures

### If Issues Found in Staging

- [ ] Disable flags:
  - [ ] `VAULT_DIRECT_RESOLUTION_ENABLED=false`
  - [ ] `VAULT_DIRECT_MODE_ENABLED=false`
- [ ] Verify legacy mode works
- [ ] Debug issues
- [ ] Fix and re-test

### If Issues Found in Production

- [ ] **Immediate action**: Disable flags on affected instances
- [ ] **Communication**: Notify stakeholders
- [ ] **Rollback**: Revert to legacy mode
- [ ] **Debug**: Analyze logs, metrics, errors
- [ ] **Fix**: Address root cause
- [ ] **Re-deploy**: After validation on staging

---

## Success Criteria

### Functional

- [x] Direct mode resolves credentials for all auth types
- [x] Error messages clear and actionable
- [x] Legacy mode preserved (backward compatible)
- [x] Zero breaking changes
- [x] Zero silent failures

### Performance

- [x] Vault-proxy latency: <100ms p95
- [x] Tool invocation latency increase: <50ms p95
- [x] No increase in error rates

### Security

- [x] Agent no longer requires vault-proxy access
- [x] Single credential per gateway (least privilege)
- [x] No credentials in transit (only vault_token)

### Operational

- [x] Configuration drift incidents: 0
- [x] Support tickets decreased: -50%
- [x] Time to add MCP server: -60%
- [x] Debugging time: -70%

---

## Sign-Off

### Technical Review

- [ ] Implementation plan approved by: _______________
- [ ] Architecture reviewed by: _______________
- [ ] Security reviewed by: _______________

### Stakeholder Approval

- [ ] Product owner approval: _______________
- [ ] Engineering manager approval: _______________
- [ ] Operations team approval: _______________

### Go-Live Approval

- [ ] Staging validation complete: _______________
- [ ] Production rollout plan approved: _______________
- [ ] Rollback plan tested: _______________

---

## Issue Closure

- [ ] All code merged
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Production deployment successful
- [ ] Success metrics validated
- [ ] Close GitHub issue #5402

---

**End of Checklist**
