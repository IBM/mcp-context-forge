# Issue #5402: Architecture Diagrams

## Architectural Justification: Why `vault_credential_alias` is Required

### The Core Problem

The current tag-based system requires **three separate configuration points** that must be manually coordinated:

1. **Agent token key naming**: `"github.com:USER:PAT:x"` - defined in agent runtime
2. **Gateway system tag**: `"system:github.com"` - defined in gateway configuration
3. **Gateway auth header tag**: `"AUTH_HEADER:X-GitHub-Token"` - defined in gateway configuration

These three strings must align perfectly through **brittle string-matching logic**:
- Token key prefix (`github.com`) must match system tag suffix (`github.com`)
- Auth header tag must specify the correct HTTP header name
- Any mismatch results in **silent authentication failures**

### Why `vault_credential_alias` is the Solution

The `vault_credential_alias` field provides a **direct, explicit link** between a gateway and its vault credential, replacing the three-way coordination with a single authoritative reference:

```python
# Single source of truth - no string matching required
{
  "name": "GitHub MCP Server",
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal"  # Direct vault reference
}
```

**How it works:**
1. Gateway declares: "I need credential `github-personal` from vault"
2. Vault plugin reads this field during tool invocation
3. Vault plugin calls vault-proxy: `resolve_credential(owner, alias="github-personal")`
4. Vault-proxy returns credential **with metadata**: `{secretValue, authType, headerName}`
5. Vault plugin injects auth header based on **vault's authoritative metadata**

**Key architectural benefits:**
- ✅ **Single source of truth**: Vault is authoritative for both credential value and injection metadata
- ✅ **Explicit failures**: Missing credential = immediate, clear error (not silent failure)
- ✅ **No string parsing**: Direct alias lookup, no tag matching logic
- ✅ **Separation of concerns**: Agent doesn't resolve credentials, Context Forge does
- ✅ **Reduced attack surface**: Agent no longer needs vault-proxy access

### Why Not Use Existing Fields?

**Tags?** 
- Require string parsing and matching logic (fragile)
- Support arbitrary labels, not structured credential references
- No way to enforce uniqueness or validity
- Silent failures when tags don't align

**URL?**
- Identifies the MCP server endpoint, not the credential to use
- Same MCP server may need different credentials per user/team
- No semantic connection between URLs and vault aliases

**Name/Description?**
- Human-readable fields, not machine configuration
- No guaranteed format or uniqueness
- Would conflate display names with credential references

**Metadata/Custom Fields?**
- Less discoverable (not in primary schema)
- No database index support
- Not part of standard CRUD validation

### Architectural Principle

The `vault_credential_alias` field follows the **explicit configuration over convention** principle:
- **Explicit**: Each gateway declares exactly which vault credential it needs
- **Validated**: Database schema enforces field constraints (255 char max, indexed)
- **Discoverable**: Field appears in API responses, admin UI, documentation
- **Authoritative**: Vault metadata (not gateway tags) determines injection method

This eliminates the "coordination problem" inherent in convention-based tag matching.

---

## Current Architecture (Tag-Based - Fragile)

```
┌─────────────────────────────────────────────────────────────────┐
│ User Request                                                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ agent_langchain_mcp                                             │
│                                                                  │
│ Input:                                                           │
│   - vault_entity_id: "user@example.com"                        │
│   - vault_token: "vault_token_abc"                             │
│   - tokens: {"github.com:USER:PAT:x": "token_path"}            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ vault-proxy (Wrap)                                              │
│                                                                  │
│ Request: GET /api/secret/v1/wrap/{user}/{token_path}           │
│ Response: "wrapped_token_abc123"                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ vault-proxy (Unwrap)                                            │
│                                                                  │
│ Request: POST /api/secret/v1/unwrap                            │
│ Response: "ghp_abc123"  (plain token)                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ agent_langchain_mcp (Build Headers)                            │
│                                                                  │
│ X-Vault-Tokens: {                                               │
│   "github.com:USER:PAT:x": "ghp_abc123"                         │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Context Forge (:4444/mcp)                                       │
│                                                                  │
│ Vault Plugin (tool_pre_invoke):                                │
│   1. Parse X-Vault-Tokens header                               │
│   2. Extract gateway tags:                                      │
│      - "system:github.com"                                      │
│      - "AUTH_HEADER:X-GitHub-Token"                             │
│   3. Match token key "github.com:USER:PAT:x" to tag            │
│   4. Match AUTH_HEADER tag for header name                     │
│   5. Inject: X-GitHub-Token: ghp_abc123                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ MCP Server (GitHub API)                                         │
│                                                                  │
│ Request Headers:                                                │
│   X-GitHub-Token: ghp_abc123                                    │
└─────────────────────────────────────────────────────────────────┘

FRAGILE POINTS:
❌ Token key "github.com:USER:PAT:x" must match tag "system:github.com"
❌ AUTH_HEADER tag must be correctly configured
❌ Silent failures if any part mismatches
❌ Agent requires vault-proxy access (security risk)
```

---

## New Architecture (Direct Integration - Robust)

```
┌─────────────────────────────────────────────────────────────────┐
│ User Request                                                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ agent_langchain_mcp                                             │
│                                                                  │
│ Input:                                                           │
│   - vault_entity_id: "user@example.com"                        │
│   - vault_token: "vault_token_abc"                             │
│                                                                  │
│ VAULT_DIRECT_MODE_ENABLED=true                                 │
│   → Skip vault resolution                                       │
│   → Pass vault credentials to Context Forge                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Context Forge (:4444/mcp)                                       │
│                                                                  │
│ Request Headers:                                                │
│   Authorization: Bearer <cf_token>                              │
│   X-Vault-Token: vault_token_abc                                │
│   X-User-Name: user@example.com                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ VaultDirect Plugin (NEW PLUGIN - tool_pre_invoke)              │
│                                                                  │
│ 1. Read gateway.vault_credential_alias = "github-personal"     │
│ 2. Extract vault_token and user_name from request              │
│ 3. Call VaultProxyClient.resolve_credential()                  │
│                                                                  │
│ NOTE: Separate plugin from legacy vault plugin                 │
│ Routing: vault_credential_alias exists → vault_direct          │
│          vault_credential_alias absent → vault (legacy)        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ vault-proxy (Wrap)                                              │
│                                                                  │
│ Request: POST /api/secret/v1/wrap/user@example.com/github-...  │
│ Response: "wrapped_token_xyz"                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ vault-proxy (Unwrap)                                            │
│                                                                  │
│ Request: POST /api/secret/v1/unwrap                            │
│ Response: {                                                     │
│   "secretValue": "ghp_abc123",                                  │
│   "authType": "PAT",                                            │
│   "headerName": "X-GitHub-Token"                                │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Vault Plugin (Inject Header)                                   │
│                                                                  │
│ Based on authType="PAT" and headerName="X-GitHub-Token":       │
│   → Inject: X-GitHub-Token: ghp_abc123                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ MCP Server (GitHub API)                                         │
│                                                                  │
│ Request Headers:                                                │
│   X-GitHub-Token: ghp_abc123                                    │
└─────────────────────────────────────────────────────────────────┘

ROBUST POINTS:
✅ Single source of truth: gateway.vault_credential_alias
✅ Vault metadata determines injection method
✅ Explicit errors when credentials missing
✅ Agent no longer needs vault-proxy access
```

---

## Component Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER / CLIENT                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           │ 1. Query + vault credentials
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                    agent_langchain_mcp                          │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ VAULT_DIRECT_MODE_ENABLED?                             │    │
│  │                                                         │    │
│  │  TRUE:  Skip fetch_tokens()                            │    │
│  │         Add X-Vault-Token + X-User-Name headers        │    │
│  │                                                         │    │
│  │  FALSE: Call fetch_tokens()                            │    │
│  │         Add X-Vault-Tokens header (legacy)             │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           │ 2. MCP request with vault headers
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Context Forge                              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ Plugin Router (automatic selection)                    │    │
│  │                                                         │    │
│  │ gateway.vault_credential_alias exists?                 │    │
│  │                                                         │    │
│  │  YES:  Use VaultDirect Plugin (NEW)                    │    │
│  │        ├─ Read gateway.vault_credential_alias          │    │
│  │        ├─ Extract X-Vault-Token, X-User-Name           │    │
│  │        ├─ Call vault-proxy                             │    │
│  │        └─ Inject header based on vault metadata        │    │
│  │                                                         │    │
│  │  NO:   Use Vault Plugin (LEGACY - UNCHANGED)           │    │
│  │        ├─ Parse X-Vault-Tokens header                  │    │
│  │        ├─ Match token keys to gateway tags             │    │
│  │        └─ Inject header based on AUTH_HEADER tag       │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │ (Direct mode only)   │                      │
    │                      ↓                      │
    │  ┌────────────────────────────────┐         │
    │  │      vault-proxy               │         │
    │  │                                │         │
    │  │  - Wrap credential             │         │
    │  │  - Unwrap → {secret, type}     │         │
    │  └────────────────────────────────┘         │
    │                      ↓                      │
    └──────────────────────┬──────────────────────┘
                           │
                           │ 3. Tool invocation with injected auth
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Server                                 │
│                   (GitHub, GitLab, etc.)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema Changes

### Before (No vault_credential_alias)

```sql
CREATE TABLE gateways (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url VARCHAR(767) NOT NULL,
    description TEXT,
    tags JSON,  -- [{"label": "system:github.com"}, {"label": "AUTH_HEADER:X-GitHub-Token"}]
    -- ... other fields ...
);
```

### After (With vault_credential_alias)

```sql
CREATE TABLE gateways (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url VARCHAR(767) NOT NULL,
    description TEXT,
    tags JSON,  -- Still supported for legacy mode
    vault_credential_alias VARCHAR(255),  -- NEW: "github-personal"
    -- ... other fields ...
);

CREATE INDEX ix_gateways_vault_credential_alias 
    ON gateways(vault_credential_alias);
```

**Migration**: Alembic migration adds column and index (idempotent, backward-compatible).

---

## Request/Response Flow Comparison

### Legacy Mode (Tag-Based)

```http
┌──────────────────────────────────────────────────────────────┐
│ Agent → Context Forge                                         │
├──────────────────────────────────────────────────────────────┤
│ POST /mcp HTTP/1.1                                            │
│ Host: cf.internal:4444                                        │
│ Authorization: Bearer <cf_token>                              │
│ X-Vault-Tokens: {"github.com:USER:PAT:x": "ghp_abc123"}      │
│ Content-Type: application/json                                │
│                                                                │
│ {                                                              │
│   "tool": "github-list-repos",                                │
│   "arguments": {"org": "myorg"}                               │
│ }                                                              │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Vault Plugin Processing                                      │
├──────────────────────────────────────────────────────────────┤
│ 1. Parse X-Vault-Tokens:                                     │
│    {"github.com:USER:PAT:x": "ghp_abc123"}                   │
│                                                               │
│ 2. Extract gateway tags:                                     │
│    - "system:github.com"                                     │
│    - "AUTH_HEADER:X-GitHub-Token"                            │
│                                                               │
│ 3. Match token key to system tag:                            │
│    "github.com:USER:PAT:x" → "github.com" ✅                 │
│                                                               │
│ 4. Determine header from AUTH_HEADER tag:                   │
│    "X-GitHub-Token" ✅                                        │
│                                                               │
│ 5. Inject header:                                            │
│    X-GitHub-Token: ghp_abc123                                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Context Forge → MCP Server                                   │
├──────────────────────────────────────────────────────────────┤
│ POST /mcp/tools/invoke HTTP/1.1                              │
│ Host: api.github.com                                          │
│ X-GitHub-Token: ghp_abc123                                    │
│ Content-Type: application/json                                │
│                                                                │
│ {                                                              │
│   "tool": "list-repos",                                       │
│   "arguments": {"org": "myorg"}                               │
│ }                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

### Direct Mode (Vault Integration)

```http
┌──────────────────────────────────────────────────────────────┐
│ Agent → Context Forge                                         │
├──────────────────────────────────────────────────────────────┤
│ POST /mcp HTTP/1.1                                            │
│ Host: cf.internal:4444                                        │
│ Authorization: Bearer <cf_token>                              │
│ X-Vault-Token: vault_token_abc                                │
│ X-User-Name: user@example.com                                 │
│ Content-Type: application/json                                │
│                                                                │
│ {                                                              │
│   "tool": "github-list-repos",                                │
│   "arguments": {"org": "myorg"}                               │
│ }                                                              │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Vault Plugin Processing (DIRECT MODE)                        │
├──────────────────────────────────────────────────────────────┤
│ 1. Read gateway config:                                      │
│    vault_credential_alias: "github-personal"                 │
│                                                               │
│ 2. Extract headers:                                          │
│    vault_token: "vault_token_abc"                            │
│    user_name: "user@example.com"                             │
│                                                               │
│ 3. Call VaultProxyClient.resolve_credential():               │
│    owner="user@example.com"                                  │
│    alias="github-personal"                                   │
│    vault_token="vault_token_abc"                             │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Context Forge → vault-proxy                                  │
├──────────────────────────────────────────────────────────────┤
│ POST /api/secret/v1/wrap/user@example.com/github-personal    │
│ Authorization: Bearer vault_token_abc                         │
│                                                                │
│ Response: {"wrapped_token": "wrapped_xyz"}                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Context Forge → vault-proxy                                  │
├──────────────────────────────────────────────────────────────┤
│ POST /api/secret/v1/unwrap                                   │
│ Authorization: Bearer vault_token_abc                         │
│ Content-Type: application/json                                │
│                                                                │
│ {"wrapped_token": "wrapped_xyz"}                             │
│                                                                │
│ Response: {                                                   │
│   "secretValue": "ghp_abc123",                                │
│   "authType": "PAT",                                          │
│   "headerName": "X-GitHub-Token"                              │
│ }                                                              │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Vault Plugin Processing (CONTINUED)                          │
├──────────────────────────────────────────────────────────────┤
│ 4. Determine injection method:                               │
│    authType="PAT" + headerName="X-GitHub-Token"              │
│    → Inject as custom header                                 │
│                                                               │
│ 5. Inject header:                                            │
│    X-GitHub-Token: ghp_abc123                                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Context Forge → MCP Server                                   │
├──────────────────────────────────────────────────────────────┤
│ POST /mcp/tools/invoke HTTP/1.1                              │
│ Host: api.github.com                                          │
│ X-GitHub-Token: ghp_abc123                                    │
│ Content-Type: application/json                                │
│                                                                │
│ {                                                              │
│   "tool": "list-repos",                                       │
│   "arguments": {"org": "myorg"}                               │
│ }                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Error Scenarios

### Legacy Mode Error (Silent Failure)

```
┌──────────────────────────────────────────────────────────────┐
│ Problem: Token key doesn't match gateway tag                 │
├──────────────────────────────────────────────────────────────┤
│ X-Vault-Tokens: {"gitlab.com:USER:PAT:x": "glpat_123"}      │
│ Gateway tags: ["system:github.com"]                          │
│                                                               │
│ Result: ❌ No match found                                     │
│         → No auth header injected                            │
│         → Tool proceeds UNAUTHENTICATED                      │
│         → GitHub returns 401                                 │
│         → Confusing error for user                           │
└──────────────────────────────────────────────────────────────┘
```

### Direct Mode Error (Explicit Failure)

```
┌──────────────────────────────────────────────────────────────┐
│ Problem: Credential not found in vault                       │
├──────────────────────────────────────────────────────────────┤
│ Gateway: vault_credential_alias="github-missing"             │
│ User: user@example.com                                        │
│                                                               │
│ vault-proxy response: 404 Not Found                          │
│                                                               │
│ Result: ✅ VaultNotFoundError raised                          │
│         → Clear error message:                               │
│           "Credential not found: github-missing               │
│            for user user@example.com"                        │
│         → Tool invocation stops immediately                  │
│         → User knows exactly what's missing                  │
└──────────────────────────────────────────────────────────────┘
```

---

## Deployment Architecture

### Development Environment

```
┌────────────────────────────────────────────────────────────┐
│ Developer Laptop                                            │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ agent        │  │ Context      │  │ vault-proxy  │    │
│  │ :5000        │  │ Forge :4444  │  │ :8080        │    │
│  │              │  │              │  │              │    │
│  │ DIRECT_MODE  │  │ DIRECT_MODE  │  │              │    │
│  │ =false       │  │ =false       │  │              │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  Both feature flags OFF → Legacy mode for safety           │
└────────────────────────────────────────────────────────────┘
```

### Staging Environment

```
┌────────────────────────────────────────────────────────────┐
│ Staging Cluster                                             │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ agent        │  │ Context      │  │ vault-proxy  │    │
│  │ :5000        │  │ Forge :4444  │  │ :8080        │    │
│  │              │  │              │  │              │    │
│  │ DIRECT_MODE  │  │ DIRECT_MODE  │  │              │    │
│  │ =true  ✅    │  │ =true  ✅    │  │              │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  Both feature flags ON → Direct mode testing               │
└────────────────────────────────────────────────────────────┘
```

### Production Environment (Phased Rollout)

```
┌────────────────────────────────────────────────────────────┐
│ Production Cluster - Phase 1 (10%)                          │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ agent-pod-1  │  │ cf-pod-1     │  │ vault-proxy  │    │
│  │ DIRECT=true  │  │ DIRECT=true  │  │ (shared)     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                       │
│  │ agent-pod-2  │  │ cf-pod-2     │                       │
│  │ DIRECT=false │  │ DIRECT=false │                       │
│  └──────────────┘  └──────────────┘                       │
│                                                             │
│  ... (8 more pods with DIRECT=false) ...                   │
│                                                             │
│  Gradual rollout with monitoring                           │
└────────────────────────────────────────────────────────────┘
```

---

## Security Comparison

### Attack Surface

```
┌────────────────────────────────────────────────────────────┐
│ Legacy Mode - Attack Surface                                │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │ Agent                                              │    │
│  │ - Requires vault-proxy access (credentials)       │    │
│  │ - Resolves ALL credentials upfront                │    │
│  │ - Stores multiple secrets in memory               │    │
│  │ - Sends all secrets in one header                 │    │
│  │                                                    │    │
│  │ Risk: Compromise agent → access to ALL vault      │    │
│  └───────────────────────────────────────────────────┘    │
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │ Context Forge                                      │    │
│  │ - Receives all credentials in X-Vault-Tokens      │    │
│  │ - No vault access needed                          │    │
│  │                                                    │    │
│  │ Risk: Intercept request → access to ALL secrets   │    │
│  └───────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Direct Mode - Reduced Attack Surface                       │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │ Agent                                              │    │
│  │ - NO vault-proxy access needed ✅                 │    │
│  │ - Only passes vault_token (not secrets)           │    │
│  │ - No secret resolution                            │    │
│  │                                                    │    │
│  │ Risk: Compromise agent → vault_token exposed,     │    │
│  │       but requires Context Forge to exploit       │    │
│  └───────────────────────────────────────────────────┘    │
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │ Context Forge                                      │    │
│  │ - Resolves ONE credential per gateway             │    │
│  │ - Requires vault-proxy access (credentials)       │    │
│  │ - Secret only in memory during tool invocation    │    │
│  │                                                    │    │
│  │ Risk: Compromise Context Forge → access to ONE    │    │
│  │       secret per request (least privilege)        │    │
│  └───────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────┘
```

---

## Monitoring & Observability

### Metrics to Track

```
┌────────────────────────────────────────────────────────────┐
│ Context Forge Metrics                                       │
├────────────────────────────────────────────────────────────┤
│ - vault.plugin.mode (gauge: "direct" or "legacy")          │
│ - vault.plugin.direct_mode.calls (counter)                 │
│ - vault.plugin.direct_mode.errors (counter)                │
│ - vault.plugin.direct_mode.latency (histogram)             │
│ - vault.plugin.direct_mode.cache_hits (counter)            │
│ - vault.plugin.legacy_mode.calls (counter)                 │
│ - vault.plugin.credentials_not_found (counter)             │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Agent Metrics                                               │
├────────────────────────────────────────────────────────────┤
│ - agent.vault.direct_mode_enabled (gauge: 0 or 1)          │
│ - agent.vault.passthrough_headers_added (counter)          │
│ - agent.vault.legacy_resolution_calls (counter)            │
│ - agent.vault.resolution_errors (counter)                  │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ vault-proxy Metrics                                         │
├────────────────────────────────────────────────────────────┤
│ - vault.wrap.requests (counter)                            │
│ - vault.unwrap.requests (counter)                          │
│ - vault.latency (histogram)                                │
│ - vault.errors (counter)                                   │
└────────────────────────────────────────────────────────────┘
```

---

## Conclusion

This architecture provides:

1. ✅ **Clear separation of concerns**: Agent handles user requests, Context Forge handles credential resolution
2. ✅ **Single source of truth**: Gateway configuration drives everything
3. ✅ **Reduced security surface**: Agent no longer needs vault access
4. ✅ **Explicit error handling**: No silent failures
5. ✅ **Backward compatibility**: Both modes coexist safely
6. ✅ **Observable**: Rich metrics for monitoring and debugging

The transition from tag-based to direct integration is **phased, safe, and reversible**.
