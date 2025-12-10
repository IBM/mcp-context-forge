# Input Validation & Output Sanitization

## Overview

The MCP Gateway provides comprehensive input validation and output sanitization to protect against common security vulnerabilities including:

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

# Enable validation middleware (default: false)
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

### 1. Enable Validation in Production

Always enable validation in production environments:

```bash
EXPERIMENTAL_VALIDATE_IO=true
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
