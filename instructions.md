# Merge Plan: `upstream/main` → `feat/cpex`

## Context

**Branch `feat/cpex`** replaces the in-tree plugin framework (`mcpgateway/plugins/framework/`) with the external [CPEX](https://github.com/contextforge-org/contextforge-plugins-framework) package (`cpex>=0.1.0.dev11`). The entire `mcpgateway/plugins/framework/` directory has been deleted and all imports migrated to `cpex.framework`.

Since `feat/cpex` was created, **88 commits** have landed on `upstream/main` — including 3 PRs that modified files inside `mcpgateway/plugins/framework/`, which no longer exists on `feat/cpex`.

**CPEX tracking PR**: [contextforge-org/contextforge-plugins-framework#11](https://github.com/contextforge-org/contextforge-plugins-framework/pull/11) — backports of in-tree changes, tagged `0.1.0.dev11`.

---

## The 3 Critical PRs

### PR #4292 — Runtime plugin management (global toggle, per-plugin mode, cross-instance propagation)
- **Merged**: 2026-04-19
- **Framework files touched**: `__init__.py`, `_redis.py` (new), `_state.py` (new), `manager.py`
- **CF-side files touched**: `admin.py`, `main.py`, `gateway_plugin_manager.py`, `routers/tool_plugin_bindings.py`, `schemas.py`, `services/plugin_service.py`
- **What it does**: Adds Redis pub/sub for cross-worker/cross-pod plugin state propagation, runtime enable/disable endpoints, per-plugin mode changes.
- **Merge strategy**: The `_redis.py` and `_state.py` modules it adds to `framework/` are **new files** that don't exist in CPEX. The runtime management logic (Redis pub/sub, state propagation, API endpoints) is **gateway-specific orchestration** — it should be refactored to live in CF modules (`mcpgateway/plugins/` or `mcpgateway/services/`), not inside CPEX. The framework-level changes (manager cache invalidation hooks, shutdown changes) need to be checked against what CPEX `0.1.0.dev11` already provides. Accept all CF-side file changes.

### PR #4331 — SpanAttributeCustomizer plugin (customizable OTel span attributes)
- **Merged**: 2026-04-21
- **Framework files touched**: `__init__.py`, `_redis.py`, `_state.py`, `manager.py`, `utils.py`
- **CF-side files touched**: `admin.py`, `handlers/signal_handlers.py`, `middleware/request_logging_middleware.py`, `routers/runtime_admin_router.py`, `runtime_state.py`, `services/observability_service.py`, `services/tool_service.py`, `services/tool_plugin_binding_service.py`, various transport files, `plugins/span_attribute_customizer/` (new plugin), alembic migration
- **What it does**: Adds span attribute customization via a plugin + `apply_attribute_mapping()` utility. Modifies the executor's observability span creation in `manager.py` and adds a helper to `utils.py`.
- **Merge strategy**: The `utils.py` addition (`apply_attribute_mapping`) is a generic utility that could live in CPEX, but per the user's preference, it should be refactored to live in CF (e.g., new `mcpgateway/plugins/utils.py`). The `manager.py` changes (enriched span attributes) need to be checked against CPEX's `ObservabilityProvider` protocol — if CPEX already exposes the right hooks, the customization should be wired via the provider protocol on the CF side rather than patching the framework. Accept all CF-side file changes and the new `plugins/span_attribute_customizer/` plugin.

### PR #3152 — End-user identity propagation
- **Merged**: 2026-04-23
- **Framework files touched**: `__init__.py` (re-export `UserContext`), `models.py` (new `UserContext` class)
- **CF-side files touched**: `auth.py`, `config.py`, `db.py`, `middleware/rbac.py`, `schemas.py`, `services/audit_trail_service.py`, `services/oauth_manager.py`, `services/resource_service.py`, `services/tool_service.py`, `transports/context.py`, `transports/streamablehttp_transport.py`, `utils/identity_propagation.py` (new), alembic migrations
- **Merge strategy**: Per the user's comment, `UserContext` should be **kept in CF, not CPEX**. CPEX provides extension points for this purpose. The `UserContext` model should live in a CF module (e.g., `mcpgateway/transports/context.py` or `mcpgateway/models/user_context.py`), and the framework `__init__.py` / `models.py` additions should be discarded. Accept all CF-side file changes (auth, config, db, services, transports, utils).

---

## Pre-Merge Preparation

### Step 0: Commit or stash local changes
```bash
# There are unstaged changes to .secrets.baseline and pyproject.toml
git add .secrets.baseline pyproject.toml
git commit -s -m "chore: stage local changes before merge"
```

### Step 1: Fetch upstream
```bash
git fetch upstream main
```

### Step 2: Verify CPEX version
Confirm `pyproject.toml` on `feat/cpex` pins `cpex>=0.1.0.dev11` and that `0.1.0.dev11` includes the backports from CPEX PR #11 that cover the framework-internal changes from PRs already merged before #4292/#4331/#3152.

---

## Merge Execution

### Step 3: Start the merge
```bash
git merge upstream/main --no-ff
```

This will produce conflicts. Based on the trial merge, the following conflicts are expected:

#### Category A: Framework delete/modify conflicts (the 3 PRs)
These files were deleted on `feat/cpex` and modified on `main`. Resolution: **delete them** (they belong to CPEX now), but first extract any logic that must live in CF.

| File | Action |
|------|--------|
| `mcpgateway/plugins/framework/__init__.py` | Delete. Any new re-exports (#3152 `UserContext`, #4292 runtime symbols) will be handled by CF-side modules. |
| `mcpgateway/plugins/framework/manager.py` | Delete. Span attribute enrichment (#4331) and runtime management hooks (#4292) will be refactored into CF. |
| `mcpgateway/plugins/framework/models.py` | Delete. `UserContext` (#3152) will be placed in a CF module. |
| `mcpgateway/plugins/framework/utils.py` | Delete. `apply_attribute_mapping()` (#4331) will be placed in a CF module. |
| `mcpgateway/plugins/framework/_redis.py` | Delete. Runtime Redis shim (#4292) will be refactored into CF's `mcpgateway/plugins/` or a new module. |
| `mcpgateway/plugins/framework/_state.py` | Delete. Runtime state (#4292) will be refactored into CF's `mcpgateway/plugins/` or a new module. |

#### Category B: Content conflicts in CF-side files
These need manual resolution — accept the `upstream/main` changes for the new functionality, but fix imports from `mcpgateway.plugins.framework` → `cpex.framework`.

| File | Notes |
|------|-------|
| `mcpgateway/auth.py` | Identity propagation changes (#3152). Resolve, keep upstream additions. |
| `mcpgateway/main.py` | Runtime management startup/shutdown (#4292). Resolve, fix framework imports. |
| `mcpgateway/middleware/rbac.py` | Identity propagation (#3152). Resolve, keep upstream. |
| `mcpgateway/plugins/gateway_plugin_manager.py` | Runtime management (#4292). Resolve, fix imports. |
| `mcpgateway/routers/tool_plugin_bindings.py` | Runtime management (#4292). Resolve, fix imports. |
| `mcpgateway/schemas.py` | Both #4292 and #3152 additions. Resolve, fix imports. |
| `mcpgateway/services/tool_service.py` | Both #4331 and #3152 changes. Resolve, fix imports. |
| `mcpgateway/services/prompt_service.py` | Resolve, fix imports. |
| `plugins/config.yaml` | Span attribute customizer config (#4331). Resolve. |
| `pyproject.toml` | Dependency changes. Resolve, keep cpex dependency. |
| `crates/request_logging_masking_native_extension/pyproject.toml` | Resolve. |
| `uv.lock` | Regenerate after merge. |

#### Category C: Test file conflicts
| File | Action |
|------|--------|
| `tests/unit/mcpgateway/plugins/conftest.py` | Resolve, fix framework imports → cpex. |
| `tests/unit/mcpgateway/plugins/framework/test_observability.py` | Delete (framework tests belong in CPEX). |
| `tests/unit/mcpgateway/plugins/framework/test_policies.py` | Delete. |
| `tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_stdio.py` | Delete. |
| `tests/unit/mcpgateway/plugins/framework/external/unix/test_client_integration.py` | Delete. |
| `tests/unit/mcpgateway/plugins/test_gateway_plugin_manager.py` | Resolve, fix imports. |
| `tests/unit/mcpgateway/routers/test_tool_plugin_bindings.py` | Resolve, fix imports. |
| `tests/unit/mcpgateway/services/test_prompt_service.py` | Resolve, fix imports. |
| `tests/unit/mcpgateway/services/test_tool_plugin_binding_service.py` | Resolve, fix imports. |
| `tests/unit/mcpgateway/services/test_tool_service_coverage.py` | Resolve, fix imports. |
| `tests/unit/mcpgateway/test_main.py` | Resolve, fix imports. |
| `tests/unit/plugins/test_secrets_detection.py` | Keep HEAD version (deleted upstream). |
| `tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py` | Keep HEAD version (deleted upstream). |

#### Category D: Template conflicts
| File | Action |
|------|--------|
| `plugin_templates/external/{{cookiecutter.plugin_slug}}/Containerfile` | Delete (templates removed in feat/cpex). |
| `plugin_templates/external/{{cookiecutter.plugin_slug}}/Makefile` | Delete. |

---

## Post-Merge Refactoring (The 3 PRs)

After resolving conflicts, the following refactoring is needed to integrate the functionality from the 3 PRs without putting code back into `mcpgateway/plugins/framework/`.

### Refactor 1: `UserContext` model (from PR #3152)

**Goal**: Keep `UserContext` in CF, not CPEX. CPEX provides extension mechanisms for custom context.

1. Create `UserContext` in a CF module — `mcpgateway/transports/context.py` already exists and is a natural fit, or create `mcpgateway/models/user_context.py` if a separate module is preferred.
2. Check all references that imported `UserContext` from `mcpgateway.plugins.framework` or `mcpgateway.plugins.framework.models` — update them to the new CF location.
3. If CPEX's `GlobalContext` needs to carry user context, use CPEX's extension mechanism (e.g., `GlobalContext.state` or `GlobalContext.extra`) to pass it through, rather than adding it to CPEX's `models.py`.
4. Verify `mcpgateway/auth.py`, `mcpgateway/middleware/rbac.py`, and `mcpgateway/transports/context.py` all reference the CF-local `UserContext`.

### Refactor 2: Runtime plugin management (from PR #4292)

**Goal**: Keep Redis pub/sub state propagation and runtime toggle logic in CF modules.

1. **`_redis.py`** (Redis provider shim): This was a dependency-inversion shim to let the framework access Redis without importing `mcpgateway.utils`. Since CPEX is now external, this shim is no longer needed in its original form. If CPEX's `TenantPluginManager` or factory needs Redis, wire it via CF's `gateway_plugin_manager.py` by passing the Redis client through constructor injection or the existing provider pattern.
2. **`_state.py`** (in-process runtime state): Move the runtime state (plugin enabled/disabled flags, per-plugin mode overrides, in-process override map) to `mcpgateway/plugins/` — e.g., `mcpgateway/plugins/runtime_state.py` or integrate into `mcpgateway/runtime_state.py` (which #4331 already created).
3. **`__init__.py` additions** (new runtime functions like `plugin_invalidation_listener`, `stop_plugin_invalidation_listener`, runtime enable/disable helpers): Move to `mcpgateway/plugins/` — e.g., `mcpgateway/plugins/runtime_management.py`.
4. **`manager.py` changes** (cache invalidation hooks, shutdown with factory cleanup): Check if CPEX `0.1.0.dev11`'s `TenantPluginManagerFactory` already handles shutdown/reload. If so, wire from CF side. If CPEX needs additional hooks, those should be added to CPEX PR #11 rather than patching CF.
5. **`gateway_plugin_manager.py` changes**: These stay in CF. Fix imports.
6. **New endpoints** (`PUT /admin/plugins`, `PUT /admin/plugins/{name}`, enhanced `GET /admin/plugins`): These are in `admin.py`, `services/plugin_service.py`, `routers/runtime_admin_router.py` — all CF-side. Accept as-is, fix imports.

### Refactor 3: Span attribute customization (from PR #4331)

**Goal**: Keep attribute mapping/customization logic in CF, use CPEX's `ObservabilityProvider` protocol.

1. **`utils.py` addition** (`apply_attribute_mapping()`): Move to `mcpgateway/plugins/observability_adapter.py` or `mcpgateway/services/observability_service.py`.
2. **`manager.py` changes** (enriched span attributes in executor): Check if CPEX's `ObservabilityProvider` protocol already exposes the span creation hook that #4331 modified. If so, implement the enrichment in CF's observability adapter. If CPEX's protocol is insufficient, coordinate with CPEX PR #11 to add the needed hook.
3. **New plugin** (`plugins/span_attribute_customizer/`): Accept as-is — this is a CF-side plugin, not framework code.
4. **`services/observability_service.py` changes**: Accept as-is, fix any framework imports.

---

## Post-Merge Validation

### Step 4: Fix remaining import references
```bash
# Find any remaining references to the old in-tree framework
grep -rn "from mcpgateway.plugins.framework" mcpgateway/ tests/ plugins/ --include="*.py"
grep -rn "import mcpgateway.plugins.framework" mcpgateway/ tests/ plugins/ --include="*.py"
```
All hits must be updated to either `from cpex.framework` (for CPEX-owned types) or the new CF module location (for `UserContext`, runtime state, etc.).

### Step 5: Regenerate lock file
```bash
uv lock
```

### Step 6: Lint and format
```bash
make autoflake isort black pre-commit
make ruff bandit interrogate pylint
```

### Step 7: Run tests
```bash
python -m pytest tests/unit/ -x -q
```

### Step 8: Verify no framework directory resurrection
```bash
# This directory should NOT exist after merge
ls mcpgateway/plugins/framework/ 2>/dev/null && echo "ERROR: framework dir still exists" || echo "OK: framework dir removed"
```

### Step 9: Commit the merge
```bash
git commit -s -m "chore: merge upstream/main into feat/cpex

Merge upstream/main (88 commits) into feat/cpex.

Resolved conflicts from 3 PRs that modified the now-removed in-tree
plugin framework:
- #4292 (runtime plugin management) — refactored Redis/state into CF modules
- #4331 (span attribute customizer) — moved attribute mapping to CF
- #3152 (identity propagation) — kept UserContext in CF, not CPEX

All mcpgateway/plugins/framework/ files remain deleted; functionality
is provided by cpex>=0.1.0.dev11 and CF-side modules."
```

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| CPEX `0.1.0.dev11` missing hooks needed by #4292/#4331 | Medium | Check CPEX PR #11 diff against the specific `manager.py` changes. If gaps exist, add to CPEX before merging. |
| Import breakage in transitive test files | High | Run full `grep` sweep (Step 4) and test suite (Step 7). |
| Alembic migration ordering conflicts | Low | Verify `alembic heads` shows single head after merge. |
| `uv.lock` conflict | Certain | Regenerate entirely (Step 5). |
| Runtime management state module placement | Medium | May need iteration — `runtime_state.py` already exists from #4331, consolidate there. |

---

## Open Questions

1. **CPEX `_redis.py` / `_state.py` equivalents**: Does CPEX `0.1.0.dev11` already have its own Redis and state abstractions, or do we need to build CF-side wrappers? → Check CPEX PR #11.
2. **`ObservabilityProvider` protocol sufficiency**: Does CPEX's protocol expose enough hooks for the span attribute enrichment from #4331, or do we need a CPEX protocol extension? → Check `cpex/framework/observability.py`.
3. **`UserContext` placement**: `mcpgateway/transports/context.py` vs a new `mcpgateway/models/user_context.py`? The transport context file already exists and handles request context — it's a natural home, but a dedicated module keeps concerns separated.
