# Input Validation & Output Sanitization

## Overview

ContextForge provides comprehensive input validation and output sanitization to protect against common security vulnerabilities including:

- **Path Traversal**: Prevents access to files outside allowed directories
- **Command Injection**: Blocks shell metacharacters in parameters
- **SQL Injection**: Validates and escapes SQL parameters
- **XSS Attacks**: Sanitizes output to remove dangerous content
- **Control Character Injection**: Removes ANSI escape sequences and control characters

## Configuration

### Environment Variables

```bash
# Enable experimental validation (default: false)
EXPERIMENTAL_VALIDATE_IO=true

# Deprecated global validation middleware (default: false)
VALIDATION_MIDDLEWARE_ENABLED=true

# Strict mode - reject on violations (default: true)
VALIDATION_STRICT=true

# Sanitize output responses (default: true)
SANITIZE_OUTPUT=true

# Allowed root paths for resource access (JSON array or comma-separated)
ALLOWED_ROOTS='["/srv/data", "/var/app"]'

# Maximum path depth (default: 10)
MAX_PATH_DEPTH=10

# Maximum parameter length (default: 10000)
MAX_PARAM_LENGTH=10000

# Dangerous patterns (regex, JSON array)
DANGEROUS_PATTERNS='["[;&|`$(){}\\[\\]<>]", "\\.\\.[\\\/]", "[\\x00-\\x1f\\x7f-\\x9f]"]'
```

### Roll-out Phases

The validation feature supports a phased roll-out approach:

#### Phase 0: Feature Flag (Off by Default)
```bash
EXPERIMENTAL_VALIDATE_IO=false  # Disabled in production
```

#### Phase 1: Log-Only Mode (Dev/Staging)
```bash
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_STRICT=false  # Warn only, don't block
```

#### Phase 2: Enforce in Staging
```bash
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_STRICT=true  # Block violations
```

#### Phase 3: Production Deployment
```bash
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_STRICT=true
SANITIZE_OUTPUT=true
```

## Validation Rules

### Path Traversal Defense

**Scenario**: Reject resource path traversal

```python
# Configuration
MCP_GW_ROOT="/srv/data"

# Attack attempt
uri = "/srv/data/../../secret.txt"

# Result: 400 "invalid_path: Path traversal detected"
# No files outside "/srv/data" are accessed
```

**Implementation**:

- Normalizes paths using `Path.resolve()`
- Checks for `..` sequences
- Validates against `ALLOWED_ROOTS`
- Enforces `MAX_PATH_DEPTH` limit

### Command Injection Prevention

**Scenario**: Prevent command injection via filename

```python
# Tool that shells out with filename parameter
filename = "bobbytables.jpg; cat /etc/passwd"

# Strict mode: Rejects with 422 "validation_failed"
# Non-strict mode: Escapes value using shlex.quote()
```

**Protected Patterns**:

- Shell metacharacters: `; & | \` $ ( ) { } [ ] < >`
- Command chaining: `&&`, `||`, `;`
- Pipe operators: `|`
- Backticks and command substitution

### SQL Injection Prevention

**Scenario**: Validate SQL parameters

```python
# Dangerous input
param = "'; DROP TABLE users; --"

# Strict mode: Rejects with 422 "validation_failed"
# Non-strict mode: Escapes quotes
```

**Protected Patterns**:

- Quote characters: `'`, `"`
- SQL comments: `--`, `/* */`
- SQL keywords: `UNION`, `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DROP`

### Output Sanitization

**Scenario**: Sanitize tool output

```python
# Tool returns text with control characters
output = "Result: \x1b[31mError\x1b[0m\x00"

# Sanitized output
clean = "Result: Error"

# Control chars removed, Content-Type verified
```

**Sanitization Rules**:

- Removes C0 control characters (0x00-0x1F) except newlines/tabs
- Removes ANSI escape sequences
- Removes C1 control characters (0x7F-0x9F)
- Preserves `\n` (newline) and `\t` (tab)
- Verifies Content-Type matches payload

### Tool Description Content Validation

**Scenario**: control which tools a gateway accepts, from a global default down to a single tool

Every tool is checked against a **tool validation policy** before it is stored. A policy is a
[CEL](https://cel.dev) expression that evaluates to `true` when the tool is acceptable. Three levels can
hold one, and the most specific level wins:

| Level | Where it lives | Set by |
|-------|----------------|--------|
| Tool | `tool_validation_policy` on the tool | Tool create/edit form, `POST /tools`, `PUT /tools/{id}` |
| Gateway | `tool_validation_policy` on the gateway | Gateway create/edit form, `POST /gateways`, `PUT /gateways/{id}` |
| Global | `TOOL_DESCRIPTION_FORBIDDEN_PATTERNS` settings | Environment |

An empty policy at a level means **inherit**: a tool without one uses its gateway's, a gateway without one
uses the global settings. The levels replace each other, they do not combine. A gateway policy that allows
`&&` admits a tool the global list would refuse, and a tool policy that allows the tool overrides both.

The global settings compile into the expression `!(description.contains("&&") || ...)`, one `contains` per
listed pattern, so the shipped behaviour is unchanged when no policy is stored.

**Who can set a policy**: creating or changing `tool_validation_policy` on a tool or a gateway, through the
API, the Admin UI, or an import, requires the `validation_policy.manage` permission. Platform administrators
hold it everywhere and team administrators hold it for records of their shared teams. A personal team never
counts, because every user is its administrator. Grant the permission to a custom role for anyone else. Resubmitting the stored policy unchanged is not a change.
Every change writes an audit trail entry (`set_tool_validation_policy` or `set_gateway_validation_policy`)
with the old and new expressions.

**Variables available to an expression**:

| Variable | Value |
|----------|-------|
| `description` | The tool description, as text. Empty when the tool has none. |
| `tool_name` | The upstream tool name, without the gateway prefix. |

**Examples**:

```text
# Refuse any description that mentions SQL
!description.contains("SQL")

# Case-insensitive variant
!description.matches("(?i)sql")

# Admit exactly one tool, whatever its description says
tool_name == "ping"

# Keep the global shell-operator check but allow blockquotes
!(description.contains("&&") || description.contains("$("))
```

`contains` is case-sensitive. Use `matches` with `(?i)` for case-insensitive checks. An expression must
reference only the two variables above and must return a boolean; anything else is rejected when the policy
is saved, with the parser's message.

**What a refusal does**:

- **Tools discovered from a gateway** (registration, refresh, reactivation) are stored **disabled**, with the
  reason in the tool's `validation_refusal` field, for example `denied by the gateway-level validation policy`.
  They are not served to clients, cannot be invoked, and cannot be enabled by hand until the policy allows
  them. They are not deleted, so their virtual-server membership, metrics, and any tool-level policy survive.
  The next refresh re-evaluates every tool and re-enables those the policy now allows.
- **Tools created through the API or the Admin UI** are rejected with HTTP 400, because there is no row to
  disable yet.
- **Editing a tool's description or policy** always saves. The policy result only decides whether the tool is
  enabled afterwards, exactly as a refresh would. Clearing a tool-level policy on a tool its gateway refuses
  therefore disables it again.
- **Changing a gateway's policy** re-checks every stored tool of that gateway from its saved descriptions at
  once, without contacting the upstream, so a tightened policy takes effect even while the server is down.
- **A policy that cannot be evaluated** counts as a refusal, so a broken policy or a failed check never lets a
  tool through unchecked. A syntax error, an unknown variable, or a non-boolean result refuses at once. A sandbox
  that is busy or unavailable is retried once, then refuses; the stored reason names the level and the log line
  carries the cause. The next refresh or edit re-evaluates the tool.

Gateway refreshes evaluate the description reported by the upstream server. Edits in the gateway evaluate
the stored description and, when an operator has customised it, the upstream text as well.

**Control variables**:

| Variable | Default | Effect |
|----------|---------|--------|
| `TOOL_DESCRIPTION_FORBIDDEN_PATTERNS_ENABLED` | `true` | Master switch for the global default. Does not affect gateway or tool policies. |
| `TOOL_DESCRIPTION_FORBIDDEN_PATTERNS` | `["&&", "||", "$(", "> ", "< "]` | Substrings the global default refuses (JSON array) |
| `VALIDATION_STRICT` | `true` | When `false`, a refused tool is logged as a warning and stored enabled |
| `CEL_EXECUTION` | `subprocess` | `subprocess` evaluates policies in the forked sandbox; `inprocess` disables it |
| `CEL_TIMEOUT_SECONDS` | `1.0` | Wall-clock limit for one evaluation, at most `1.0` |
| `CEL_WORKERS` | `2` | Sandbox worker processes per gateway process |

Note: single pipes (`|`), semicolons (`;`), and backticks (`` ` ``) are not in the default list because they
commonly appear in natural-language documentation and Markdown tables.

!!! note "Upgrade note (v0.9.0 → v1.0.0.Beta2)"
    The forbidden-pattern check was introduced in v1.0.0.Beta2. If you are upgrading from v0.9.0 and your MCP servers expose tools with Markdown descriptions, set a gateway policy that allows the characters your tools use, customise `TOOL_DESCRIPTION_FORBIDDEN_PATTERNS`, or set `VALIDATION_STRICT=false`.

### JSON Schema Validation

**Scenario**: Validate tool and prompt schemas during registration

```python
# Tool registration with invalid schema
tool = {
    "name": "invalid_tool",
    "inputSchema": {
        "type": "object",
        "properties": {"arg": {"type": "unknown_type"}} # Invalid type
    }
}

# Strict mode (Default): Rejects with 400 Bad Request
# Non-strict mode: Logs warning but accepts registration
```

**Control variable**: `JSON_SCHEMA_VALIDATION_STRICT` (default: `true`)

**Validation Rules**:
- Enforces valid JSON Schema 2020-12 (default)
- Validates structural integrity of `inputSchema` for tools
- Validates `arguments` schema for tool prompts
- prevents registration of broken tools that would fail at runtime

## API Usage

### SecurityValidator Class

```python
from mcpgateway.common.validators import SecurityValidator

# Validate shell parameters
safe_param = SecurityValidator.validate_shell_parameter("filename.txt")

# Validate paths
safe_path = SecurityValidator.validate_path("/srv/data/file.txt", ["/srv/data"])

# Validate SQL parameters
safe_sql = SecurityValidator.validate_sql_parameter("user_input")

# Sanitize output
clean_text = SecurityValidator.sanitize_text("Text\x1b[31mwith\x1b[0mcolors")

# Sanitize JSON responses
clean_data = SecurityValidator.sanitize_json_response({
    "message": "Hello\x1bWorld",
    "items": ["test\x00", "clean"]
})
```

### ValidationMiddleware

!!! warning "Deprecated as of 2026-06-11; sunsets on 2026-07-07"
    `ValidationMiddleware` is deprecated. Prefer endpoint-level Pydantic
    validation, `SecurityValidator` helpers, and protocol-specific validation
    middleware. See [Deprecations](../deprecations.md).

The middleware automatically validates all incoming requests when enabled:

```python
# In main.py
from mcpgateway.middleware.validation_middleware import ValidationMiddleware

if settings.validation_middleware_enabled:
    app.add_middleware(ValidationMiddleware)
```

## Testing

### Unit Tests

```python
import pytest
from mcpgateway.common.validators import SecurityValidator

def test_path_traversal_blocked():
    """Test path traversal is blocked."""
    with pytest.raises(ValueError, match="Path traversal"):
        SecurityValidator.validate_path("../../../etc/passwd")

def test_command_injection_blocked():
    """Test command injection is blocked."""
    with pytest.raises(ValueError, match="shell metacharacters"):
        SecurityValidator.validate_shell_parameter("file; rm -rf /")

def test_output_sanitization():
    """Test output sanitization removes control chars."""
    result = SecurityValidator.sanitize_text("Hello\x1b[31mWorld\x00")
    assert result == "HelloWorld"
```

### Integration Tests

```bash
# Test path traversal protection
curl -X POST http://localhost:4444/resources \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"uri": "../../../etc/passwd"}'
# Expected: 400 Bad Request

# Test command injection protection
curl -X POST http://localhost:4444/tools/call \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "convert", "arguments": {"file": "test; cat /etc/passwd"}}'
# Expected: 422 Validation Failed (strict mode)
```

## Metrics & Monitoring

### Log Messages

```
[VALIDATION] Input validation failed: Parameter contains shell metacharacters
[VALIDATION] Path traversal detected: ../../../etc/passwd
[SECURITY] Path validation failed: Path outside allowed roots
```

### Prometheus Metrics

```
# Validation failures
mcpgateway_validation_failures_total{type="path_traversal"} 5
mcpgateway_validation_failures_total{type="command_injection"} 2
mcpgateway_validation_failures_total{type="sql_injection"} 1

# Sanitization operations
mcpgateway_sanitization_operations_total{type="output"} 1234
```

## Security Best Practices

### 1. Enable Endpoint and Protocol Validation in Production

Use endpoint-level Pydantic validation and protocol-specific validation in production.
Keep the deprecated global validation middleware disabled unless an existing deployment depends on it:

```bash
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_MIDDLEWARE_ENABLED=false
VALIDATION_STRICT=true
SANITIZE_OUTPUT=true
```

### 2. Configure Allowed Roots

Restrict resource access to specific directories:

```bash
ALLOWED_ROOTS='["/srv/data", "/var/app/uploads"]'
```

### 3. Use Strict Mode

Enable strict mode to reject invalid input:

```bash
VALIDATION_STRICT=true
```

### 4. Monitor Validation Failures

Set up alerts for validation failures:

```yaml
# Prometheus alert
- alert: HighValidationFailureRate
  expr: rate(mcpgateway_validation_failures_total[5m]) > 10
  annotations:
    summary: "High rate of validation failures detected"
```

### 5. Regular Security Audits

Review validation logs regularly:

```bash
# Check for validation failures
grep "VALIDATION" /var/log/mcpgateway.log | tail -100

# Check for security warnings
grep "SECURITY" /var/log/mcpgateway.log | tail -100
```

## Troubleshooting

### Issue: Legitimate Paths Blocked

**Symptom**: Valid file paths are rejected

**Solution**: Add path to `ALLOWED_ROOTS`:

```bash
ALLOWED_ROOTS='["/srv/data", "/var/app", "/opt/resources"]'
```

### Issue: MCP Server Tools Fail to Register with "unsafe characters" Error

**Symptom**:
```
All N tools failed validation. First error: Validation failed for tool 'X':
[{'type': 'value_error', 'loc': ('description',),
  'msg': "Value error, Description contains unsafe characters: '> '", ...}]
```

**Cause**: The tool's `description` field contains a shell metacharacter (`> `, `< `, `&&`, `||`, `$(`) that is blocked by default. This is common with Markdown-formatted descriptions. Note: single pipes (`|`), semicolons (`;`), and backticks (`` ` ``) are allowed as they commonly appear in natural-language documentation.

**Solution** (pick one):

```bash
# Option 1: Customize the pattern list to allow specific characters
TOOL_DESCRIPTION_FORBIDDEN_PATTERNS=["&&", "||", "$("]

# Option 2: Disable pattern checks entirely
TOOL_DESCRIPTION_FORBIDDEN_PATTERNS_ENABLED=false

# Option 3: Warn-only mode (log but don't reject)
VALIDATION_STRICT=false
```

**Note**: `EXPERIMENTAL_VALIDATE_IO=false` and `JSON_SCHEMA_VALIDATION_STRICT=false` do **not** affect this check — only `VALIDATION_STRICT` and `TOOL_DESCRIPTION_FORBIDDEN_PATTERNS_ENABLED` do.

### Issue: Tool Parameters Escaped

**Symptom**: Tool receives escaped parameters

**Solution**: Disable strict mode for specific tools or use non-strict mode:

```bash
VALIDATION_STRICT=false  # Escape instead of reject
```

### Issue: Output Appears Corrupted

**Symptom**: Output missing formatting

**Solution**: Control characters were sanitized. This is expected behavior for security.

## Upstream Spec Proposal

### Validation Clause

> Servers MUST treat all inbound values as untrusted and validate them against JSON Schema or allow-lists.

### Path-Safety Clause

> Resource paths MUST resolve inside configured roots; otherwise reject with 400 status.

### Dangerous-Sink Clause

> Parameters passed to shells/SQL MUST be escaped or rejected to prevent injection attacks.

### Output-Sanitization Clause

> Before emission, servers SHOULD strip control chars and MUST ensure MIME correctness.

## References

- [OWASP Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
- [OWASP Command Injection](https://owasp.org/www-community/attacks/Command_Injection)
- [OWASP SQL Injection](https://owasp.org/www-community/attacks/SQL_Injection)
- [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html)
- [CWE-78: OS Command Injection](https://cwe.mitre.org/data/definitions/78.html)
- [CWE-89: SQL Injection](https://cwe.mitre.org/data/definitions/89.html)
