# Issue #5402: Approach Comparison - Domain-Based vs vault_credential_alias

## Overview

This document compares two approaches for vault direct integration:
1. **Approach A**: `vault_credential_alias` field (database storage)
2. **Approach B**: Domain-based lookup (stateless, current final design)

---

## Approach A: vault_credential_alias Field

### Description

Gateway stores a `vault_credential_alias` field in the database that explicitly names which vault credential to use.

### Architecture

```python
# Database Schema
class Gateway(Base):
    vault_credential_alias: Mapped[Optional[str]] = mapped_column(
        String(255), 
        nullable=True,
        index=True
    )

# Example Gateway
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal"  # Stored in DB
}

# Plugin Logic
vault_alias = gateway.vault_credential_alias  # Read from DB
credential = vault.resolve_credential(
    owner="user@example.com",
    alias="github-personal",  # From gateway config
    vault_token="vault_token_abc"
)
```

### Benefits

✅ **Explicit credential naming**
- Each gateway explicitly declares which credential it needs
- No ambiguity about which credential to use
- Clear intent in gateway configuration

✅ **Per-gateway flexibility**
- Different gateways can use different credentials for same domain
- Example: `github-work` vs `github-personal` for different GitHub instances

✅ **User control**
- Users choose their own credential names
- No forced naming conventions

✅ **Database validation**
- Schema enforces max length (255 chars)
- Indexed for fast lookup
- Can add foreign key constraints if needed

### Drawbacks

❌ **Database schema change required**
- Alembic migration needed
- Database column added to gateways table
- Potential migration issues in production

❌ **Configuration overhead**
- Admin must set `vault_credential_alias` for each gateway
- Another field to manage in gateway config
- Coordination between gateway config and vault credential names

❌ **Agent complexity**
- Agent needs to maintain user config file (`~/.agent/vault_credentials.yaml`)
- Maps domain → credential_name for each user
- Config file can get out of sync with vault

❌ **Not truly stateless**
- Credential alias stored in database
- Requires database read for every request

---

## Approach B: Domain-Based Lookup (Current Final Design)

### Description

Gateway URL is parsed to extract domain, which is used directly to lookup credentials in vault. No database storage needed.

### Architecture

```python
# Computed Property (No DB Storage)
class Gateway(Base):
    @hybrid_property
    def required_domain(self) -> str:
        """Extract domain from URL."""
        hostname = urlparse(self.url).hostname or ""
        # Remove api., www. prefixes
        for prefix in ['api.', 'www.']:
            if hostname.startswith(prefix):
                hostname = hostname[len(prefix):]
        return hostname

# Example Gateway
{
  "name": "GitHub MCP",
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"  # Computed, not stored
}

# Plugin Logic
domain = gateway.required_domain  # Computed from URL
credential = vault.resolve_credential_by_domain(
    owner="user@example.com",
    domain="github.com",  # Derived from URL
    vault_token="vault_token_abc"
)
```

### Benefits

✅ **Zero database changes**
- No Alembic migration needed
- No new columns added
- No production migration risk

✅ **Truly stateless**
- Domain computed on-the-fly from URL
- No database storage required
- Scales infinitely without DB growth

✅ **Zero agent configuration**
- No agent config file needed
- Vault manages domain → credential mapping
- Simpler agent implementation

✅ **Automatic domain extraction**
- Domain derived from gateway URL automatically
- No manual configuration needed
- Consistent with URL as source of truth

✅ **Standardized approach**
- Industry standard: credentials indexed by domain
- Similar to OAuth/OIDC patterns
- Easier to understand and maintain

✅ **Simpler vault management**
- Vault credentials organized by domain
- Natural grouping (all github.com credentials together)
- Easier to audit and manage

### Drawbacks

❌ **Less per-gateway flexibility**
- All gateways for same domain use same credential
- Cannot have `github-work` vs `github-personal` for different GitHub gateways
- **Mitigation**: Use different user accounts or vault namespaces

❌ **Domain extraction logic**
- Requires URL parsing and prefix stripping
- Edge cases: subdomains, non-standard URLs
- **Mitigation**: Well-tested extraction logic, clear documentation

❌ **Vault API requirement**
- Vault-proxy must support `resolve_credential_by_domain` endpoint
- New API endpoint needed
- **Mitigation**: Vault-proxy team implements endpoint (straightforward)

---

## Side-by-Side Comparison

| Aspect | vault_credential_alias (A) | Domain-Based (B) |
|--------|---------------------------|------------------|
| **Database Changes** | ❌ Yes (new column) | ✅ No (computed property) |
| **Alembic Migration** | ❌ Required | ✅ Not needed |
| **Agent Config File** | ❌ Required (`~/.agent/vault_credentials.yaml`) | ✅ Not needed |
| **Stateless** | ❌ No (DB storage) | ✅ Yes (computed) |
| **Configuration Points** | 2 (gateway + agent config) | 1 (vault only) |
| **Per-Gateway Flexibility** | ✅ High (different creds per gateway) | ⚠️ Medium (same domain = same cred) |
| **User Credential Naming** | ✅ User chooses names | ⚠️ Standardized by domain |
| **Vault Organization** | ⚠️ By user-chosen names | ✅ By domain (natural grouping) |
| **Production Risk** | ⚠️ Medium (DB migration) | ✅ Low (no DB changes) |
| **Agent Complexity** | ⚠️ Higher (config file) | ✅ Lower (no config) |
| **Vault API Changes** | ✅ None (existing API) | ⚠️ New endpoint needed |
| **Industry Standard** | ⚠️ Custom approach | ✅ Standard (domain-based) |
| **Onboarding** | ⚠️ More steps (config file) | ✅ Fewer steps (just vault) |
| **Debugging** | ⚠️ Check gateway + agent config | ✅ Check vault only |

---

## Use Case Analysis

### Use Case 1: Single User, Multiple GitHub Instances

**Scenario**: User needs to access both github.com and github.ibm.com

**Approach A (vault_credential_alias)**:
```json
// Gateway 1
{
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-personal"
}

// Gateway 2
{
  "url": "https://github.ibm.com/mcp/",
  "vault_credential_alias": "github-work"
}

// Agent config
credentials:
  github.com: github-personal
  github.ibm.com: github-work
```
✅ Works well - different credentials per instance

**Approach B (Domain-Based)**:
```json
// Gateway 1
{
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"  // Computed
}

// Gateway 2
{
  "url": "https://github.ibm.com/mcp/",
  "required_domain": "github.ibm.com"  // Computed
}

// Vault (indexed by domain)
github.com → user's personal credential
github.ibm.com → user's work credential
```
✅ Works well - different domains = different credentials

**Winner**: **TIE** - Both handle this well

---

### Use Case 2: Multiple Gateways, Same Domain, Different Credentials

**Scenario**: User has two GitHub.com gateways (dev vs prod) needing different credentials

**Approach A (vault_credential_alias)**:
```json
// Gateway 1 (dev)
{
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-dev"
}

// Gateway 2 (prod)
{
  "url": "https://api.github.com/mcp/",
  "vault_credential_alias": "github-prod"
}
```
✅ Works - different aliases for same domain

**Approach B (Domain-Based)**:
```json
// Gateway 1 (dev)
{
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"
}

// Gateway 2 (prod)
{
  "url": "https://api.github.com/mcp/",
  "required_domain": "github.com"
}
```
❌ Problem - both resolve to same credential

**Workaround for B**:
- Use different vault namespaces/users
- Use subdomain URLs if available
- Accept that same domain = same credential (most common case)

**Winner**: **Approach A** - Better flexibility for this edge case

---

### Use Case 3: Large Organization, 100+ Gateways

**Scenario**: Enterprise with many MCP servers

**Approach A (vault_credential_alias)**:
- 100 gateway configs to set `vault_credential_alias`
- 100 entries in agent config file per user
- Database stores 100 credential aliases
- Admin overhead: High

**Approach B (Domain-Based)**:
- 0 gateway configs needed (domain auto-extracted)
- 0 agent config entries needed
- Database stores 0 additional data
- Admin overhead: Low

**Winner**: **Approach B** - Much better scalability

---

### Use Case 4: New User Onboarding

**Scenario**: New user needs to start using the system

**Approach A (vault_credential_alias)**:
1. Create vault credentials with chosen names
2. Create `~/.agent/vault_credentials.yaml` file
3. Map each domain to credential name
4. Test each gateway
5. Debug config file if issues

**Approach B (Domain-Based)**:
1. Create vault credentials indexed by domain
2. Start using (no config file needed)

**Winner**: **Approach B** - Simpler onboarding

---

## Architect Decision Factors

### Choose Approach A (vault_credential_alias) if:

1. **Per-gateway credential flexibility is critical**
   - Need different credentials for same domain
   - Example: dev vs prod environments on same domain

2. **User control over naming is important**
   - Users want to choose their own credential names
   - Organizational naming conventions exist

3. **Vault API changes are blocked**
   - Cannot add `resolve_credential_by_domain` endpoint
   - Must use existing vault API

4. **Database migrations are acceptable**
   - Have robust migration process
   - Low production risk tolerance for DB changes

### Choose Approach B (Domain-Based) if:

1. **Stateless architecture is priority**
   - Want to avoid database storage
   - Computed properties preferred

2. **Simplicity is critical**
   - Minimize configuration points
   - Reduce agent complexity
   - Easier user onboarding

3. **Scalability is important**
   - Many gateways (100+)
   - Want to minimize admin overhead

4. **Industry standards matter**
   - Domain-based credential management is standard
   - OAuth/OIDC-like patterns

5. **Production risk aversion**
   - Avoid database migrations
   - Minimize deployment complexity

---

## Recommendation

**Approach B (Domain-Based Lookup)** is recommended for most scenarios because:

1. ✅ **Zero database changes** - Lower production risk
2. ✅ **Simpler architecture** - Fewer moving parts
3. ✅ **Better scalability** - O(1) config per gateway
4. ✅ **Industry standard** - Domain-based credential management
5. ✅ **Easier onboarding** - No agent config file needed

**Exception**: Choose Approach A if per-gateway credential flexibility for the same domain is a hard requirement (rare in practice).

---

## Current Status

**Final Design Uses**: **Approach B (Domain-Based Lookup)**

**Rationale**:
- Architect approved stateless approach (per ISSUE_5402_README.md)
- Zero database changes requirement
- Simpler agent implementation
- Better long-term maintainability

**Documents**:
- ISSUE_5402_FINAL_DESIGN.md - Implements Approach B
- ISSUE_5402_PLUGIN_ARCHITECTURE.md - Implements Approach B
- ISSUE_5402_VALIDATION.md - Validates Approach B meets all requirements

---

## Migration from A to B

If you started with Approach A and want to migrate to B:

1. **Vault Migration**:
   - Re-index credentials by domain instead of alias
   - Example: `github-personal` → indexed under `github.com`

2. **Remove Database Field**:
   - Alembic migration to drop `vault_credential_alias` column
   - Update Pydantic schemas

3. **Remove Agent Config**:
   - Delete `~/.agent/vault_credentials.yaml` files
   - Update agent code to remove config loading

4. **Update Plugin**:
   - Change from `gateway.vault_credential_alias` to `gateway.required_domain`
   - Update vault client to use `resolve_credential_by_domain`

**Effort**: 2-3 days (vault re-indexing + code changes + testing)

---

## Conclusion

Both approaches solve the core problem (eliminate tag-based system), but **Approach B (Domain-Based)** is simpler, more scalable, and lower risk for most organizations.

**Final Design**: Approach B is implemented in ISSUE_5402_FINAL_DESIGN.md