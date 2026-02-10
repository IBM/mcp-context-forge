# ADR-0036: Bootstrap Custom Roles from Configuration File

- *Status:* Accepted
- *Date:* 2026-01-25
- *Deciders:* Core Engineering Team

## Context

Organizations deploying MCP Gateway need to pre-configure custom RBAC roles that match their organizational structure and access policies. Currently, the only way to create custom roles is through the Admin API after deployment, which creates additional manual steps and potential security gaps during the initial deployment window.

Common use cases requiring custom roles:

- **Data Analyst role**: Read-only access to tools and resources for data analysis workflows
- **Auditor role**: Global read access for compliance and security audits
- **CI/CD role**: Limited permissions for automation pipelines
- **Operator role**: Permissions to manage servers without full admin access

## Decision

We will allow administrators to define custom roles in a JSON configuration file that is automatically loaded during database bootstrap. The feature is:

1. **Disabled by default** - Requires explicit opt-in via `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED=true`
2. **File-based configuration** - Roles defined in a JSON file specified by `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE`
3. **Validated on load** - JSON structure is validated; invalid entries are skipped with warnings
4. **Idempotent** - Existing roles are detected and skipped; safe to run multiple times

### Configuration Schema

```json
[
  {
    "name": "role_name",          // Required: unique identifier
    "scope": "team|global",       // Required: access scope
    "permissions": ["..."],       // Required: array of permission strings
    "description": "...",         // Optional: human-readable description
    "is_system_role": true|false  // Optional: prevent user modification
  }
]
```

### File Resolution

When a relative path is provided:

1. Check current working directory
2. Check project root (`mcpgateway/bootstrap_db.py` → `parent.parent`)

### Error Handling

| Error Case | Behavior |
|------------|----------|
| File not found | Log warning, continue with default roles |
| Invalid JSON | Log error, continue with default roles |
| JSON is not an array | Log error, continue with default roles |
| Entry missing required keys | Skip entry with warning, process valid entries |
| Entry is not a dict | Skip entry with warning, process valid entries |

## Consequences

### Positive

- ✅ Organizations can pre-configure roles matching their access policies
- ✅ Eliminates manual role creation after deployment
- ✅ Supports GitOps workflows (roles defined in version control)
- ✅ Reduces security gap during initial deployment
- ✅ Graceful degradation on configuration errors

### Negative

- ❌ Adds complexity to bootstrap process
- ❌ Requires understanding of permission strings
- ❌ Configuration errors may go unnoticed if not monitoring logs

### Neutral

- 🔄 Roles can still be created/modified via Admin API after bootstrap
- 🔄 Feature is opt-in; no impact on existing deployments

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Helm values only** | Not all deployments use Helm; need container-agnostic solution |
| **Environment variable per role** | Complex syntax for arrays of permissions; hard to manage |
| **Database seed scripts** | Requires DB access; doesn't integrate with bootstrap flow |
| **Admin API on startup** | Requires API to be available; chicken-and-egg problem |

## Security Considerations

1. **File access**: Configuration file should be mounted read-only
2. **Validation**: All entries are validated before processing
3. **No secrets**: Role definitions don't contain sensitive data
4. **Audit trail**: All role creation is logged

## Implementation

- `mcpgateway/config.py`: Add configuration settings
- `mcpgateway/bootstrap_db.py`: Add role loading and validation logic
- `tests/unit/mcpgateway/test_bootstrap_db.py`: Comprehensive test coverage

## Related

- [RBAC Configuration](../../manage/rbac.md) - End-user documentation
- Issue #2187 - Feature request
- PR #2188 - Implementation
