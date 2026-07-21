# PR #5737 Review Response Plan

**PR:** [refactor: remove Rust build infrastructure and stdio wrapper capability](https://github.com/IBM/mcp-context-forge/pull/5737)
**Status:** Draft (marked after review feedback)
**Reviewer:** lucarlig
**Review Date:** July 21, 2026

---

## Executive Summary

The PR successfully removes the core Rust workspace (~15k lines), but the review identified **4 blocking build/test failures** and **significant remaining Rust infrastructure** that must be cleaned up before merge. This plan provides a comprehensive roadmap to address all review comments.

---

## 🚨 BLOCKING ISSUES (Must Fix Before Merge)

### ✅ 1. License Checker Failure - FIXED

**Problem:**
- `scripts/license_checker.py` still enables Rust dependency scanning by default
- Requires `cargo-license` even with zero Cargo manifests
- Currently causing license check failures

**Solution:**
```python
# In scripts/license_checker.py
# Change default behavior to skip Rust scanning when no Cargo.toml exists

def check_rust_dependencies():
    cargo_toml = Path("Cargo.toml")
    if not cargo_toml.exists():
        logger.info("No Cargo.toml found, skipping Rust dependency checks")
        return True  # Pass check when no Rust workspace exists

    # Existing cargo-license logic...
```

**Verification:**
```bash
python scripts/license_checker.py
# Should pass without requiring cargo-license
```

---

### ✅ 2. Version Bumping Broken - FIXED

**Problem:**
- `.bumpversion.cfg` still references `[bumpversion:file:Cargo.toml]`
- `bump2version --dry-run patch` fails with `FileNotFoundError: Cargo.toml`

**Solution:**
```ini
# In .bumpversion.cfg
# Remove the following section:
[bumpversion:file:Cargo.toml]
search = version = "{current_version}"
replace = version = "{new_version}"
```

**Verification:**
```bash
bump2version --dry-run patch
# Should complete without errors
```

---

### ✅ 3. Package Build Failure - FIXED

**Problem:**
- `MANIFEST.in` pruning removed required non-Rust Admin UI assets
- Missing `mcpgateway/admin_ui/index.js` from sdist
- Package build currently fails

**Solution:**
```manifest
# In MANIFEST.in
# Restore Admin UI assets that were incorrectly pruned:
recursive-include mcpgateway/admin_ui *.js *.css *.html
include mcpgateway/admin_ui/index.js
include mcpgateway/static/bundle-*.js
include mcpgateway/static/chunk-*.js

# Keep existing prunes for actual Rust artifacts:
prune crates/
prune supply-chain/
global-exclude Cargo.toml Cargo.lock
```

**Verification:**
```bash
python -m build --sdist
tar -tzf dist/mcp-contextforge-gateway-*.tar.gz | grep admin_ui/index.js
# Should find the file in the tarball
```

---

### ✅ 4. Pre-commit Failure - FIXED

**Problem:**
- `.secrets.baseline` still contains Cargo/crate entries
- Causing pre-commit check failures

**Solution:**
```bash
# Regenerate secrets baseline without Cargo/crate references
make detect-secrets-scan

# Or manually edit .secrets.baseline to remove entries like:
# - "filename": "Cargo.toml"
# - "filename": "Cargo.lock"
# - "filename": "crates/*/Cargo.toml"
```

**Verification:**
```bash
pre-commit run --all-files
# Should pass all checks
```

---

## 🧹 REMAINING RUST INFRASTRUCTURE CLEANUP

### Category 1: Build & Docker Configuration

#### Files to Update:

**`.dockerignore`**
```diff
# Remove re-includes of deleted Rust server paths
- !crates/mcp_server/
- !crates/wrapper/
```

**`scripts/pre-commit/check_rust_workspace.py`**
- **Action:** Delete entire file (no longer needed)
- **Verification:** Remove from `.pre-commit-config.yaml` if referenced

---

### Category 2: Scripts & Tooling

#### `scripts/compliance_matrix.py`

**Problem:** Still defines `rust_edge` and `rust_full` modes

**Solution:**
```python
# Remove Rust mode definitions:
MODES = {
    "python_full": {...},
    "python_edge": {...},
    # DELETE: "rust_full": {...},
    # DELETE: "rust_edge": {...},
}
```

#### Performance Compose Generation

**Problem:** Targets deleted `mcp-servers/rust/` paths

**Files to check:**
- `scripts/generate_perf_compose.py` (or similar)
- Any Makefile targets that reference `mcp-servers/rust/`

**Solution:** Remove references to `mcp-servers/rust/` directory

#### Secret Detection Comparison Scripts

**Problem:** Still run "Rust vs Python" comparisons

**Files to check:**
- `scripts/compare_secret_detection.py` (or similar)
- Any scripts in `scripts/` that mention Rust

**Solution:** Remove Rust comparison logic or delete scripts if Rust-specific

#### Test File: `test_fast_server_go_rust_parity.py`

**Problem:** Both branches now select same tool (no Rust to compare)

**Solution:**
```bash
# Delete the file
rm tests/*/test_fast_server_go_rust_parity.py

# Or if it tests Go vs Python, rename to:
# test_fast_server_go_python_parity.py
```

---

### Category 3: Runtime Code

#### `mcpgateway/version.py`

**Problem:** Runtime compatibility checks for Rust mode

**Solution:**
```python
# Remove Rust mode detection:
def get_runtime_mode():
    # DELETE: if os.getenv("ENABLE_RUST_RUNTIME") == "true":
    # DELETE:     return "rust"
    return "python"
```

#### `mcpgateway/main.py`

**Problem:** Rust runtime initialization code

**Solution:**
```python
# Remove Rust-specific startup logic:
# - Rust mode detection
# - Rust sidecar initialization
# - Rust health check endpoints
```

#### `mcpgateway/runtime_state.py`

**Problem:** Rust runtime state management

**Solution:**
```python
# Remove Rust runtime state:
class RuntimeState:
    # DELETE: rust_mode: bool = False
    # DELETE: rust_sidecar_url: Optional[str] = None
    pass
```

#### Admin UI Files

**Files to check:**
- `mcpgateway/admin_ui/*.js`
- `mcpgateway/templates/*.html`

**Solution:**
```javascript
// Remove Rust mode UI elements:
// - Rust mode badges
// - Rust runtime status indicators
// - Rust-specific configuration options
```

#### Internal MCP/A2A Endpoints

**Problem:** `_rust_session_validated` and internal sidecar endpoints remain

**⚠️ IMPORTANT NOTE:** Some internal MCP RPC code is used by Python session affinity

**Solution:**
```python
# In routers/mcp.py or similar:
# DELETE: @router.post("/_rust_session_validated")
# DELETE: async def rust_session_validated(...):

# KEEP: Internal MCP RPC used by Python session affinity
# TODO: Generalize these endpoints (remove "rust" naming)
# - Rename _rust_* to _internal_* or _session_*
# - Update callers to use new names
```

**Refactoring Plan:**
1. Identify all `_rust_*` endpoints
2. Determine which are truly Rust-specific (delete) vs. used by Python (rename)
3. Create mapping of old → new endpoint names
4. Update all callers
5. Add deprecation warnings for old names (if needed for compatibility)

---

### Category 4: A2A CRUD

**Problem:** Still publishes Redis invalidations solely for removed Rust L1 cache

**Files to check:**
- `mcpgateway/services/a2a_service.py` (or similar)
- Any CRUD operations that publish to Redis

**Solution:**
```python
# Remove Rust L1 cache invalidation:
async def update_a2a_agent(...):
    # ... update logic ...

    # DELETE: Publish Redis invalidation for Rust L1 cache
    # if settings.REDIS_ENABLED:
    #     await redis_client.publish("rust:cache:invalidate", agent_id)

    return agent
```

---

### Category 5: Documentation

#### Live Documentation

**Files to update:**
- `docs/docs/architecture/*.md`
- `docs/docs/deployment/*.md`
- `docs/docs/development/*.md`
- `README.md` (if not already updated)
- `AGENTS.md` (if not already updated)

**Solution:**
```markdown
# Remove or mark as deprecated:
- Rust mode descriptions
- Rust workspace setup instructions
- Rust build commands
- Rust runtime configuration

# Update to reflect Python-only architecture:
- Deployment guides
- Architecture diagrams
- Performance benchmarks (remove Rust comparisons)
```

#### Historical ADRs

**Action:** Mark as superseded but keep for historical context

**Example:**
```markdown
# ADR-XXX: Rust Runtime Implementation

**Status:** SUPERSEDED by ADR-YYY (Removal of Rust Infrastructure)

[Original content remains for historical reference]
```

---

## 📋 SCOPE CLARIFICATION

### Current State Analysis

**What Remains:**
- ✅ Granian (Rust-based ASGI server) - **Third-party dependency**
- ✅ Prebuilt Rust MCP service images - **Third-party services**
- ✅ Rust-backed Python packages (e.g., cryptography, pydantic-core) - **Transitive dependencies**

**What Was Removed:**
- ✅ First-party Rust workspace (`crates/`)
- ✅ First-party Rust runtime and sidecars
- ✅ Rust build infrastructure (Cargo.toml, toolchain, CI)
- ✅ Stdio wrapper (Python + Rust)

### Recommended Scope Statement

**Update PR description to clarify:**

```markdown
## Scope

This PR removes the **first-party Rust workspace, runtime, sidecars, and related build/test infrastructure**.

### What is Removed:
- First-party Rust crates (`crates/mcp_stdio_wrapper`, `request_logging_masking_native_extension`)
- Rust build system (Cargo.toml, Cargo.lock, rust-toolchain.toml, deny.toml)
- Rust CI workflows and Makefile targets
- Stdio wrapper capability (Python + Rust)
- Rust runtime mode and sidecar infrastructure

### What Remains (Intentionally):
- **Granian** - Third-party Rust-based ASGI server (production deployment option)
- **Third-party MCP services** - Prebuilt Rust MCP servers (external dependencies)
- **Transitive Rust dependencies** - Rust-backed Python packages (cryptography, pydantic-core, etc.)

### Rationale:
The goal is to eliminate maintenance burden of first-party Rust code while retaining the benefits of mature third-party Rust-based tools in the Python ecosystem.
```

---

## ✅ VERIFICATION CHECKLIST

Before requesting re-review, verify all items pass:

### Blocking Issues
- [ ] `python scripts/license_checker.py` passes
- [ ] `bump2version --dry-run patch` completes without errors
- [ ] `python -m build --sdist` succeeds and includes `admin_ui/index.js`
- [ ] `pre-commit run --all-files` passes

### Build & Test
- [ ] `make install-dev` completes successfully
- [ ] `make test` passes all unit tests
- [ ] `make lint` passes all linters
- [ ] `make smoketest` passes end-to-end smoke test

### Infrastructure Cleanup
- [ ] No references to `crates/` in active code/configs
- [ ] No `cargo`, `rust`, or `Cargo.toml` in scripts (except historical docs)
- [ ] No Rust mode logic in runtime code
- [ ] Admin UI has no Rust-specific elements
- [ ] Documentation reflects Python-only architecture

### Manual Verification
- [ ] Search codebase for `rust` (case-insensitive): `rg -i "rust" --type py --type yaml --type toml`
- [ ] Search for `cargo`: `rg -i "cargo" --type py --type yaml --type toml`
- [ ] Search for `_rust_`: `rg "_rust_" --type py`
- [ ] Review all modified files in PR diff

---

## 📊 ESTIMATED EFFORT

| Category | Effort | Priority |
|----------|--------|----------|
| Blocking Issues (1-4) | 2-3 hours | 🔴 Critical |
| Build & Docker Cleanup | 1 hour | 🟡 High |
| Scripts & Tooling | 2 hours | 🟡 High |
| Runtime Code Refactoring | 3-4 hours | 🟡 High |
| A2A CRUD Cleanup | 1 hour | 🟢 Medium |
| Documentation Updates | 2-3 hours | 🟢 Medium |
| Testing & Verification | 2 hours | 🔴 Critical |
| **Total** | **13-16 hours** | |

---

## 🎯 RECOMMENDED APPROACH

### Phase 1: Unblock Merge (Critical Path)
1. Fix license checker (30 min)
2. Fix version bumping (15 min)
3. Fix package build (1 hour)
4. Fix pre-commit (30 min)
5. Run verification checklist (30 min)

**Milestone:** PR can build and pass CI

### Phase 2: Infrastructure Cleanup (High Priority)
1. Clean up build configs (1 hour)
2. Update scripts and tooling (2 hours)
3. Refactor runtime code (3-4 hours)
4. Update A2A CRUD (1 hour)

**Milestone:** No Rust infrastructure remains in active code

### Phase 3: Documentation & Polish (Medium Priority)
1. Update live documentation (2-3 hours)
2. Mark historical ADRs as superseded (30 min)
3. Update PR description with scope clarification (15 min)
4. Final verification pass (1 hour)

**Milestone:** PR ready for final review

---

## 📝 COMMIT STRATEGY

Suggested commit sequence for clean history:

```bash
# Phase 1: Blocking fixes
git commit -m "fix: update license checker to skip Rust when no Cargo.toml"
git commit -m "fix: remove Cargo.toml reference from .bumpversion.cfg"
git commit -m "fix: restore Admin UI assets to MANIFEST.in"
git commit -m "fix: regenerate secrets baseline without Cargo references"

# Phase 2: Infrastructure cleanup
git commit -m "refactor: remove Rust references from build configs"
git commit -m "refactor: clean up Rust-specific scripts and tooling"
git commit -m "refactor: remove Rust runtime code and generalize internal endpoints"
git commit -m "refactor: remove Rust L1 cache invalidation from A2A CRUD"

# Phase 3: Documentation
git commit -m "docs: update live docs to reflect Python-only architecture"
git commit -m "docs: mark Rust ADRs as superseded"
git commit -m "docs: clarify PR scope regarding third-party Rust dependencies"
```

---

## 🔍 ADDITIONAL NOTES

### Internal MCP RPC Endpoints

The reviewer noted that some internal MCP RPC code is used by Python session affinity and should be **generalized, not deleted**. This requires careful analysis:

1. **Audit all `_rust_*` endpoints:**
   ```bash
   rg "_rust_" mcpgateway/routers/ mcpgateway/transports/
   ```

2. **Categorize each endpoint:**
   - Rust-specific (safe to delete)
   - Used by Python session affinity (rename/generalize)
   - Shared infrastructure (refactor)

3. **Create refactoring plan:**
   - Document current usage
   - Design new naming convention
   - Update all callers
   - Add tests for renamed endpoints

### Third-Party Rust Dependencies

The PR should explicitly state that third-party Rust dependencies (Granian, cryptography, pydantic-core, etc.) are **intentionally retained**. This is standard practice in the Python ecosystem and provides performance benefits without maintenance burden.

---

## 📞 NEXT STEPS

1. **Review this plan** with the team
2. **Prioritize** which items to address in this PR vs. follow-up PRs
3. **Execute Phase 1** to unblock merge
4. **Request re-review** after Phase 1 completion
5. **Complete Phases 2-3** based on reviewer feedback

---

**Plan Created:** July 21, 2026
**Last Updated:** July 21, 2026
**Status:** Phase 1 Complete - All blocking issues fixed and committed

---

## ✅ PHASE 1 COMPLETION SUMMARY

**Commits:**
- `01053f1b9` - "fix: address blocking issues from PR review"
- `8b386cc6a` - "refactor: completely remove Rust dependency scanning from license checker"

All 4 blocking issues have been successfully resolved:

1. ✅ **License Checker** - Completely removed `scan_rust_modules()` function and Rust scanning from `scripts/license_checker.py`
2. ✅ **Version Bumping** - Removed `[bumpversion:file:Cargo.toml]` section from `.bumpversion.cfg`
3. ✅ **Package Build** - Restored Admin UI assets to `MANIFEST.in` (recursive-include for admin_ui, static, templates)
4. ✅ **Pre-commit** - Removed Cargo.lock and crates/ references from `.secrets.baseline`

**Verification Results:**
- ✅ `uv run bump2version --dry-run --allow-dirty patch` - Passes
- ✅ `uv run python -m build --sdist` - Successfully builds package with admin_ui/index.js included
- ✅ `pre-commit run detect-secrets --all-files` - Passes after staging changes
- ✅ Rust dependency scanning completely removed from license checker
- ✅ Cargo.lock removed from Makefile DETECT_SECRETS_FILES_EXCLUDE
- ⚠️ License checker still reports missing `pip-licenses` and `go-licenses` tools (not Rust-related)

**Next Steps:** Proceed to Phase 2 (Infrastructure Cleanup) or Phase 3 (Documentation) as needed.
