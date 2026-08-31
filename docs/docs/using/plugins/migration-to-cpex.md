# Migrating to CPEX (External Plugin Framework)

!!! warning "Breaking Change"
    This migration is required when upgrading from ContextForge ≤ 1.0.0 to the CPEX-based plugin framework. Existing plugins **will not load** until imports and mode names are updated.

## Overview

The plugin framework has been extracted from `mcpgateway/plugins/framework/` into the standalone [CPEX](https://github.com/contextforge-org/contextforge-plugins-framework) package (`cpex>=0.1.0`). All framework classes, utilities, and CLI tools now live in the `cpex` namespace.

**What moved:**

| Before | After |
|--------|-------|
| `from mcpgateway.plugins.framework import ...` | `from cpex.framework import ...` |
| `from mcpgateway.plugins.framework.decorator import hook` | `from cpex.framework.decorator import hook` |
| `from mcpgateway.plugins.tools import ...` | `from cpex.tools import ...` |

**What was deleted (no longer exists):**

- `mcpgateway/plugins/framework/` — entire directory
- `mcpgateway/plugins/tools/` — CLI and models
- `plugin_templates/` — bootstrap templates (now provided by `cpex`)

---

## Step 1: Update Imports

Replace all `mcpgateway.plugins.framework` imports with `cpex.framework`:

```python
# Before
from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext
from mcpgateway.plugins.framework import (
    ToolPreInvokePayload, ToolPreInvokeResult,
    PromptPrehookPayload, PromptPrehookResult,
    PluginViolation, PluginMode,
)
from mcpgateway.plugins.framework.decorator import hook

# After
from cpex.framework import Plugin, PluginConfig, PluginContext
from cpex.framework import (
    ToolPreInvokePayload, ToolPreInvokeResult,
    PromptPrehookPayload, PromptPrehookResult,
    PluginViolation, PluginMode,
)
from cpex.framework.decorator import hook
```

CLI tools:

```python
# Before
from mcpgateway.plugins.tools.cli import main

# After
from cpex.tools.cli import main
```

---

## Step 2: Update Plugin Modes in Configuration

The mode vocabulary has been unified to use CPEX's native `PluginMode` enum values. Legacy gateway mode names continue to work at runtime (they are mapped automatically), but new configurations should use the native names.

### Mode Mapping

| Legacy (gateway) | CPEX Native | Behavior |
|------------------|-------------|----------|
| `enforce` | `sequential` | Execute plugins in sequence; block on violation or error |
| `enforce_ignore_error` | `sequential` + `on_error: ignore` | Block on violation; swallow plugin errors |
| `permissive` | `transform` | Log violations; allow request to continue |
| `disabled` | `disabled` | Plugin loaded but never executed |
| *(new)* | `concurrent` | Execute plugins in parallel |
| *(new)* | `audit` | Execute after the request (non-blocking) |
| *(new)* | `fire_and_forget` | Execute without waiting for result |

### Configuration Update

```yaml
# Before
plugins:
  - name: "SecurityPlugin"
    kind: "plugins.security.SecurityPlugin"
    hooks: ["tool_pre_invoke"]
    mode: "enforce"          # ← legacy name
    priority: 50

  - name: "MonitorPlugin"
    kind: "plugins.monitor.MonitorPlugin"
    hooks: ["tool_post_invoke"]
    mode: "permissive"       # ← legacy name
    priority: 100

# After
plugins:
  - name: "SecurityPlugin"
    kind: "plugins.security.SecurityPlugin"
    hooks: ["tool_pre_invoke"]
    mode: "sequential"       # ← native name
    priority: 50

  - name: "MonitorPlugin"
    kind: "plugins.monitor.MonitorPlugin"
    hooks: ["tool_post_invoke"]
    mode: "transform"        # ← native name
    priority: 100
```

### Replacing `enforce_ignore_error`

The `enforce_ignore_error` mode is replaced by combining `sequential` mode with the new `on_error` field:

```yaml
# Before
- name: "MyPlugin"
  mode: "enforce_ignore_error"

# After
- name: "MyPlugin"
  mode: "sequential"
  on_error: "ignore"
```

The `on_error` field accepts: `fail` (default — block on error), `ignore` (swallow errors), `disable` (disable plugin on first error).

---

## Step 3: Update Payload Field Names

Two payload fields were renamed for consistency:

| Payload class | Old field | New field |
|--------------|-----------|-----------|
| `PromptPosthookPayload` | `.name` | `.prompt_id` |
| `ToolPreInvokePayload` | `.arguments` | `.args` |

```python
# Before
async def prompt_post_fetch(self, payload, context):
    name = payload.name  # ← old field
    ...

async def tool_pre_invoke(self, payload, context):
    args = payload.arguments  # ← old field
    ...

# After
async def prompt_post_fetch(self, payload, context):
    name = payload.prompt_id  # ← new field
    ...

async def tool_pre_invoke(self, payload, context):
    args = payload.args  # ← new field
    ...
```

---

## Step 4: Update Tool Plugin Bindings (API)

The `PluginPolicyItem` API now accepts all CPEX native modes in addition to legacy names, and includes an optional `on_error` field:

```json
{
  "tool_names": ["*"],
  "plugin_id": "OutputLengthGuardPlugin",
  "mode": "sequential",
  "on_error": "ignore",
  "priority": 50,
  "config": {"max_length": 4096}
}
```

Valid `mode` values: `enforce`, `enforce_ignore_error`, `permissive`, `disabled`, `sequential`, `concurrent`, `transform`, `audit`, `fire_and_forget`.

Valid `on_error` values: `fail`, `ignore`, `disable` (or `null` for default behavior).

---

## Step 5: Verify with Acceptance Tests

Run the CPEX contract tests to verify your environment is correctly wired:

```bash
pytest tests/acceptance/plugins/test_cpex_contract.py -v
```

These tests validate:

- All expected symbols are importable from `cpex.framework`
- Payload models serialize/deserialize correctly
- `PluginMode` enum has expected members
- `OnError` enum is available
- Settings env vars are read correctly

---

## Backward Compatibility

The gateway maintains **runtime backward compatibility** for legacy mode names:

- `plugins/config.yaml` files using `enforce`, `enforce_ignore_error`, `permissive`, `disabled` continue to work — the gateway's `_GATEWAY_MODE_TO_PLUGIN_MODE` mapping translates them to CPEX native enums at load time.
- The Admin UI displays unified labels that deduplicate legacy and native names (e.g., both `enforce` and `sequential` display as "Sequential (Enforce)").
- Redis mode overrides accept both legacy and native mode values.
- The API accepts both vocabularies for `PluginModeUpdateRequest` and `PluginPolicyItem.mode`.

However, **import paths are not backward-compatible** — any code importing from `mcpgateway.plugins.framework` will fail with `ModuleNotFoundError`.

---

## Quick Migration Checklist

- [ ] Update all `from mcpgateway.plugins.framework` → `from cpex.framework`
- [ ] Update all `from mcpgateway.plugins.tools` → `from cpex.tools`
- [ ] Rename `payload.name` → `payload.prompt_id` in prompt posthook handlers
- [ ] Rename `payload.arguments` → `payload.args` in tool pre-invoke handlers
- [ ] (Optional) Update `plugins/config.yaml` mode values to native names
- [ ] (Optional) Replace `enforce_ignore_error` with `mode: sequential` + `on_error: ignore`
- [ ] Run `pytest tests/acceptance/plugins/test_cpex_contract.py` to verify
- [ ] Run full plugin test suite: `pytest tests/unit/mcpgateway/plugins/ -v`

---

## Scaffolding New Plugins

The `mcpplugins` CLI (provided by `cpex`) replaces the deleted `plugin_templates/` directory:

```bash
# Bootstrap a new plugin
mcpplugins bootstrap --destination plugins/my_plugin --type native
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'mcpgateway.plugins.framework'`**

The internal framework has been deleted. Update imports to `cpex.framework`.

**`PluginViolation` constructor errors**

The field signature is unchanged from the old in-tree model. Ensure you pass `reason`, `description`, and `code` (all required). `http_status_code` and `http_headers` remain optional.

**`AttributeError: 'ToolPreInvokePayload' object has no attribute 'arguments'`**

The field was renamed to `.args`. See [Step 3](#step-3-update-payload-field-names).

**`AttributeError: 'PromptPosthookPayload' object has no attribute 'name'`**

The field was renamed to `.prompt_id`. See [Step 3](#step-3-update-payload-field-names).

**Plugin not executing after mode change**

Verify the mode value is valid. The CPEX native modes are: `sequential`, `transform`, `concurrent`, `audit`, `fire_and_forget`, `disabled`.
