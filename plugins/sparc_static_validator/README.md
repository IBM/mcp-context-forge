# SPARC Static Validator Plugin

> **Author:** Osher Elhadad
> **Version:** 0.1.0
> **Requires:** `agent-lifecycle-toolkit>=0.10.0`

The SPARC Static Validator plugin provides comprehensive **syntax validation** for tool call arguments before execution. Using the **SPARC (Semantic Pre-execution Analysis for Reliable Calls)** component from the Agent Lifecycle Toolkit (ALTK), it catches common errors like missing required parameters, type mismatches, and invalid values (with correction suggestions when possible) — all without requiring an LLM.

## Why Use This Plugin?

**Catch errors early** — Validate tool calls before execution to prevent runtime failures.

**Auto-fix common mistakes** — Optionally auto-correct type mismatches (e.g., `"123"` → `123`).

**Zero LLM cost** — Uses pure static analysis with JSON Schema validation.

**Production-ready** — Graceful degradation when ALTK is not installed.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Validation Checks](#validation-checks)
- [Error Codes](#error-codes)
- [Examples](#examples)
- [Type Correction](#type-correction)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)

---

## Installation

The plugin requires the optional `altk` dependency:

```bash
# Install MCP Gateway with ALTK support
pip install mcp-contextforge-gateway[altk]
```

Or add to your existing installation:

```bash
pip install agent-lifecycle-toolkit>=0.10.0
```

> **Note:** The plugin works without ALTK but will skip validation and log a warning.

---

## Quick Start

Add the plugin to your `plugins/config.yaml`:

```yaml
plugins:
  - name: "SPARCStaticValidator"
    kind: "plugins.sparc_static_validator.sparc_static_validator.SPARCStaticValidatorPlugin"
    description: "SPARC static validation for tool call arguments"
    version: "0.1.0"
    author: "Osher Elhadad"
    hooks: ["tool_pre_invoke"]
    tags: ["validation", "sparc", "altk", "static", "schema"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 60     # Run early, after argument normalizer
    conditions: []
    config:
      block_on_violation: true
      enable_type_correction: true
      auto_apply_corrections: false
```

That's it! The plugin will automatically validate tool calls against their `input_schema`.

---

## Configuration

### Full Configuration Options

```yaml
config:
  # Block tool execution when validation fails
  # When false, validation errors are logged but execution continues
  block_on_violation: true

  # Attempt automatic type conversion for mismatched types
  # e.g., "123" → 123 for integer fields
  enable_type_correction: true

  # Automatically apply type corrections to the payload
  # Only works when enable_type_correction is true
  auto_apply_corrections: false

  # Include corrected arguments in response metadata
  include_correction_in_response: true

  # Log when corrections are available or applied
  log_corrections: true

  # Optional per-tool schemas (overrides tool metadata)
  tool_schemas:
    my_custom_tool:
      type: object
      required: [param1, param2]
      properties:
        param1:
          type: string
        param2:
          type: integer
          minimum: 0
          maximum: 100
```

### Configuration Options Explained

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `block_on_violation` | bool | `true` | Stop tool execution on validation failure |
| `enable_type_correction` | bool | `true` | Try to fix type mismatches automatically |
| `auto_apply_corrections` | bool | `false` | Apply fixes to the payload (use with caution) |
| `include_correction_in_response` | bool | `true` | Include fix suggestions in response |
| `log_corrections` | bool | `true` | Log when corrections are available |
| `tool_schemas` | dict | `null` | Override schemas for specific tools |

---

## How It Works

```
┌─────────────────────┐
│   Tool Call Request │
│  (name + arguments) │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────────────┐
│    Get Tool Schema               │
│  (from metadata or config)       │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│    Convert to SPARC Format       │
│  (OpenAI function calling spec)  │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│    SPARC Static Validation       │
│  • Required parameters           │
│  • Type checking                 │
│  • Enum validation               │
│  • Schema constraints            │
└──────────┬───────────────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌─────────┐  ┌─────────────────────────┐
│  Pass   │  │  Fail                   │
│ Continue│  │  • Block (if configured)│
│         │  │  • Suggest corrections  │
└─────────┘  │  • Log errors           │
             └─────────────────────────┘
```

### Schema Source Priority

1. **Plugin config** — `tool_schemas` in plugin configuration (highest priority)
2. **Tool metadata** — `input_schema` from the tool's metadata in global context

---

## Validation Checks

The plugin performs the following static validations:

| Check | Description | Example Error |
|-------|-------------|---------------|
| **Required Parameters** | Detects missing required fields | `"Missing required: email, subject"` |
| **Type Checking** | Validates parameter types | `"Expected integer, got string"` |
| **Unknown Parameters** | Detects extra/unknown fields | `"Parameter 'foo' not defined"` |
| **Enum Validation** | Checks allowed values | `"Value must be: low, medium, high"` |
| **Schema Constraints** | min/max, minLength, pattern, etc. | `"Value 150 exceeds maximum 100"` |
| **JSON Schema** | Full JSON Schema Draft 7 validation | Various schema violations |

---

## Error Codes

The plugin maps SPARC validation errors to specific error codes:

| Error Code | Description | Common Cause |
|------------|-------------|--------------|
| `SPARC_MISSING_REQUIRED` | Required parameter is missing | Forgot to include a required field |
| `SPARC_TYPE_ERROR` | Parameter has wrong type | `"123"` instead of `123` |
| `SPARC_UNKNOWN_PARAM` | Parameter not in schema | Typo in parameter name |
| `SPARC_ENUM_VIOLATION` | Value not in allowed list | Invalid enum value |
| `SPARC_SCHEMA_ERROR` | General schema violation | min/max, pattern, format issues |
| `SPARC_UNKNOWN_FUNCTION` | Tool name not found | Tool not registered |
| `SPARC_VALIDATION_FAILED` | General validation failure | Multiple issues |

### Error Response Example

When validation fails with `block_on_violation: true`:

```json
{
  "error": {
    "code": "SPARC_MISSING_REQUIRED",
    "reason": "SPARC static validation failed",
    "description": "Tool call validation failed:\n• Missing required: subject, body",
    "details": {
      "errors": [
        {
          "code": "SPARC_MISSING_REQUIRED",
          "check": "missing_required_parameter",
          "description": "One or more required parameters are missing from the call.",
          "explanation": "Missing required: subject, body"
        }
      ],
      "correction": null,
      "tool_name": "send_email",
      "arguments": {"to": ["john@example.com"]}
    }
  }
}
```

---

## Examples

### Example 1: Valid Tool Call

```python
# Tool schema (from tool metadata)
input_schema = {
    "type": "object",
    "required": ["to", "subject", "body"],
    "properties": {
        "to": {"type": "array", "items": {"type": "string"}},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]}
    }
}

# Valid tool call - passes validation
args = {
    "to": ["john@example.com"],
    "subject": "Hello",
    "body": "Hi there!",
    "priority": "normal"
}
# ✅ Validation passes, tool executes normally
```

### Example 2: Missing Required Parameters

```python
# Missing 'subject' and 'body'
args = {
    "to": ["john@example.com"]
}
# ❌ SPARC_MISSING_REQUIRED: Missing required: subject, body
```

### Example 3: Type Mismatch with Correction

```python
# Schema expects integer for duration_minutes
input_schema = {
    "type": "object",
    "required": ["duration_minutes"],
    "properties": {
        "duration_minutes": {"type": "integer"}
    }
}

# String instead of integer
args = {"duration_minutes": "30"}

# With enable_type_correction: true
# → Correction suggested: {"duration_minutes": 30}

# With auto_apply_corrections: true
# → Payload automatically fixed and execution continues
```

### Example 4: Enum Violation

```python
# Schema with enum constraint
input_schema = {
    "type": "object",
    "properties": {
        "priority": {"type": "string", "enum": ["low", "normal", "high"]}
    }
}

args = {"priority": "urgent"}
# ❌ SPARC_ENUM_VIOLATION: 'urgent' not in allowed values [low, normal, high]
```

### Example 5: Override Schema in Config

```yaml
config:
  tool_schemas:
    # Override schema for specific tool
    legacy_calculator:
      type: object
      required: [operation, a, b]
      properties:
        operation:
          type: string
          enum: [add, subtract, multiply, divide]
        a:
          type: number
        b:
          type: number
```

---

## Type Correction

The plugin can automatically detect and optionally fix common type mismatches:

### Supported Corrections

| From | To | Example |
|------|----|---------|
| `string` | `integer` | `"123"` → `123` |
| `string` | `number` | `"3.14"` → `3.14` |
| `string` | `boolean` | `"true"` → `true` |
| `integer/float` | `boolean` | `1` → `true` |
| Single value | `array` | `"email@test.com"` → `["email@test.com"]` |

### Correction Modes

1. **Suggest only** (default):
   ```yaml
   enable_type_correction: true
   auto_apply_corrections: false
   ```
   Corrections are included in the response but not applied.

2. **Auto-apply**:
   ```yaml
   enable_type_correction: true
   auto_apply_corrections: true
   ```
   Corrections are automatically applied to the payload.

> ⚠️ **Caution:** Use `auto_apply_corrections` carefully in production. It modifies the original request.

---

### Comparison with Schema Guard Plugin

| Feature | SPARC Static Validator | Schema Guard |
|---------|----------------------|--------------|
| JSON Schema support | Full (Draft 7) | Minimal subset |
| Type correction | ✅ Yes | ❌ No |
| Auto-apply fixes | ✅ Yes | ❌ No |
| Uses tool metadata | ✅ Yes | ❌ No (config only) |
| Post-invoke validation | ❌ No | ✅ Yes |
| External dependency | ALTK | None |

---

## Troubleshooting

### Plugin Not Validating

1. **Check ALTK installation:**
   ```bash
   pip show agent-lifecycle-toolkit
   ```
   If not installed, install with:
   ```bash
   pip install agent-lifecycle-toolkit>=0.10.0
   ```

2. **Check tool has input_schema:**
   The tool must have an `input_schema` defined in its metadata, or you must provide one in `tool_schemas` config.

3. **Check plugin is enabled:**
   Ensure `mode` is not `disabled` in config.yaml.

### Validation Too Strict

Set permissive mode to log errors without blocking:
```yaml
mode: "permissive"
# or
config:
  block_on_violation: false
```

### Type Corrections Not Working

Ensure both settings are enabled:
```yaml
config:
  enable_type_correction: true
  auto_apply_corrections: true  # if you want auto-fix
```

### Debug Logging

Enable debug logging to see validation details:
```python
import logging
logging.getLogger("plugins.sparc_static_validator").setLevel(logging.DEBUG)
```
