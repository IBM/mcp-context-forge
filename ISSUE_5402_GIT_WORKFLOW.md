# Issue #5402: Git Workflow and Branch Strategy

**Recommended Git workflow for implementing the vault plugin direct integration feature**

---

## 🌿 Recommended Branch Structure

### Main Development Branch

```
feature/5402-vault-direct-integration
```

**Naming Convention**: `feature/{issue-number}-{short-description}`

### Sub-Feature Branches (Optional for Large Teams)

For parallel development by multiple developers:

```
feature/5402-vault-direct-integration-database
feature/5402-vault-direct-integration-client
feature/5402-vault-direct-integration-plugin
feature/5402-vault-direct-integration-tests
feature/5402-vault-direct-integration-docs
```

---

## 📋 Branch Strategy Options

### Option 1: Single Feature Branch (Recommended for Small Teams)

**Best for**: 1-2 developers, sequential implementation

```
main
  └── feature/5402-vault-direct-integration
        ├── commit: Add database migration for vault_credential_alias
        ├── commit: Implement VaultProxyClient class
        ├── commit: Refactor VaultPlugin for dual-mode support
        ├── commit: Update gateway service CRUD operations
        ├── commit: Simplify agent runtime vault handling
        ├── commit: Add comprehensive test suite
        ├── commit: Update documentation and examples
        └── PR → main
```

**Advantages**:
- ✅ Simple, linear history
- ✅ Easy to review as a cohesive unit
- ✅ No merge conflicts between sub-features

**Commands**:
```bash
# Create and switch to feature branch
git checkout -b feature/5402-vault-direct-integration

# Make changes and commit incrementally
git add .
git commit -m "feat(vault): add database migration for vault_credential_alias

- Add vault_credential_alias column to gateways table
- Create idempotent Alembic migration
- Update DbGateway model and Pydantic schemas

Relates to #5402"

# Push to remote
git push -u origin feature/5402-vault-direct-integration

# Create PR when ready
gh pr create --title "feat: Vault plugin direct integration" --body "Closes #5402"
```

---

### Option 2: Multi-Branch Strategy (Recommended for Large Teams)

**Best for**: 3+ developers, parallel implementation

```
main
  └── feature/5402-vault-direct-integration (integration branch)
        ├── feature/5402-vault-direct-integration-database
        │     └── PR → feature/5402-vault-direct-integration
        ├── feature/5402-vault-direct-integration-client
        │     └── PR → feature/5402-vault-direct-integration
        ├── feature/5402-vault-direct-integration-plugin
        │     └── PR → feature/5402-vault-direct-integration
        └── feature/5402-vault-direct-integration-tests
              └── PR → feature/5402-vault-direct-integration
        
        └── Final PR → main
```

**Advantages**:
- ✅ Parallel development
- ✅ Smaller, focused PRs
- ✅ Independent code reviews

**Commands**:
```bash
# Create integration branch
git checkout -b feature/5402-vault-direct-integration

# Developer 1: Database work
git checkout -b feature/5402-vault-direct-integration-database feature/5402-vault-direct-integration
# ... make changes ...
git push -u origin feature/5402-vault-direct-integration-database
gh pr create --base feature/5402-vault-direct-integration

# Developer 2: Client work
git checkout -b feature/5402-vault-direct-integration-client feature/5402-vault-direct-integration
# ... make changes ...
git push -u origin feature/5402-vault-direct-integration-client
gh pr create --base feature/5402-vault-direct-integration

# After all sub-PRs merged, create final PR to main
git checkout feature/5402-vault-direct-integration
gh pr create --base main --title "feat: Vault plugin direct integration" --body "Closes #5402"
```

---

### Option 3: Incremental PR Strategy (Recommended for Continuous Delivery)

**Best for**: Gradual rollout, feature flags enabled

```
main
  ├── PR #1: feat(vault): add database schema for vault_credential_alias
  ├── PR #2: feat(vault): implement VaultProxyClient
  ├── PR #3: feat(vault): add dual-mode support to VaultPlugin
  ├── PR #4: feat(vault): update gateway service
  ├── PR #5: feat(vault): simplify agent runtime
  ├── PR #6: test(vault): add comprehensive test suite
  └── PR #7: docs(vault): update documentation
```

**Advantages**:
- ✅ Continuous integration
- ✅ Smaller, easier-to-review PRs
- ✅ Can deploy incrementally with feature flags

**Commands**:
```bash
# PR #1: Database
git checkout -b feature/5402-database-schema
# ... implement database changes ...
git push -u origin feature/5402-database-schema
gh pr create --title "feat(vault): add database schema for vault_credential_alias" --body "Part 1 of #5402"

# After PR #1 merged, start PR #2
git checkout main
git pull
git checkout -b feature/5402-vault-client
# ... implement vault client ...
git push -u origin feature/5402-vault-client
gh pr create --title "feat(vault): implement VaultProxyClient" --body "Part 2 of #5402"

# Continue for each component...
```

---

## 📝 Commit Message Convention

Follow **Conventional Commits** format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactoring
- `test`: Adding tests
- `docs`: Documentation changes
- `chore`: Maintenance tasks

### Examples:

```bash
# Database migration
git commit -m "feat(vault): add vault_credential_alias to gateways table

- Add nullable vault_credential_alias column (String 255)
- Create index for performance
- Update DbGateway model and Pydantic schemas
- Add idempotent Alembic migration

Relates to #5402"

# Vault client implementation
git commit -m "feat(vault): implement VaultProxyClient for direct integration

- Add VaultProxyClient class with wrap/unwrap methods
- Implement custom exceptions (NotFound, Connection, Timeout)
- Add comprehensive error handling
- Support all auth types (PAT, OAuth2, JWT, Custom)

Relates to #5402"

# Plugin refactoring
git commit -m "refactor(vault): add dual-mode support to VaultPlugin

- Implement _process_direct_mode() for vault-proxy integration
- Keep _process_legacy_tag_mode() for backward compatibility
- Add mode routing based on VAULT_DIRECT_RESOLUTION_ENABLED
- Inject headers based on vault metadata (authType, headerName)

Relates to #5402"

# Tests
git commit -m "test(vault): add comprehensive test suite for direct mode

- Add VaultProxyClient unit tests (wrap, unwrap, errors)
- Add VaultPlugin direct mode tests (PAT, OAuth2, errors)
- Add legacy compatibility tests
- Add end-to-end integration tests

Relates to #5402"

# Documentation
git commit -m "docs(vault): update documentation for direct integration

- Add implementation plan with code samples
- Add architecture diagrams and flowcharts
- Update vault plugin README
- Add migration guide from legacy to direct mode

Closes #5402"
```

---

## 🔄 Workflow Steps

### Step 1: Create Feature Branch

```bash
# Ensure main is up to date
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/5402-vault-direct-integration

# Push to remote to create tracking branch
git push -u origin feature/5402-vault-direct-integration
```

### Step 2: Implement Changes Incrementally

```bash
# Phase 1: Database
# ... make changes ...
git add mcpgateway/db.py mcpgateway/schemas.py mcpgateway/alembic/versions/
git commit -m "feat(vault): add database schema for vault_credential_alias"

# Phase 2: Vault Client
# ... make changes ...
git add plugins/vault/vault_client.py
git commit -m "feat(vault): implement VaultProxyClient"

# Phase 3: Plugin Refactoring
# ... make changes ...
git add plugins/vault/vault_plugin.py
git commit -m "refactor(vault): add dual-mode support to VaultPlugin"

# Continue for each phase...
```

### Step 3: Keep Branch Updated

```bash
# Regularly sync with main to avoid conflicts
git checkout main
git pull origin main
git checkout feature/5402-vault-direct-integration
git merge main

# Or use rebase for cleaner history
git rebase main

# Push updates
git push origin feature/5402-vault-direct-integration
```

### Step 4: Create Pull Request

```bash
# Using GitHub CLI
gh pr create \
  --title "feat: Vault plugin direct integration" \
  --body "$(cat <<EOF
## Summary
Implements direct vault-proxy integration in the vault plugin, eliminating the fragile tag-based credential injection system.

## Changes
- ✅ Add vault_credential_alias to gateways table
- ✅ Implement VaultProxyClient for wrap/unwrap operations
- ✅ Refactor VaultPlugin with dual-mode support (direct + legacy)
- ✅ Update gateway service CRUD operations
- ✅ Simplify agent runtime (remove vault resolution)
- ✅ Add comprehensive test suite (unit + integration)
- ✅ Update documentation with diagrams and examples

## Testing
- [x] Unit tests pass (vault client, plugin)
- [x] Integration tests pass (end-to-end)
- [x] Manual testing completed
- [x] Backward compatibility verified

## Migration
- Feature flag: VAULT_DIRECT_RESOLUTION_ENABLED (default: false)
- Legacy mode preserved for backward compatibility
- Migration guide included in documentation

## Related
Closes #5402

## Checklist
- [x] Code follows project style guidelines
- [x] Tests added/updated
- [x] Documentation updated
- [x] No breaking changes (backward compatible)
- [x] Signed commits (DCO)
EOF
)" \
  --label "enhancement" \
  --label "vault"

# Or manually on GitHub
git push origin feature/5402-vault-direct-integration
# Then create PR via GitHub UI
```

### Step 5: Address Review Comments

```bash
# Make requested changes
git add .
git commit -m "refactor: address PR review comments

- Improve error messages
- Add input validation
- Fix edge case in unwrap logic"

# Push updates
git push origin feature/5402-vault-direct-integration
```

### Step 6: Merge to Main

```bash
# After PR approval, merge via GitHub UI or CLI
gh pr merge --squash --delete-branch

# Or merge locally
git checkout main
git pull origin main
git merge --no-ff feature/5402-vault-direct-integration
git push origin main
git branch -d feature/5402-vault-direct-integration
git push origin --delete feature/5402-vault-direct-integration
```

---

## 🏷️ Tagging Strategy

After merging to main, create a tag for the release:

```bash
# Create annotated tag
git tag -a v1.5.0 -m "Release v1.5.0: Vault plugin direct integration

- Add vault_credential_alias to gateways
- Implement VaultProxyClient
- Add dual-mode support to VaultPlugin
- Comprehensive test coverage
- Full backward compatibility

Closes #5402"

# Push tag
git push origin v1.5.0
```

---

## 🔍 Branch Protection Rules

Recommended settings for `main` branch:

```yaml
Branch Protection Rules:
  - Require pull request reviews (1+ approvals)
  - Require status checks to pass:
    - CI/CD pipeline
    - Unit tests
    - Integration tests
    - Linting (ruff, pylint)
    - Type checking (mypy)
  - Require signed commits
  - Require linear history (optional)
  - Include administrators
```

---

## 📊 Git History Visualization

### Good History (Recommended):

```
* feat: Vault plugin direct integration (#1234)
|   - Add vault_credential_alias to gateways
|   - Implement VaultProxyClient
|   - Add dual-mode support
|   - Comprehensive tests
|   Closes #5402
|
* fix: Resolve SSO token refresh issue (#1233)
|
* feat: Add A2A agent metrics (#1232)
```

### Avoid (Too Granular):

```
* docs: fix typo in README
* fix: remove debug print
* refactor: rename variable
* test: add missing assertion
* feat: implement vault client
```

**Tip**: Use `git rebase -i` to squash related commits before creating PR.

---

## 🚀 Quick Reference Commands

```bash
# Start work
git checkout -b feature/5402-vault-direct-integration

# Save work
git add .
git commit -m "feat(vault): implement feature X"
git push origin feature/5402-vault-direct-integration

# Update from main
git fetch origin
git rebase origin/main

# Create PR
gh pr create --title "feat: Vault plugin direct integration" --body "Closes #5402"

# After merge, cleanup
git checkout main
git pull
git branch -d feature/5402-vault-direct-integration
```

---

## 📚 Additional Resources

- **Conventional Commits**: https://www.conventionalcommits.org/
- **GitHub Flow**: https://guides.github.com/introduction/flow/
- **Git Best Practices**: https://git-scm.com/book/en/v2/Distributed-Git-Contributing-to-a-Project

---

**Recommended Branch**: `feature/5402-vault-direct-integration`  
**Merge Strategy**: Squash and merge (for clean history)  
**Review Required**: Yes (1+ approvals)  
**CI/CD**: Must pass all checks before merge