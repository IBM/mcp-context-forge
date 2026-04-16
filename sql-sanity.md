# SQL Sanitizer Plugin

## Overview

The SQL Sanitizer plugin detects risky SQL patterns in tool and prompt inputs, and optionally sanitizes or blocks them. It uses simple, safe heuristics without full SQL parsing.

**Location:** `plugins/sql_sanitizer/`

**Version:** 0.1.0

**Author:** ContextForge

## Capabilities

- **Strip comments** - Removes `--` line comments and `/* */` block comments from SQL queries
- **Block dangerous statements** - Detects and blocks: DROP, TRUNCATE, ALTER, GRANT, REVOKE (configurable via regex patterns)
- **Detect missing WHERE clauses** - Flags DELETE and UPDATE statements that lack WHERE clauses
- **Interpolation detection** - Heuristic detection of non-parameterized queries (e.g., string concatenation with `+`, `%`, or f-string patterns)

## Hooks

- `prompt_pre_fetch` - Scans prompt arguments before fetching results
- `tool_pre_invoke` - Scans tool arguments before invocation

## Configuration

```yaml
- name: "SQLSanitizer"
  kind: "plugins.sql_sanitizer.sql_sanitizer.SQLSanitizerPlugin"
  mode: "enforce"  # or "disabled"
  priority: 45
  hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
  config:
    fields: ["sql", "query", "statement"]  # Which args to scan (null = all strings)
    strip_comments: true                    # Remove SQL comments
    block_delete_without_where: true        # Block DELETE without WHERE
    block_update_without_where: true        # Block UPDATE without WHERE
    require_parameterization: false         # Require parameterized queries
    blocked_statements:                     # Regex patterns for blocked statements
      - "\\bDROP\\b"
      - "\\bTRUNCATE\\b"
      - "\\bALTER\\b"
      - "\\bGRANT\\b"
      - "\\bREVOKE\\b"
    block_on_violation: true                # Block execution on violations
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `fields` | `list[str] \| null` | `null` | Argument field names to scan for SQL. If `null`, all string arguments are scanned. |
| `strip_comments` | `bool` | `true` | Remove SQL comments (`--` and `/* */`) from queries. |
| `block_delete_without_where` | `bool` | `true` | Block DELETE statements without WHERE clauses. |
| `block_update_without_where` | `bool` | `true` | Block UPDATE statements without WHERE clauses. |
| `require_parameterization` | `bool` | `false` | Require parameterized queries; flag string interpolation patterns. |
| `blocked_statements` | `list[str]` | See above | List of regex patterns (case-insensitive) for blocked SQL statements. |
| `block_on_violation` | `bool` | `true` | If `true`, block execution on violations. If `false`, report issues in metadata but allow execution. |

## Behavior

### On Violation

When `block_on_violation: true`:
- Returns `PluginViolation` with reason "Risky SQL detected"
- Sets `continue_processing: false` to block execution
- Includes details with list of issues found

When `block_on_violation: false`:
- Allows execution to continue
- Reports issues in metadata as `{"sql_issues": [...]}`

### On Sanitization

When comments are stripped:
- Returns modified payload with cleaned SQL
- Sets metadata flag `{"sql_sanitized": true}`

## Implementation Details

### Detection Logic

1. **Comment stripping** - Uses regex to remove `--` line comments and `/* */` block comments
2. **Statement blocking** - Matches blocked regex patterns against SQL (case-insensitive)
3. **WHERE clause detection** - Checks for presence of WHERE in DELETE/UPDATE statements
4. **Interpolation heuristics** - Detects patterns like:
   - String concatenation with `+`
   - Format strings with `%`
   - F-string patterns with `{` and `}`

### Performance Optimizations

- Precompiled regex patterns for common operations
- Pattern compilation cached in config validator

## Current Status

- **Enabled in default config:** No (`mode: disabled` in `plugins/config.yaml`)
- **Priority:** 45
- **Test coverage:** Present in unit test fixtures

## Usage Notes

- Uses simple heuristics (no full SQL parsing) - may have false positives/negatives
- For strict enforcement, combine with SchemaGuard plugin and policy engines
- Recommended for MCP servers that accept SQL queries as tool arguments
- Consider enabling in environments where SQL injection is a concern

## Example Violations

```
Blocked statement matched: \bDROP\b
Blocked statement matched: \bTRUNCATE\b
DELETE without WHERE clause
UPDATE without WHERE clause
Possible non-parameterized interpolation detected
```

## Files

- `plugins/sql_sanitizer/sql_sanitizer.py` - Main plugin implementation
- `plugins/sql_sanitizer/__init__.py` - Package init
- `plugins/sql_sanitizer/README.md` - Plugin documentation
- `plugins/sql_sanitizer/plugin-manifest.yaml` - Plugin metadata
- `plugins/config.yaml` - Default configuration (disabled by default)

---

## How to Enable

### Step 1: Enable the Plugin Framework

Set the following environment variable in your `.env` file:

```bash
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

### Step 2: Enable the SQL Sanitizer Plugin

Edit `plugins/config.yaml` and change the SQL Sanitizer mode from `disabled` to `enforce` or `permissive`:

```yaml
# SQL Sanitizer - detect dangerous SQL patterns in inputs
- name: "SQLSanitizer"
  kind: "plugins.sql_sanitizer.sql_sanitizer.SQLSanitizerPlugin"
  description: "Detects risky SQL and optionally strips comments or blocks"
  version: "0.1.0"
  author: "ContextForge"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
  tags: ["security", "sql", "validation"]
  mode: "enforce"  # Change from "disabled" to "enforce" or "permissive"
  priority: 45
  conditions: []
  config:
    fields: ["sql", "query", "statement"]
    blocked_statements: ["\\bDROP\\b", "\\bTRUNCATE\\b", "\\bALTER\\b", "\\bGRANT\\b", "\\bREVOKE\\b"]
    block_delete_without_where: true
    block_update_without_where: true
    strip_comments: true
    require_parameterization: false
    block_on_violation: true
```

**Mode options:**
- `enforce` - Block execution on violations (recommended for production)
- `permissive` - Log violations but allow execution (recommended for testing)
- `disabled` - Plugin is inactive

### Step 3: Restart the Gateway

```bash
# Development
make dev

# Production
make serve
```

Verify the plugin is loaded by checking the logs or visiting the Admin UI plugins page.

---

## How to Test

### Method 0: Using the Setup Script (Recommended for Docker)

If you're running in Docker Compose, use the provided setup script to register servers and create virtual servers with tools:

```bash
# Using docker-compose with testing profile (includes fast_test_server)
docker compose --profile testing up -d

# The register_fast_test service will automatically:
# 1. Register the fast_test_server gateway
# 2. Wait for tools to sync
# 3. Create a virtual server with all tools

# Or run the standalone script manually:
./scripts/create-tools.sh \
  --gateway-url http://localhost:4444 \
  --server-name fast_test \
  --server-url http://localhost:8880/mcp \
  --transport STREAMABLEHTTP
```

This script handles all the setup automatically. After running, you can test the SQL Sanitizer with the created tools.

### Method 1: Unit Tests (Automated)

The SQL Sanitizer is included in the plugin test suite. Run:

```bash
# Run all plugin tests
pytest tests/unit/mcpgateway/plugins/plugins/test_init_hooks_plugins.py -v

# Run specific SQL Sanitizer tests
pytest tests/unit/mcpgateway/plugins/plugins/test_init_hooks_plugins.py -v -k "SQLSanitizer"
```

### Method 2: Manual API Testing

#### Test 1: Block DROP Statement

```bash
# Create a tool that accepts SQL
curl -X POST http://localhost:4444/api/tools \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-sql-tool",
    "description": "Test SQL tool",
    "url": "http://example.com/execute",
    "integration_type": "HTTP",
    "request_type": "POST",
    "args": {
      "sql": {"type": "string", "description": "SQL query"}
    }
  }'

# Invoke with dangerous SQL (should be blocked)
curl -X POST http://localhost:4444/api/tools/test-sql-tool/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "DROP TABLE users"
  }'
```

**Expected result:** Request blocked with error "Risky SQL detected"

#### Test 2: Block DELETE without WHERE

```bash
curl -X POST http://localhost:4444/api/tools/test-sql-tool/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "DELETE FROM users"
  }'
```

**Expected result:** Request blocked with "DELETE without WHERE clause"

#### Test 3: Safe SQL with Comments (comments stripped)

```bash
curl -X POST http://localhost:4444/api/tools/test-sql-tool/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM users WHERE id = 1 -- comment here"
  }'
```

**Expected result:** Request allowed, comments stripped from SQL

#### Test 4: Safe SQL with WHERE Clause

```bash
curl -X POST http://localhost:4444/api/tools/test-sql-tool/invoke \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "DELETE FROM users WHERE id = 1"
  }'
```

**Expected result:** Request allowed (has WHERE clause)

### Method 3: Using MCP Client

If you have an MCP server registered that accepts SQL:

```python
from mcp import ClientSession
import asyncio

async def test_sql_sanitizer():
    async with ClientSession(...) as session:
        # This should be blocked
        try:
            await session.call_tool("your-sql-tool", sql="DROP TABLE test")
        except Exception as e:
            print(f"Blocked: {e}")
        
        # This should succeed
        result = await session.call_tool("your-sql-tool", sql="SELECT 1")
        print(f"Success: {result}")

asyncio.run(test_sql_sanitizer())
```

### Method 4: Check Plugin Logs

Enable detailed logging to see plugin activity:

```bash
# In .env
LOG_LEVEL=DEBUG
PLUGINS_ENABLED=true
```

Then watch for plugin activity:

```bash
make dev 2>&1 | grep -i "sql_sanitizer\|SQLSanitizer"
```

Expected log entries:
- `SQLSanitizer: Risky SQL detected in tool args`
- `SQLSanitizer: Blocked statement matched: \bDROP\b`
- `SQLSanitizer: sql_sanitized=True`

---

## Troubleshooting

### Plugin Not Loading

1. Verify `PLUGINS_ENABLED=true` in `.env`
2. Check `PLUGINS_CONFIG_FILE` points to correct path
3. Ensure `plugins/sql_sanitizer/` directory exists
4. Check logs for import errors

### Plugin Not Blocking

1. Verify `mode: "enforce"` in config
2. Verify `block_on_violation: true`
3. Check if the SQL field name matches `fields` config (default: `sql`, `query`, `statement`)
4. Try setting `fields: null` to scan all string arguments

### False Positives

If legitimate SQL is being blocked:

1. Customize `blocked_statements` to remove overly broad patterns
2. Disable specific checks (e.g., `block_delete_without_where: false`)
3. Use `mode: "permissive"` to log without blocking
4. Add specific field names to `fields` to limit scanning scope

### Testing in Permissive Mode

For initial deployment, use `mode: "permissive"` to:
- Monitor what SQL is being flagged
- Avoid disrupting existing workflows
- Tune configuration before enforcing

Then switch to `mode: "enforce"` once confident in the configuration.
