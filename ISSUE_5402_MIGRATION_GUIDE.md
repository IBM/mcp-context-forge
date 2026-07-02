# Issue #5402: Migration Guide - VirtualServer UUID Approach

## Overview

This guide covers migration from the legacy tag-based vault plugin to the new VirtualServer UUID-based vault_direct plugin.

**Migration strategy**: Gradual, per-virtual-server rollout with zero downtime. Both plugins coexist during migration period.

---

## Migration Timeline

| Phase | Duration | Activities |
|-------|----------|------------|
| **Preparation** | Week 1-2 | Deploy vault-proxy changes, update CF, add vault_direct plugin |
| **Pilot** | Week 3-4 | Migrate 1-2 virtual servers in staging |
| **Validation** | Week 5-6 | End-to-end testing, performance validation |
| **Production Rollout** | Week 7-16 | Gradual migration (10-20 virtual servers per week) |
| **Stabilization** | Week 17-26 | Monitor, fix issues, complete stragglers |
| **Deprecation** | Month 7-12 | Mark legacy plugin deprecated, remove after 6 months |

---

## Prerequisites

### System Requirements

**Vault-Proxy**:
- ✅ New API endpoint: `GET /api/secret/v1/by-uuid/{user_id}/{virtualServerUuid}`
- ✅ Support for self-describing credential structs
- ✅ Support for credential arrays (multi-system virtual servers)

**Context Forge**:
- ✅ vault_direct plugin installed and enabled
- ✅ Plugin routing logic (detect X-Vault-Token header)
- ✅ Virtual server UUID available in plugin context

**Agent**:
- ✅ Remove vault credential resolution code
- ✅ Pass X-Vault-Token header to CF (instead of X-Vault-Tokens)
- ✅ Remove config file parsing

---

## Phase 1: Preparation (Weeks 1-2)

### Step 1.1: Deploy Vault-Proxy Changes

**New API Endpoint**:

```python
# vault-proxy implementation
@app.get("/api/secret/v1/by-uuid/{user_id}/{virtual_server_uuid}")
async def get_credential_by_uuid(
    user_id: str,
    virtual_server_uuid: str,
    vault_token: str = Header(None, alias="X-Vault-Token")
):
    """Resolve credentials by virtual server UUID.
    
    Returns:
        - Single credential (dict) for single-system virtual servers
        - Array of credentials (list) for multi-system virtual servers
    """
    # Validate vault token
    if not validate_vault_token(vault_token):
        raise HTTPException(401, "Invalid vault token")
    
    # Lookup credential(s) at path: secret/users/{user_id}/{virtual_server_uuid}
    path = f"secret/users/{user_id}/{virtual_server_uuid}"
    
    try:
        data = vault_client.read(path)
        
        # Check if single credential or array
        if isinstance(data, dict) and "secretValue" in data:
            # Single credential
            return VaultCredential.parse_obj(data)
        elif isinstance(data, list):
            # Multiple credentials
            return [VaultCredential.parse_obj(item) for item in data]
        else:
            raise HTTPException(404, "Invalid credential format")
    
    except VaultNotFoundError:
        raise HTTPException(404, "Credentials not found")
```

**Validation**:
```bash
# Test single-system credential
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  http://vault-proxy:8080/api/secret/v1/by-uuid/user@example.com/vs-github-abc123

# Expected response:
{
  "secretValue": "ghp_abc123",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}

# Test multi-system credentials
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  http://vault-proxy:8080/api/secret/v1/by-uuid/user@example.com/vs-dev-tools-xyz

# Expected response (array):
[
  {"secretValue": "ghp_...", "authType": "PAT", "headerName": "X-GitHub-Token", "system": "github.com"},
  {"secretValue": "jira_...", "authType": "BASIC", "headerName": "Authorization", "system": "jira.com"}
]
```

### Step 1.2: Deploy Context Forge Changes

**Add vault_direct plugin**:

```bash
# Create plugin files
mkdir -p plugins/vault_direct
touch plugins/vault_direct/__init__.py
touch plugins/vault_direct/vault_client.py
touch plugins/vault_direct/vault_direct_plugin.py
```

**Update plugins/config.yaml**:
```yaml
# Legacy vault plugin (keep enabled during migration)
vault:
  enabled: true
  config:
    system_tag_prefix: "system"
    vault_header_name: "X-Vault-Tokens"
    vault_handling: "raw"
    system_handling: "tag"
    auth_header_tag_prefix: "AUTH_HEADER"

# New vault_direct plugin
vault_direct:
  enabled: true
  config:
    vault_proxy_url: "${VAULT_PROXY_URL}"
    vault_proxy_timeout: 5.0
    verify_ssl: true
    rate_limit_max_requests: 20
    rate_limit_window_seconds: 60
```

**Plugin routing logic** (mcpgateway/middleware/plugin_router.py):
```python
def select_vault_plugin(request) -> Optional[str]:
    """Select which vault plugin to use based on request headers.
    
    Returns:
        "vault_direct" - New UUID-based approach
        "vault" - Legacy tag-based approach
        None - No vault plugin needed
    """
    # New format: has X-Vault-Token header (user's vault token)
    if "X-Vault-Token" in request.headers:
        return "vault_direct"
    
    # Legacy format: has X-Vault-Tokens header (resolved credentials)
    elif "X-Vault-Tokens" in request.headers:
        return "vault"
    
    # No vault plugin needed
    return None
```

**Deploy**:
```bash
# Deploy to staging
make deploy-staging

# Verify both plugins loaded
curl http://staging:4444/api/v1/admin/plugins | jq '.[] | select(.id | contains("vault"))'

# Expected output:
# [
#   {"id": "vault", "enabled": true, "version": "1.0.0"},
#   {"id": "vault_direct", "enabled": true, "version": "1.0.0"}
# ]
```

---

## Phase 2: Pilot Migration (Weeks 3-4)

### Step 2.1: Select Pilot Virtual Servers

**Criteria**:
- ✅ Low traffic (fewer users, fewer tool invocations)
- ✅ Single-system (not multi-system) for simplicity
- ✅ Active development team (can provide quick feedback)
- ✅ Non-critical (failure won't impact production workflows)

**Example pilot candidates**:
1. Internal GitHub MCP (dev team only)
2. Test Jira instance (QA team only)

### Step 2.2: Migrate Credentials to Vault

**For each pilot virtual server**:

```bash
# Identify virtual server UUID
VS_UUID="vs-github-dev-abc123"
VS_NAME="GitHub Dev MCP"

# Identify users
USERS=("dev1@example.com" "dev2@example.com" "dev3@example.com")

# For each user, create credential in vault
for USER in "${USERS[@]}"; do
  echo "Migrating credential for $USER to $VS_UUID"
  
  # User creates credential in vault-proxy UI or CLI
  vault kv put secret/users/$USER/$VS_UUID \
    secretValue="<user's GitHub PAT>" \
    authType="PAT" \
    headerName="X-GitHub-Token" \
    system="github.com"
  
  echo "✅ Credential created for $USER"
done
```

**Validation**:
```bash
# Verify credential readable by CF service token
CF_VAULT_TOKEN="<CF service token>"

for USER in "${USERS[@]}"; do
  curl -H "X-Vault-Token: $CF_VAULT_TOKEN" \
    http://vault-proxy:8080/api/secret/v1/by-uuid/$USER/$VS_UUID
  
  # Should return credential struct
done
```

### Step 2.3: Update Agent

**Remove old code**:
```python
# REMOVE: Vault credential resolution
# agent/vault_resolver.py (DELETE entire file)

# REMOVE: Config file parsing
# agent/config.py
# - load_vault_credentials()
# - parse_credential_mapping()

# REMOVE: X-Vault-Tokens header construction
# agent/cf_client.py
# - build_vault_tokens_header()
```

**New code**:
```python
# agent/cf_client.py

async def invoke_tool(
    virtual_server_uuid: str,
    tool_name: str,
    arguments: dict,
    user_vault_token: str
):
    """Invoke tool via Context Forge.
    
    Args:
        virtual_server_uuid: Virtual server UUID
        tool_name: Tool to invoke
        arguments: Tool arguments
        user_vault_token: User's vault token (pass-through)
    """
    url = f"{CF_BASE_URL}/servers/{virtual_server_uuid}/mcp"
    
    headers = {
        "Authorization": f"Bearer {user_jwt}",
        "X-Vault-Token": user_vault_token  # ← Pass user's vault token
    }
    
    body = {
        "tool_name": tool_name,
        "arguments": arguments
    }
    
    return await http_post(url, headers=headers, json=body)
```

**Agent deployment**:
```bash
# Deploy updated agent to staging
./deploy_agent.sh staging

# Verify agent version
agent --version
# Should show new version without vault resolution code
```

### Step 2.4: End-to-End Testing

**Test single-system virtual server**:

```bash
# User: dev1@example.com
# Virtual server: vs-github-dev-abc123
# Tool: list-repos

# 1. User authenticates and gets vault token
USER_VAULT_TOKEN=$(vault login -method=ldap username=dev1 -format=json | jq -r .auth.client_token)

# 2. Agent invokes tool
agent invoke \
  --virtual-server vs-github-dev-abc123 \
  --tool list-repos \
  --args '{"org": "myorg"}' \
  --vault-token $USER_VAULT_TOKEN

# 3. Verify success
# Expected: List of repositories returned

# 4. Check CF logs for vault_direct plugin activity
kubectl logs -f context-forge-pod | grep "vault_direct"

# Expected log entries:
# [INFO] vault_direct: Resolving credential for vs-github-dev-abc123, user dev1@example.com
# [INFO] vault_direct: Credential resolved successfully, auth_type=PAT, system=github.com
# [DEBUG] vault_direct: Injected auth header X-GitHub-Token
```

**Verify credential injection**:

```bash
# Check backend MCP server received correct auth header
kubectl logs -f github-mcp-server-pod | grep "X-GitHub-Token"

# Expected: Requests have X-GitHub-Token header with dev1's PAT
```

**Test error scenarios**:

```bash
# 1. Missing credential
# User dev4 has NOT created credential in vault
agent invoke \
  --virtual-server vs-github-dev-abc123 \
  --tool list-repos \
  --vault-token $USER_VAULT_TOKEN

# Expected error:
# "No credentials found for virtual server 'GitHub Dev MCP'. Please configure credentials in vault-proxy."

# 2. Invalid vault token
agent invoke \
  --virtual-server vs-github-dev-abc123 \
  --tool list-repos \
  --vault-token "invalid_token"

# Expected error:
# "Vault authentication required. Ensure X-Vault-Token header and valid JWT are present."

# 3. Rate limit exceeded
# Make 21 requests in 1 minute
for i in {1..21}; do
  agent invoke --virtual-server vs-github-dev-abc123 --tool list-repos &
done
wait

# Expected: Last request returns 429 Too Many Requests
```

---

## Phase 3: Validation (Weeks 5-6)

### Step 3.1: Performance Testing

**Metrics to collect**:

```bash
# 1. Vault lookup latency (p50, p95, p99)
kubectl logs context-forge-pod | grep "vault_direct" | grep "latency_ms" | \
  jq -s 'map(.latency_ms) | [min, (add/length), max]'

# Target: p95 < 500ms, p99 < 1000ms

# 2. Success rate
kubectl logs context-forge-pod | grep "vault_direct" | grep "resolved successfully" | wc -l
# vs.
kubectl logs context-forge-pod | grep "vault_direct" | grep "not found" | wc -l

# Target: >99% success rate

# 3. Cache hit rate (if caching enabled)
kubectl logs context-forge-pod | grep "vault_direct" | grep "cache_hit" | wc -l
# vs.
kubectl logs context-forge-pod | grep "vault_direct" | grep "cache_miss" | wc -l

# Target: >80% cache hit rate
```

**Load testing**:

```bash
# Use k6 or similar tool
k6 run load_test.js

# load_test.js:
import http from 'k6/http';
import { check } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 100 },  // Ramp up to 100 users
    { duration: '5m', target: 100 },  // Stay at 100 users
    { duration: '2m', target: 0 },    // Ramp down
  ],
};

export default function() {
  const res = http.post(
    'http://staging:4444/servers/vs-github-dev-abc123/mcp',
    JSON.stringify({
      tool_name: 'list-repos',
      arguments: { org: 'myorg' }
    }),
    {
      headers: {
        'Authorization': `Bearer ${__ENV.USER_JWT}`,
        'X-Vault-Token': __ENV.USER_VAULT_TOKEN,
        'Content-Type': 'application/json'
      }
    }
  );
  
  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 2s': (r) => r.timings.duration < 2000,
  });
}
```

### Step 3.2: Security Validation

**Audit trail verification**:

```bash
# 1. Verify all credential accesses logged
kubectl logs context-forge-pod | grep "vault_direct" | grep "resolution attempt" | \
  jq -s 'map({user, virtual_server_uuid, timestamp})'

# 2. Verify no secret values in logs
kubectl logs context-forge-pod | grep "ghp_" || echo "✅ No secrets in logs"

# 3. Verify rate limiting works
# Make 21 requests in 1 minute, verify 429 on last request
```

**Penetration testing**:

```bash
# 1. Test credential enumeration
# Try to determine if credential exists by error message
for VS_UUID in $(generate_random_uuids 100); do
  agent invoke --virtual-server $VS_UUID --tool list-repos 2>&1
done

# Verify: All errors are generic (no "exists" vs "doesn't exist")

# 2. Test unauthorized access
# User A tries to use User B's virtual server
# Expected: 403 Forbidden or 404 Not Found (no enumeration)

# 3. Test vault token injection
# Try to send vault token in query param or request body
# Expected: Rejected (only accept X-Vault-Token header)
```

---

## Phase 4: Production Rollout (Weeks 7-16)

### Step 4.1: Rollout Strategy

**Gradual rollout by team/department**:

| Week | Teams | Virtual Servers | Users |
|------|-------|-----------------|-------|
| 7-8 | Dev team | 5-10 | ~20 |
| 9-10 | QA team | 10-15 | ~30 |
| 11-12 | Product team | 15-20 | ~50 |
| 13-14 | Sales team | 20-25 | ~100 |
| 15-16 | All remaining | 25+ | All |

**Rollback plan**:
- If issues detected: Pause rollout
- Users revert to legacy agent version (uses X-Vault-Tokens)
- Legacy vault plugin still enabled (no CF changes needed)

### Step 4.2: Migration Checklist (Per Virtual Server)

```bash
# Checklist for migrating vs-example-abc123

[ ] 1. Identify all users of this virtual server
[ ] 2. Notify users of migration (email, Slack, etc.)
[ ] 3. Create migration guide for users (how to create credentials in vault)
[ ] 4. For each user:
    [ ] a. User creates credential in vault-proxy
    [ ] b. User updates agent to new version
    [ ] c. User tests tool invocation
    [ ] d. User confirms success
[ ] 5. Monitor CF logs for errors
[ ] 6. Monitor backend MCP server logs for auth failures
[ ] 7. Collect feedback from users
[ ] 8. Mark virtual server as "migrated" in tracking sheet
```

**Migration tracking spreadsheet**:

| Virtual Server | UUID | Users | Status | Migration Date | Notes |
|----------------|------|-------|--------|----------------|-------|
| GitHub Dev | vs-github-dev-abc123 | 5 | ✅ Complete | 2026-07-15 | No issues |
| Jira Test | vs-jira-test-xyz456 | 3 | ✅ Complete | 2026-07-16 | 1 user had wrong token, resolved |
| GitHub Prod | vs-github-prod-def789 | 50 | 🔄 In Progress | 2026-07-20 | 30/50 users migrated |
| ... | ... | ... | ... | ... | ... |

### Step 4.3: User Communication

**Email template**:

```
Subject: Action Required: Migrate to New Vault Integration (Virtual Server: <NAME>)

Hi <USER>,

We're upgrading the vault integration for <VIRTUAL_SERVER_NAME> to improve security and reliability.

What you need to do:
1. Create credential in vault-proxy:
   - Go to: https://vault-proxy.company.com
   - Navigate to: My Credentials > Add New
   - Virtual Server: <VIRTUAL_SERVER_NAME>
   - UUID: <VIRTUAL_SERVER_UUID>
   - Follow the wizard to store your <SYSTEM> credential

2. Update your agent:
   - Run: agent update
   - Verify: agent --version (should show v2.0.0+)

3. Test:
   - Run: agent invoke --virtual-server <UUID> --tool <TOOL_NAME>
   - If successful, you're done!

Timeline:
- Migration window: <START_DATE> to <END_DATE>
- Legacy support ends: <END_DATE + 2 weeks>

Questions? Reply to this email or ask in #vault-migration Slack channel.

Thanks!
DevOps Team
```

---

## Phase 5: Stabilization (Weeks 17-26)

### Step 5.1: Monitoring

**Key metrics to track**:

```python
# Prometheus metrics
vault_direct_calls_total{status="success|failure"}
vault_direct_latency_seconds{quantile="0.5|0.95|0.99"}
vault_direct_cache_hit_rate
vault_direct_rate_limit_exceeded_total

# Alerts
- vault_direct error rate > 1% for 5 minutes
- vault_direct p95 latency > 1s for 5 minutes
- vault_direct rate limit exceeded > 10 times per minute
```

**Dashboards**:

```yaml
# Grafana dashboard
panels:
  - title: "Vault Direct Success Rate"
    query: |
      sum(rate(vault_direct_calls_total{status="success"}[5m]))
      /
      sum(rate(vault_direct_calls_total[5m]))
    target: "> 99%"
  
  - title: "Vault Direct Latency (p95)"
    query: |
      histogram_quantile(0.95, vault_direct_latency_seconds)
    target: "< 500ms"
  
  - title: "Legacy vs New Plugin Usage"
    query: |
      sum(rate(vault_calls_total[5m])) by (plugin)
    # Show: vault (legacy) vs vault_direct (new)
```

### Step 5.2: Issue Resolution

**Common issues and solutions**:

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **Missing credential** | "Credentials not found" error | User creates credential in vault-proxy |
| **Wrong system field** | Auth fails at backend | User updates credential with correct system (e.g., "github.com") |
| **Expired vault token** | "Invalid vault token" error | User re-authenticates to get new token |
| **Rate limit exceeded** | 429 Too Many Requests | Increase rate limit or ask user to slow down |
| **Multi-system credential missing** | "No credential for system X" | User creates credential for missing system |

---

## Phase 6: Deprecation (Months 7-12)

### Step 6.1: Mark Legacy Plugin Deprecated

**Update plugins/vault/README.md**:

```markdown
# Vault Plugin (Legacy - DEPRECATED)

⚠️ **DEPRECATED**: This plugin uses tag-based credential matching and is deprecated
in favor of the `vault_direct` plugin which provides direct vault-proxy integration.

**Migration**: Follow the migration guide at docs/migration/issue-5402.md

**Support timeline**:
- Deprecated: 2026-08-01
- Removal: 2027-02-01 (6 months notice)

**Why migrate**:
- ✅ Self-describing credentials (no tag matching)
- ✅ Multi-system virtual server support
- ✅ Better error messages
- ✅ Simpler configuration (no agent config file)
```

**Add deprecation warning in logs**:

```python
# plugins/vault/vault_plugin.py

class Vault(Plugin):
    def __init__(self, config):
        super().__init__(config)
        
        # Log deprecation warning
        logger.warning(
            "Legacy vault plugin is DEPRECATED and will be removed on 2027-02-01. "
            "Please migrate to vault_direct plugin. "
            "See: https://docs.company.com/migration/issue-5402"
        )
```

### Step 6.2: Remove Legacy Plugin (Month 12)

**Verification before removal**:

```bash
# 1. Confirm zero legacy plugin usage
kubectl logs context-forge-pod | grep 'plugin="vault"' | tail -n 100
# Should be empty or very few (stragglers only)

# 2. Confirm all virtual servers using vault_direct
SELECT vs.id, vs.name, COUNT(DISTINCT user_id) as user_count
FROM virtual_servers vs
JOIN credential_access_logs cal ON vs.id = cal.virtual_server_id
WHERE cal.plugin = 'vault'
  AND cal.timestamp > NOW() - INTERVAL 30 DAYS
GROUP BY vs.id, vs.name
ORDER BY user_count DESC;
# Should return 0 rows

# 3. Notify remaining users (if any)
# Send final notice: "Legacy plugin will be removed in 1 week"
```

**Removal steps**:

```bash
# 1. Disable legacy plugin
# plugins/config.yaml
vault:
  enabled: false  # Disable

# 2. Deploy to staging, test
make deploy-staging

# 3. Monitor for errors (should be none)
kubectl logs -f context-forge-staging-pod | grep "vault plugin not found" || echo "✅ No errors"

# 4. Deploy to production
make deploy-production

# 5. Monitor for 1 week
# If no issues, proceed to deletion

# 6. Delete legacy plugin files
git rm -r plugins/vault/
git commit -m "chore: remove deprecated vault plugin"
git push origin main

# 7. Update documentation
# Remove all references to legacy vault plugin
# Update migration guide to "migration complete"
```

---

## Rollback Procedures

### Rollback Scenario 1: Critical Bug in vault_direct Plugin

**Symptoms**:
- High error rate (>5%)
- Credential injection failures
- Users unable to invoke tools

**Rollback steps**:

```bash
# 1. Disable vault_direct plugin immediately
# plugins/config.yaml
vault_direct:
  enabled: false  # Disable

# 2. Deploy to production
kubectl rollout restart deployment/context-forge

# 3. Notify users to use legacy agent version
# Email: "Please revert to agent v1.x until issue is resolved"

# 4. Users revert agent
agent downgrade --version 1.9.0

# 5. Verify legacy plugin working
# Users should be able to invoke tools with X-Vault-Tokens header

# 6. Fix bug in vault_direct plugin
# Test fix in staging
# Re-enable when ready
```

### Rollback Scenario 2: Vault-Proxy API Issues

**Symptoms**:
- "Cannot connect to vault-proxy" errors
- High latency (>5s)
- Vault-proxy returning 500 errors

**Rollback steps**:

```bash
# 1. Check vault-proxy health
curl http://vault-proxy:8080/health

# 2. If vault-proxy down, fall back to legacy plugin
# plugins/config.yaml
vault_direct:
  enabled: false  # Disable temporarily

# 3. Fix vault-proxy
# Check logs: kubectl logs vault-proxy-pod
# Restart: kubectl rollout restart deployment/vault-proxy

# 4. Re-enable vault_direct once vault-proxy healthy
vault_direct:
  enabled: true
```

---

## Success Criteria

### Migration Complete When:

✅ **Adoption**:
- [ ] 100% of virtual servers migrated to vault_direct
- [ ] 100% of users have credentials in vault (UUID-based)
- [ ] 0 requests using legacy vault plugin (X-Vault-Tokens header)

✅ **Quality**:
- [ ] Error rate < 0.5%
- [ ] p95 latency < 500ms
- [ ] No security incidents
- [ ] Zero credential enumeration attacks

✅ **Documentation**:
- [ ] Migration guide published
- [ ] User documentation updated
- [ ] Admin documentation updated
- [ ] API documentation updated

✅ **Cleanup**:
- [ ] Legacy vault plugin removed
- [ ] X-Vault-Tokens header support removed
- [ ] Agent config file parsing removed
- [ ] All tests passing

---

## Post-Migration Checklist

### Immediate (Week 1 after completion)

- [ ] Announce migration complete
- [ ] Publish success metrics (adoption, performance, errors)
- [ ] Collect user feedback (survey)
- [ ] Document lessons learned
- [ ] Update runbooks

### Short-term (Month 1 after completion)

- [ ] Review monitoring dashboards (confirm stable)
- [ ] Review audit logs (confirm no security issues)
- [ ] Plan legacy plugin deprecation timeline
- [ ] Archive migration documentation

### Long-term (Month 3-6 after completion)

- [ ] Remove legacy plugin (month 6)
- [ ] Archive legacy code (tag release)
- [ ] Update training materials
- [ ] Celebrate with team! 🎉

---

## Appendix: Scripts and Tools

### Script: Migrate User Credentials

```bash
#!/bin/bash
# migrate_user_credentials.sh
# Migrate one user's credentials from legacy to UUID-based

set -e

USER_EMAIL="$1"
VIRTUAL_SERVER_UUID="$2"
SYSTEM="$3"
AUTH_TYPE="${4:-PAT}"
HEADER_NAME="${5:-Authorization}"

if [ -z "$USER_EMAIL" ] || [ -z "$VIRTUAL_SERVER_UUID" ] || [ -z "$SYSTEM" ]; then
  echo "Usage: $0 <user_email> <virtual_server_uuid> <system> [auth_type] [header_name]"
  exit 1
fi

echo "Migrating credential for $USER_EMAIL to $VIRTUAL_SERVER_UUID"

# Prompt user for secret value
read -sp "Enter secret value: " SECRET_VALUE
echo

# Create credential in vault
vault kv put "secret/users/$USER_EMAIL/$VIRTUAL_SERVER_UUID" \
  secretValue="$SECRET_VALUE" \
  authType="$AUTH_TYPE" \
  headerName="$HEADER_NAME" \
  system="$SYSTEM"

echo "✅ Credential created successfully"

# Test credential resolution
echo "Testing credential resolution..."
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  "http://vault-proxy:8080/api/secret/v1/by-uuid/$USER_EMAIL/$VIRTUAL_SERVER_UUID" | jq .

echo "✅ Migration complete"
```

### Script: Validate Migration

```bash
#!/bin/bash
# validate_migration.sh
# Validate that virtual server migration was successful

set -e

VIRTUAL_SERVER_UUID="$1"

if [ -z "$VIRTUAL_SERVER_UUID" ]; then
  echo "Usage: $0 <virtual_server_uuid>"
  exit 1
fi

echo "Validating migration for $VIRTUAL_SERVER_UUID"

# 1. Get list of users
USERS=$(curl -s "http://cf:4444/api/v1/admin/virtual-servers/$VIRTUAL_SERVER_UUID/users" | jq -r '.[].email')

# 2. For each user, check credential exists
MISSING_USERS=()
for USER in $USERS; do
  echo -n "Checking $USER... "
  
  if curl -sf -H "X-Vault-Token: $VAULT_TOKEN" \
    "http://vault-proxy:8080/api/secret/v1/by-uuid/$USER/$VIRTUAL_SERVER_UUID" > /dev/null; then
    echo "✅"
  else
    echo "❌ Missing"
    MISSING_USERS+=("$USER")
  fi
done

# 3. Report
echo ""
echo "Migration validation complete"
echo "Total users: ${#USERS[@]}"
echo "Missing credentials: ${#MISSING_USERS[@]}"

if [ ${#MISSING_USERS[@]} -gt 0 ]; then
  echo ""
  echo "Users with missing credentials:"
  for USER in "${MISSING_USERS[@]}"; do
    echo "  - $USER"
  done
  exit 1
else
  echo "✅ All users have credentials"
fi
```

---

## Contact and Support

**Migration support**:
- Slack: #vault-migration
- Email: devops@company.com
- Documentation: https://docs.company.com/migration/issue-5402

**Escalation**:
- L1: DevOps team (#devops-oncall)
- L2: Platform team (#platform-oncall)
- L3: Architect (madhav165)

**Office hours**:
- Daily: 10am-11am PT
- Zoom: https://zoom.us/vault-migration
- Drop-in for questions, help with migration, troubleshooting
