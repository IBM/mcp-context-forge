# Upgrade Guide: 0.9.x → 1.0.0-RC3

**Target Version:** 1.0.0-RC3 (2026-04-14)
**Previous Version:** 0.9.x
**Breaking Changes:** Yes (8 major changes)
**Estimated Migration Time:** 2-4 hours

---

## Overview

ContextForge 1.0.0-RC3 includes **242 commits** with significant breaking changes across authentication, plugins, database support, and security defaults. This guide provides step-by-step migration instructions.

**⚠️ CRITICAL:** Review all sections before upgrading. Some changes require configuration updates or data migration.

---

## Pre-Upgrade Checklist

- [ ] **Backup your database** (SQLite: copy file, PostgreSQL: `pg_dump`)
- [ ] **Review current configuration** (`.env` file and environment variables)
- [ ] **Check plugin configurations** (especially condition evaluation logic)
- [ ] **Document current SSRF/network settings** (if using internal services)
- [ ] **Test upgrade in non-production environment first**
- [ ] **Review CHANGELOG.md** for complete change list

---

## Breaking Changes & Migration Steps

### 1. 🛡️ SSRF Protection Defaults (CRITICAL)

**Impact:** Gateway may block connections to localhost and private networks by default.

#### What Changed

Three SSRF defaults inverted to strict security mode:

| Setting | 0.9.x Default | 1.0.0-RC3 Default | Impact |
|---------|---------------|-------------------|--------|
| `SSRF_ALLOW_LOCALHOST` | `true` | `false` | Blocks `127.0.0.1`, `localhost`, `::1` |
| `SSRF_ALLOW_PRIVATE_NETWORKS` | `true` | `false` | Blocks RFC1918 ranges (10.x, 172.16.x, 192.168.x) |
| `SSRF_DNS_FAIL_CLOSED` | `false` | `true` | Blocks requests on DNS resolution failure |

#### Migration Steps

**Step 1:** Identify if you connect to internal services

```bash
# Check your gateway configurations for internal URLs
grep -r "localhost\|127.0.0.1\|192.168\|10\.\|172\.(1[6-9]\|2[0-9]\|3[01])\." .env
```

**Step 2:** Update `.env` to restore previous behavior (if needed)

```bash
# Option A: Restore 0.9.x permissive defaults (NOT RECOMMENDED for production)
SSRF_ALLOW_LOCALHOST=true
SSRF_ALLOW_PRIVATE_NETWORKS=true
SSRF_DNS_FAIL_CLOSED=false

# Option B: Allow specific networks only (RECOMMENDED)
SSRF_ALLOW_LOCALHOST=false
SSRF_ALLOW_PRIVATE_NETWORKS=false
SSRF_ALLOWED_NETWORKS=192.168.1.0/24,10.0.0.0/8
SSRF_DNS_FAIL_CLOSED=true
```

**Step 3:** Test connectivity after upgrade

```bash
# Test MCP server connectivity
curl -X POST http://localhost:4444/mcp/sse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/list"}'
```

#### Troubleshooting

**Error:** `SSRF protection blocked request to localhost`

**Solution:** Add to `.env`:
```bash
SSRF_ALLOW_LOCALHOST=true
```

**Error:** `SSRF protection blocked request to private network`

**Solution:** Use `SSRF_ALLOWED_NETWORKS` for specific ranges:
```bash
SSRF_ALLOWED_NETWORKS=192.168.1.0/24,10.0.0.0/8
```

---

### 2. 🔌 Plugin Condition Evaluation (CRITICAL)

**Impact:** Plugin conditions now use hybrid AND/OR logic instead of pure OR.

#### What Changed

**Before (0.9.x):** All conditions evaluated with OR logic
```yaml
conditions:
  - team_id: "team-a"
  - user_email: "admin@example.com"
# Matched if: team_id="team-a" OR user_email="admin@example.com"
```

**After (1.0.0-RC3):** Conditions within same object use AND, different objects use OR
```yaml
conditions:
  - team_id: "team-a"
    user_email: "admin@example.com"  # AND within same object
  - team_id: "team-b"                # OR between objects
# Matched if: (team_id="team-a" AND user_email="admin@example.com") OR team_id="team-b"
```

#### Migration Steps

**Step 1:** Validate your plugin configurations

```bash
# Run validation script
python scripts/validate_plugin_conditions.py plugins/config.yaml
```

**Step 2:** Review validation output

The script identifies three patterns:

1. ✅ **Safe:** Single condition per object (no change needed)
2. ⚠️ **Review:** Multiple conditions in same object (now AND logic)
3. ❌ **Breaking:** Conditions that will change behavior

**Step 3:** Update plugin configurations

**Example Migration:**

```yaml
# OLD (0.9.x) - OR logic
plugins:
  - name: "TeamFilter"
    conditions:
      - team_id: "team-a"
      - team_id: "team-b"
      - user_email: "admin@example.com"
    # Matched: team-a OR team-b OR admin@example.com

# NEW (1.0.0-RC3) - Hybrid logic
plugins:
  - name: "TeamFilter"
    conditions:
      - team_id: "team-a"
      - team_id: "team-b"
      - user_email: "admin@example.com"
    # Still matches: team-a OR team-b OR admin@example.com (unchanged)

# BREAKING CASE - Multiple conditions in same object
# OLD (0.9.x)
conditions:
  - team_id: "team-a"
    user_email: "admin@example.com"
# Matched: team-a OR admin@example.com

# NEW (1.0.0-RC3)
conditions:
  - team_id: "team-a"
    user_email: "admin@example.com"
# Matches: team-a AND admin@example.com (BREAKING!)

# FIX: Split into separate objects
conditions:
  - team_id: "team-a"
  - user_email: "admin@example.com"
# Matches: team-a OR admin@example.com (restored)
```

**Step 4:** Test plugin behavior

```bash
# Start gateway with updated config
make dev

# Test plugin execution with different user contexts
curl -X POST http://localhost:4444/mcp/sse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/call","params":{"name":"test_tool"}}'
```

#### Reference

- **Full Migration Guide:** [MIGRATION-PLUGIN-CONDITIONS.md](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/architecture/MIGRATION-PLUGIN-CONDITIONS.md)
- **Validation Script:** `scripts/validate_plugin_conditions.py`
- **Issue:** #3930
- **PR:** #4078

---

### 3. 🗄️ Database Backend Removal (CRITICAL)

**Impact:** MySQL, MariaDB, and MongoDB support removed. Only PostgreSQL and SQLite supported.

#### What Changed

**Removed Backends:**
- ❌ MySQL
- ❌ MariaDB
- ❌ MongoDB

**Supported Backends:**
- ✅ PostgreSQL (recommended for production)
- ✅ SQLite (development/testing only)

#### Migration Steps

**If using PostgreSQL or SQLite:** No action required.

**If using MySQL/MariaDB:** Follow [MySQL to PostgreSQL Migration Guide](mysql-to-postgresql-migration.md)

**If using MongoDB:** MongoDB was experimental and not officially supported. Contact support for migration assistance.

---

### 4. 🔌 WebSocket & Reverse Proxy Gating (HIGH PRIORITY)

**Impact:** WebSocket relay and reverse proxy endpoints disabled by default.

#### What Changed

Two transport endpoints now require explicit enablement:

| Endpoint | 0.9.x Default | 1.0.0-RC3 Default | Feature Flag |
|----------|---------------|-------------------|--------------|
| WebSocket Relay | Enabled | **Disabled** | `MCPGATEWAY_WS_RELAY_ENABLED` |
| Reverse Proxy | Enabled | **Disabled** | `MCPGATEWAY_REVERSE_PROXY_ENABLED` |

#### Migration Steps

**Step 1:** Check if you use these endpoints

```bash
# Check for WebSocket connections
grep -r "ws://" .env config/

# Check for reverse proxy usage
grep -r "REVERSE_PROXY" .env config/
```

**Step 2:** Enable required endpoints in `.env`

```bash
# Enable WebSocket relay
MCPGATEWAY_WS_RELAY_ENABLED=true

# Enable reverse proxy
MCPGATEWAY_REVERSE_PROXY_ENABLED=true
```

**Step 3:** Verify RBAC permissions

WebSocket relay requires new permission:
```bash
# Check user has websocket.relay permission
curl -X GET "http://localhost:4444/users/me/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

#### RBAC Requirements

| Endpoint | Required Permission | Role |
|----------|-------------------|------|
| WebSocket Relay | `websocket.relay` | `developer` or higher |
| Reverse Proxy | `proxy.access` | `developer` or higher |

---

### 5. 🔑 OIDC ID Token Verification (HIGH PRIORITY)

**Impact:** SSO callbacks now cryptographically verify ID token signatures.

#### What Changed

**Before (0.9.x):** ID tokens accepted without signature verification

**After (1.0.0-RC3):** ID tokens verified using provider's JWKS endpoint

#### Migration Steps

**Step 1:** Verify JWKS endpoint configuration

Most providers auto-discover JWKS from `/.well-known/openid-configuration`:

```bash
# Test OIDC discovery
curl https://your-provider.com/.well-known/openid-configuration | jq .jwks_uri
```

**Step 2:** Configure JWKS URI (if auto-discovery fails)

```bash
# Generic OIDC provider
SSO_GENERIC_JWKS_URI=https://your-provider.com/.well-known/jwks.json

# Keycloak
SSO_GENERIC_JWKS_URI=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
```

**Step 3:** Test SSO login

```bash
# Initiate SSO flow
curl -L http://localhost:4444/auth/sso/login

# Check for JWKS verification errors in logs
docker logs mcpgateway 2>&1 | grep -i "jwks\|signature"
```

#### Troubleshooting

**Error:** `Failed to verify ID token signature`

**Causes:**
1. JWKS endpoint unreachable
2. Provider issuer mismatch
3. Clock skew between gateway and provider

**Solutions:**

```bash
# 1. Verify JWKS endpoint
curl -v https://your-provider.com/.well-known/jwks.json

# 2. Check issuer configuration
SSO_GENERIC_ISSUER=https://your-provider.com  # Must match token 'iss' claim

# 3. Sync system clock
ntpdate -s time.nist.gov  # Linux
sntp -sS time.nist.gov    # macOS
```

**Provider-Specific Notes:**

- **Keycloak:** Ensure `SSO_GENERIC_ISSUER` matches realm URL exactly
- **Azure AD:** Use v2.0 endpoint for OIDC compliance
- **Okta:** JWKS auto-discovery works out of box
- **Google:** JWKS auto-discovery works out of box

---

### 6. 👥 MAX_MEMBERS_PER_TEAM Behavior (HIGH PRIORITY)

**Impact:** New teams use dynamic limit from environment variable; existing teams retain baked-in values.

#### What Changed

**Before (0.9.x):** All teams stored `max_members` value in database

**After (1.0.0-RC3):**
- New teams: `max_members = NULL` (resolved from `MAX_MEMBERS_PER_TEAM` at runtime)
- Existing teams: Retain baked-in `max_members` value

#### Migration Steps

**Step 1:** Check current team limits

```bash
# List teams with their max_members values
curl -X GET "http://localhost:4444/teams" \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | {id, name, max_members}'
```

**Step 2:** Update teams to use dynamic limit (optional)

```bash
# Update specific team
curl -X PUT "http://localhost:4444/teams/<team_id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_members": null}'

# Bulk update all teams (requires platform_admin)
for team_id in $(curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/teams | jq -r '.[].id'); do
  curl -X PUT "http://localhost:4444/teams/$team_id" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"max_members": null}'
done
```

**Step 3:** Configure environment variable

```bash
# Set default limit for new teams
MAX_MEMBERS_PER_TEAM=50
```

#### Behavior Matrix

| Team State | `max_members` in DB | `MAX_MEMBERS_PER_TEAM` | Effective Limit |
|------------|---------------------|------------------------|-----------------|
| New team | `NULL` | `50` | 50 |
| Existing team | `100` | `50` | 100 (DB value) |
| Updated team | `NULL` | `50` | 50 (env value) |

---

### 7. 🔐 Token Scoping & Authorization (HIGH PRIORITY)

**Impact:** Multiple authorization checks tightened; default-deny for unmapped routes.

#### What Changed

**New Authorization Requirements:**

1. **Cancellation Authorization** (C-10): Requires `sessions.cancel` permission
2. **Token Scoping Default Deny** (C-15): Unmapped routes return 403 instead of allowing
3. **Session Authorization** (C-04, C-28): Tightened session access checks
4. **Resource Authorization** (C-07, C-11): Enhanced resource access validation
5. **Roots Authorization** (C-29): Added permission checks for roots endpoints

#### Migration Steps

**Step 1:** Review user permissions

```bash
# Check current user permissions
curl -X GET "http://localhost:4444/users/me/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 2:** Update role assignments (if needed)

```bash
# Grant sessions.cancel permission
curl -X POST "http://localhost:4444/teams/<team_id>/members/<user_id>/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "developer"}'
```

**Step 3:** Test critical workflows

```bash
# Test session cancellation
curl -X POST "http://localhost:4444/sessions/<session_id>/cancel" \
  -H "Authorization: Bearer $TOKEN"

# Test resource access
curl -X GET "http://localhost:4444/resources/<resource_id>" \
  -H "Authorization: Bearer $TOKEN"
```

#### New Permissions

| Permission | Description | Default Roles |
|------------|-------------|---------------|
| `sessions.cancel` | Cancel active sessions | `developer`, `team_admin`, `platform_admin` |
| `resources.read` | Read resource metadata | `viewer`, `developer`, `team_admin`, `platform_admin` |
| `roots.read` | List root resources | `viewer`, `developer`, `team_admin`, `platform_admin` |

#### Troubleshooting

**Error:** `403 Forbidden - Insufficient permissions`

**Solution:** Check required permission and update user role:

```bash
# Check error details
curl -v -X POST "http://localhost:4444/sessions/<session_id>/cancel" \
  -H "Authorization: Bearer $TOKEN" 2>&1 | grep -i "permission"

# Grant required role
curl -X POST "http://localhost:4444/teams/<team_id>/members/<user_id>/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "developer"}'
```

---

### 8. 📦 Helm Chart Changes (HIGH PRIORITY)

**Impact:** MinIO disabled by default; PostgreSQL upgrade safety defaults changed.

#### What Changed

**MinIO:**
- Default: `minio.enabled=false`
- Impact: Object storage disabled unless explicitly enabled

**PostgreSQL:**
- Single-writer upgrade safety defaults
- BETA-2 upgrade requires workaround

#### Migration Steps

**Step 1:** Check if you use MinIO

```bash
# Check Helm values
helm get values mcp-stack -n mcp-production | grep -i minio
```

**Step 2:** Enable MinIO (if needed)

```bash
# Update values.yaml
cat >> values.yaml <<EOF
minio:
  enabled: true
  persistence:
    size: 10Gi
EOF

# Upgrade release
helm upgrade mcp-stack charts/mcp-stack -n mcp-production -f values.yaml
```

**Step 3:** Upgrade from BETA-2 (if applicable)

```bash
# BETA-2 to RC3 requires special handling
# See: https://github.com/your-org/mcp-context-forge/issues/3684

# 1. Backup database
kubectl exec -n mcp-production postgres-0 -- pg_dump -U admin mcpgateway > backup.sql

# 2. Apply upgrade with workaround
helm upgrade mcp-stack charts/mcp-stack -n mcp-production \
  --set postgresql.primary.persistence.enabled=true \
  --set postgresql.primary.persistence.existingClaim=postgres-data

# 3. Verify upgrade
kubectl get pods -n mcp-production
```

---

## Post-Upgrade Validation

### 1. Verify Gateway Health

```bash
# Check health endpoint
curl http://localhost:4444/health

# Expected response:
# {"status": "healthy", "version": "1.0.0-RC3"}
```

### 2. Test Authentication

```bash
# Test JWT authentication
curl -X GET "http://localhost:4444/users/me" \
  -H "Authorization: Bearer $TOKEN"

# Test SSO login (if configured)
curl -L http://localhost:4444/auth/sso/login
```

### 3. Test MCP Connectivity

```bash
# List available tools
curl -X POST http://localhost:4444/mcp/sse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/list"}'
```

### 4. Verify Plugin Execution

```bash
# Check plugin status
curl -X GET "http://localhost:4444/plugins" \
  -H "Authorization: Bearer $TOKEN"

# Test plugin execution
curl -X POST http://localhost:4444/mcp/sse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/call","params":{"name":"test_tool"}}'
```

### 5. Check Logs for Errors

```bash
# Docker
docker logs mcpgateway 2>&1 | grep -i "error\|warning"

# Kubernetes
kubectl logs -n mcp-production deployment/mcpgateway | grep -i "error\|warning"

# Local
tail -f logs/mcpgateway.log | grep -i "error\|warning"
```

---

## Rollback Procedure

If you encounter critical issues after upgrade:

### 1. Stop Gateway

```bash
# Docker
docker-compose down

# Kubernetes
kubectl scale deployment/mcpgateway --replicas=0 -n mcp-production

# Local
pkill -f mcpgateway
```

### 2. Restore Database Backup

```bash
# SQLite
cp mcp.db.backup mcp.db

# PostgreSQL
psql -U admin -d mcpgateway < backup.sql
```

### 3. Revert to Previous Version

```bash
# Docker
docker-compose down
git checkout v0.9.x
docker-compose up -d

# Kubernetes
helm rollback mcp-stack -n mcp-production

# Local
git checkout v0.9.x
make install-dev
make dev
```

### 4. Restore Configuration

```bash
# Restore previous .env
cp .env.backup .env

# Restore previous plugin config
cp plugins/config.yaml.backup plugins/config.yaml
```

---

## Getting Help

### Documentation

- **CHANGELOG:** [CHANGELOG.md](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md)
- **Configuration Reference:** [configuration.md](configuration.md)
- **RBAC Guide:** [rbac.md](rbac.md)
- **Plugin Migration:** [MIGRATION-PLUGIN-CONDITIONS.md](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/architecture/MIGRATION-PLUGIN-CONDITIONS.md)
- **MySQL Migration:** [mysql-to-postgresql-migration.md](mysql-to-postgresql-migration.md)

### Support Channels

- **GitHub Issues:** https://github.com/your-org/mcp-context-forge/issues
- **Discussions:** https://github.com/your-org/mcp-context-forge/discussions
- **Discord:** https://discord.gg/your-server

### Reporting Issues

When reporting upgrade issues, include:

1. Previous version (e.g., 0.9.5)
2. Target version (1.0.0-RC3)
3. Deployment method (Docker, Kubernetes, local)
4. Database backend (PostgreSQL, SQLite)
5. Relevant logs (sanitized)
6. Configuration (sanitized `.env`)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-RC3 | 2026-04-14 | Initial release |

---

**Next Steps:**

1. ✅ Complete pre-upgrade checklist
2. ✅ Review all breaking changes
3. ✅ Update configuration files
4. ✅ Test in non-production environment
5. ✅ Perform production upgrade
6. ✅ Validate post-upgrade
7. ✅ Monitor for issues

**Estimated Total Migration Time:** 2-4 hours (depending on complexity)
