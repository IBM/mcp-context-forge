# Issue #5402: VirtualServer UUID Approach - Executive Summary

## Decision

**Adopt VirtualServer UUID approach** for direct vault integration (Approach C from comparison).

This is the architect-recommended solution (madhav165's GitHub comment) that uses self-describing credential structs stored at `{user_id}/{virtualServerUuid}` in vault.

---

## Why This Approach

### 1. Handles Multi-System Virtual Servers ✅

**Problem**: A single virtual server can aggregate tools from multiple backend systems (GitHub + Jira + Slack).

**Previous approaches failed**:
- Domain-based: Can only extract one domain from URL
- Alias-based: Awkward multi-alias schema

**UUID approach solves**:
```json
// Vault stores array of credentials, each with system field
[
  {"secretValue": "ghp_...", "system": "github.com", "authType": "PAT", "headerName": "X-GitHub-Token"},
  {"secretValue": "jira_...", "system": "jira.com", "authType": "BASIC", "headerName": "Authorization"},
  {"secretValue": "xoxb_...", "system": "slack.com", "authType": "OAUTH2", "headerName": "Authorization"}
]

// Plugin matches credential to backend by system field
tool = "list-repos" → backend.system = "github.com" → select credential where system == "github.com"
```

### 2. Uses Existing Infrastructure ✅

- Virtual server UUID already exists in every request path
- Destiny-services already uses `mcpServerCredential` table with `mcpServerUuid`
- No database schema changes needed
- Aligns with existing multi-tenant model

### 3. Self-Describing Credentials ✅

**Old approach** (tag-based):
```python
# Vault stores just secret
credential = "ghp_abc123"

# Must configure externally:
# - Gateway tag: system:github.com
# - Gateway tag: AUTH_HEADER:X-GitHub-Token
# - Plugin infers: Bearer vs raw value
```

**New approach** (self-describing):
```json
{
  "secretValue": "ghp_abc123",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}
```

**Benefits**:
- No AUTH_HEADER tags needed
- No auth type inference
- Vault is single source of truth
- Extensible (new auth types = add to enum)

### 4. Zero Configuration ✅

**User workflow**:
1. Create credential in vault-proxy: `{user_id}/{virtualServerUuid}`
2. Start using tools (no agent config, no gateway config)

**Agent simplification**:
- Remove vault credential resolution code
- Remove config file parsing
- Just pass user identity + vault token to CF

---

## Architecture

### Credential Structure

```typescript
// Single-system virtual server
interface VaultCredential {
  secretValue: string;      // The actual secret
  authType: AuthType;       // PAT, OAUTH2, JWT, BASIC, APIKEY, CUSTOM
  headerName: string;       // Which HTTP header to inject
  system: string;           // Domain/system identifier for routing
  metadata?: {
    expiresAt?: string;
    scope?: string;
    tokenType?: string;
  };
}

// Multi-system virtual server
type VaultCredentialResponse = VaultCredential | VaultCredential[];
```

### Request Flow

```
1. User invokes tool
   POST /servers/{virtualServerUuid}/mcp
   Headers:
     Authorization: Bearer {user_jwt}
     X-Vault-Token: {user_vault_token}

2. CF extracts context
   virtualServerUuid = path_params["virtualServerUuid"]
   user_id = decode_jwt(headers["Authorization"])["sub"]
   user_vault_token = headers["X-Vault-Token"]

3. CF calls vault-proxy
   GET /api/secret/v1/by-uuid/{user_id}/{virtualServerUuid}
   Returns: VaultCredential or VaultCredential[]

4. CF determines backend system for this tool
   tool = "list-repos"
   backend = virtual_server.find_backend_for_tool(tool)
   → backend.system = "github.com"

5. CF selects credential matching backend system
   credential = credentials.find(c => c.system == backend.system)

6. CF injects auth header based on credential metadata
   if credential.authType == "PAT":
       headers[credential.headerName] = credential.secretValue
   elif credential.authType == "OAUTH2":
       headers[credential.headerName] = f"Bearer {credential.secretValue}"
   # ... etc

7. CF forwards to backend gateway with injected auth
```

### Vault Storage Example

```
secret/
└── users/
    └── user@example.com/
        ├── vs-github-abc123                # Single-system
        │   ├── secretValue: "ghp_abc123"
        │   ├── authType: "PAT"
        │   ├── headerName: "X-GitHub-Token"
        │   └── system: "github.com"
        │
        └── vs-dev-tools-xyz789             # Multi-system
            ├── [0]
            │   ├── secretValue: "ghp_abc123"
            │   ├── authType: "PAT"
            │   ├── headerName: "X-GitHub-Token"
            │   └── system: "github.com"
            ├── [1]
            │   ├── secretValue: "amlyYTp0ZXN0Cg=="
            │   ├── authType: "BASIC"
            │   ├── headerName: "Authorization"
            │   └── system: "jira.atlassian.com"
            └── [2]
                ├── secretValue: "xoxb-slack-token"
                ├── authType: "OAUTH2"
                ├── headerName: "Authorization"
                └── system: "slack.com"
```

---

## Implementation Plan

### Phase 1: Vault-Proxy Changes (Weeks 1-2)

**New API endpoint**:
```
GET /api/secret/v1/by-uuid/{user_id}/{virtualServerUuid}
```

**Returns**:
- Single credential (JSON object) for single-system virtual servers
- Array of credentials (JSON array) for multi-system virtual servers

**Credential format**:
```json
{
  "secretValue": "string",
  "authType": "PAT|OAUTH2|JWT|BASIC|APIKEY|CUSTOM",
  "headerName": "string",
  "system": "string",
  "metadata": {}
}
```

### Phase 2: Context Forge Plugin (Weeks 3-4)

**New plugin**: `vault_direct`

**Key components**:
1. `VaultProxyClient` - HTTP client for vault-proxy API
2. `VaultDirect` plugin - Implements tool_pre_invoke hook
3. System field matching - Select credential by backend.system
4. Auth header injection - Based on authType metadata

**Files**:
- `plugins/vault_direct/vault_direct_plugin.py`
- `plugins/vault_direct/vault_client.py`
- `plugins/vault_direct/__init__.py`
- `plugins/config.yaml` (add vault_direct entry)

### Phase 3: Agent Changes (Weeks 5-6)

**Remove**:
- Vault credential resolution code
- Config file parsing (`~/.agent/vault_credentials.yaml`)
- X-Vault-Tokens header construction

**Keep**:
- User vault token pass-through
- User identity from JWT
- Request to CF with X-Vault-Token header

### Phase 4: Testing (Weeks 7-8)

**Unit tests**:
- Single-system virtual server credential resolution
- Multi-system virtual server credential selection
- Auth type header injection (PAT, OAUTH2, JWT, BASIC, APIKEY, CUSTOM)
- Error handling (not found, missing system, rate limit)

**Integration tests**:
- End-to-end single-system flow
- End-to-end multi-system flow (GitHub tool → GitHub cred, Jira tool → Jira cred)
- Mixed legacy + new plugin deployment

### Phase 5: Rollout (Weeks 9+)

```
Week  9: Staging deployment (vault-proxy + CF)
Week 10: Update one agent (staging)
Week 11: Validate end-to-end (staging)
Week 12: Production deployment (vault-proxy + CF)
Week 13-16: Gradual agent migration (production)
Week 17+: Monitor, iterate, deprecate legacy after 6 months
```

---

## API Examples

### Single-System Virtual Server

**Create virtual server**:
```bash
POST /api/v1/admin/virtual-servers
{
  "name": "GitHub MCP",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue"]
    }
  ]
}

Response: {"id": "vs-github-abc123", ...}
```

**User stores credential in vault**:
```bash
vault kv put secret/users/user@example.com/vs-github-abc123 \
  secretValue="ghp_abc123def456" \
  authType="PAT" \
  headerName="X-GitHub-Token" \
  system="github.com"
```

**Invoke tool**:
```bash
POST /servers/vs-github-abc123/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-repos",
  "arguments": {"org": "myorg"}
}
```

### Multi-System Virtual Server

**Create virtual server**:
```bash
POST /api/v1/admin/virtual-servers
{
  "name": "Developer Tools Suite",
  "backends": [
    {"system": "github.com", "gateway_id": "gw-gh-001", "tools": ["list-repos"]},
    {"system": "jira.com", "gateway_id": "gw-jira-001", "tools": ["list-issues"]},
    {"system": "slack.com", "gateway_id": "gw-slack-001", "tools": ["send-message"]}
  ]
}

Response: {"id": "vs-dev-tools-xyz789", ...}
```

**User stores credentials in vault (array)**:
```bash
cat > credentials.json <<EOF
[
  {
    "secretValue": "ghp_github_token",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.com"
  },
  {
    "secretValue": "xoxb-slack-token",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
EOF

vault kv put secret/users/user@example.com/vs-dev-tools-xyz789 @credentials.json
```

**Invoke GitHub tool**:
```bash
POST /servers/vs-dev-tools-xyz789/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-repos",
  "arguments": {"org": "myorg"}
}

# CF automatically:
# 1. Fetches all 3 credentials by UUID
# 2. Determines "list-repos" → backend.system = "github.com"
# 3. Selects credential where system == "github.com"
# 4. Injects X-GitHub-Token header
# 5. Forwards to gw-gh-001
```

**Invoke Jira tool (same virtual server)**:
```bash
POST /servers/vs-dev-tools-xyz789/mcp
Headers:
  Authorization: Bearer {user_jwt}
  X-Vault-Token: {user_vault_token}
Body:
{
  "tool_name": "list-issues",
  "arguments": {"project": "PROJ"}
}

# CF automatically:
# 1. Fetches same credentials (cached)
# 2. Determines "list-issues" → backend.system = "jira.com"
# 3. Selects credential where system == "jira.com"
# 4. Injects Authorization: Basic header
# 5. Forwards to gw-jira-001
```

---

## Security Features

### 1. Vault Token Transmission
- ✅ Via HTTP header `X-Vault-Token` (not request body)
- ✅ Masked in application logs
- ✅ Never logged in error messages

### 2. Rate Limiting
- ✅ 20 requests per minute per user + virtual server
- ✅ Prevents brute force credential discovery
- ✅ Returns 429 Too Many Requests with Retry-After

### 3. Audit Trail
- ✅ Log all credential resolution attempts
- ✅ Include: user, virtual server UUID, tool name, timestamp, success/failure
- ✅ Log credential metadata (auth type, system) but never secret values

### 4. Credential Enumeration Prevention
- ✅ Generic error messages (no "credential exists/doesn't exist")
- ✅ Same error for "not found" vs "vault unavailable"
- ✅ Detailed logging internal only (not exposed to client)

### 5. User Identity Verification
- ✅ JWT validated by middleware before plugin runs
- ✅ User ID from validated JWT (not client-provided)
- ✅ No trust in client-provided ownership fields

### 6. Service Token Scope
- ✅ CF uses service-level vault token (not user tokens for vault API calls)
- ✅ Read-only policy for user-scoped secrets
- ✅ Cannot modify or delete credentials

---

## Benefits Summary

### Technical
✅ **Uses existing infrastructure** - Virtual server UUIDs already exist  
✅ **Self-describing credentials** - All metadata in vault  
✅ **Multi-system native** - Array with system discriminator  
✅ **Zero DB changes** - No schema modifications  
✅ **Extensible** - New auth types = add to enum  

### Operational
✅ **Zero agent config** - No config files  
✅ **Simpler onboarding** - Just create credentials in vault  
✅ **Better errors** - Include virtual server name + system  
✅ **Easier debugging** - UUID path is deterministic  
✅ **Scalable** - O(1) config per virtual server  

### Security
✅ **No plain secrets in transit** - User vault token, not resolved secrets  
✅ **Audit trail** - All access logged with context  
✅ **Rate limiting** - Prevent brute force  
✅ **Generic errors** - No credential enumeration  

### Alignment
✅ **Matches destiny-services** - Uses same mcpServerUuid model  
✅ **Architect-endorsed** - madhav165's recommendation  
✅ **Industry standard** - Resource-based credential management  

---

## Key Documents

1. **ISSUE_5402_FINAL_DESIGN_V2.md** - Complete technical design (this approach)
2. **ISSUE_5402_APPROACH_COMPARISON_V2.md** - Detailed comparison of 3 approaches
3. **ISSUE_5402_SUMMARY_V2.md** - This executive summary

---

## Next Actions

### Immediate (Week 1)
- [ ] Share design with vault-proxy team
- [ ] Share design with destiny-services team
- [ ] Get API endpoint implementation timeline from vault-proxy
- [ ] Confirm credential struct format with destiny-services

### Short-term (Weeks 2-4)
- [ ] Implement vault-proxy API endpoint
- [ ] Implement CF vault_direct plugin
- [ ] Write unit tests
- [ ] Write integration tests

### Medium-term (Weeks 5-8)
- [ ] Update agent (remove credential resolution)
- [ ] Staging deployment
- [ ] End-to-end testing

### Long-term (Weeks 9+)
- [ ] Production rollout (gradual)
- [ ] Monitor metrics and errors
- [ ] Deprecate legacy vault plugin (after 6 months)

---

## Questions & Answers

### Q: Why not use domain-based lookup?
**A**: Cannot handle multi-system virtual servers. A virtual server that aggregates GitHub + Jira + Slack tools has one URL but needs credentials for three different systems. Domain extraction can only get one domain.

### Q: Why not use vault_credential_alias field?
**A**: Requires database migration, agent config file, and doesn't align with destiny-services model. Also awkward for multi-system (need JSON array or multiple fields).

### Q: What if virtual server UUID changes?
**A**: UUIDs are immutable. If a virtual server is deleted and recreated, it gets a new UUID, which is correct behavior (new identity = new credentials).

### Q: How does this work with OAuth2 token refresh?
**A**: Vault-proxy handles token refresh. CF just fetches the current valid token at tool invocation time.

### Q: What about caching credentials?
**A**: Can add short-lived cache (30-60s) in CF plugin to reduce vault-proxy calls for repeated tool invocations within same session. Cache key: `{user_id}:{virtualServerUuid}`.

### Q: What if user doesn't have credential for a system?
**A**: CF returns clear error: "No credential found for system 'jira.com' in virtual server 'Developer Tools Suite'". User knows exactly what to create in vault.

### Q: How to handle credential rotation?
**A**: User updates credential in vault. Next tool invocation fetches new value. No CF restart needed (stateless).

---

## Success Metrics

### Adoption (Month 1-3)
- [ ] 10+ virtual servers using vault_direct plugin
- [ ] 50+ users with UUID-based credentials in vault
- [ ] Zero production incidents from credential injection

### Quality (Month 1-6)
- [ ] <1% error rate for credential resolution
- [ ] <500ms p95 latency for vault lookups
- [ ] Zero security incidents (enumeration, unauthorized access)

### Migration (Month 3-9)
- [ ] 50% of agents migrated to new flow (Month 6)
- [ ] 90% of agents migrated to new flow (Month 9)
- [ ] Legacy vault plugin marked deprecated (Month 6)

### Deprecation (Month 9-12)
- [ ] Legacy vault plugin removed (Month 12)
- [ ] All agents using vault_direct plugin
- [ ] X-Vault-Tokens header support removed

---

## Conclusion

The **VirtualServer UUID approach** is the recommended solution for Issue #5402 because:

1. ✅ **Only approach that handles multi-system virtual servers**
2. ✅ Aligns with existing infrastructure (destiny-services)
3. ✅ Provides best user experience (zero configuration)
4. ✅ Offers best operational characteristics (clear errors, easy debugging)
5. ✅ Has architect endorsement

This is a **production-ready design** that solves the core problem (eliminate fragile tag-based system) while supporting advanced use cases (multi-system virtual servers).
