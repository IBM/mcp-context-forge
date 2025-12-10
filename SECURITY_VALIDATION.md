# Gateway-Level Input Validation & Output Sanitization

## Overview

This document describes the implementation of comprehensive security validation and sanitization features for the MCP Gateway, addressing the requirements specified in the feature specification.

## Implementation Summary

### Components Added/Modified

1. **ValidationMiddleware** (`mcpgateway/middleware/validation_middleware.py`)
   - Enhanced with improved path validation
   - Added support for URI scheme detection
   - Improved logging for security events
   - Phase-based roll-out support

2. **SecurityValidator** (`mcpgateway/common/validators.py`)
   - Comprehensive validation methods for:
     - Shell parameters (command injection prevention)
     - File paths (traversal attack prevention)
     - SQL parameters (SQL injection prevention)
     - Output sanitization (control character removal)
     - XSS prevention (HTML/JavaScript detection)
     - SSTI prevention (template injection detection)
     - MIME type validation

3. **Service Layer Validation**
   - **ToolService** (`mcpgateway/services/tool_service.py`)
     - Validates tool name, description, URL, and path_template
     - Prevents XSS, command injection, and path traversal
   - **PromptService** (`mcpgateway/services/prompt_service.py`)
     - Validates prompt name, description, and template
     - Prevents XSS, command injection, and SSTI
   - **ResourceService** (`mcpgateway/services/resource_service.py`)
     - Validates resource name, description, URI, and MIME type
     - Prevents XSS, command injection, path traversal, and invalid MIME types

4. **Configuration** (`mcpgateway/config.py`, `.env.example`)
   - New settings for validation control
   - Configurable security patterns
   - Roll-out phase support

5. **Tests** (`tests/security/test_validation.py`)
   - Comprehensive test coverage for:
     - Path traversal detection
     - Command injection prevention
     - SQL injection prevention
     - Output sanitization
     - Middleware behavior

6. **Documentation**
   - `docs/docs/best-practices/input-validation.md` - Complete feature guide
   - `docs/docs/best-practices/validation-cookbook.md` - Practical examples

## Security Features

### 1. Path Traversal Defense

**User Story**: As a platform security engineer, I want the gateway to normalize and confine all resource paths to declared roots so that traversal payloads like `../../../etc/passwd` are blocked before any file I/O.

**Implementation**:
```python
# Configuration
ALLOWED_ROOTS=["/srv/data"]

# Attack attempt
uri = "/srv/data/../../secret.txt"

# Result: 400 "invalid_path: Path traversal detected"
```

**Key Features**:
- Normalizes paths using `Path.resolve()`
- Checks for `..` sequences
- Validates against `ALLOWED_ROOTS`
- Enforces `MAX_PATH_DEPTH` limit
- Skips validation for URI schemes (http://, plugin://)

### 2. Command Injection Prevention

**User Story**: As a tool developer, I want the runtime to escape or reject shell/SQL metas in parameters so that `"bobbytables.jpg; cat /etc/passwd"` cannot trigger command injection.

**Implementation**:
```python
# Dangerous input
filename = "bobbytables.jpg; cat /etc/passwd"

# Strict mode: Rejects with 422 "validation_failed"
# Non-strict mode: Escapes using shlex.quote()
```

**Protected Patterns**:
- Shell metacharacters: `; & | \` $ ( ) { } [ ] < >`
- Command chaining: `&&`, `||`, `;`
- Pipe operators: `|`
- Backticks and command substitution

### 3. Output Sanitization

**User Story**: As a client integrator, I want control chars & mismatched MIME types stripped or fixed on every response so that hostile escape sequences aren't fed back into UIs or LLMs.

**Implementation**:
```python
# Tool returns text with control characters
output = "Result: \x1b[31mError\x1b[0m\x00"

# Sanitized output
clean = "Result: Error"
```

**Sanitization Rules**:
- Removes C0 control characters (0x00-0x1F) except newlines/tabs
- Removes ANSI escape sequences
- Removes C1 control characters (0x7F-0x9F)
- Preserves `\n` (newline) and `\t` (tab)
- Verifies Content-Type matches payload

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

# Allowed root paths (JSON array or comma-separated)
ALLOWED_ROOTS='["/srv/data", "/var/app"]'

# Maximum path depth (default: 10)
MAX_PATH_DEPTH=10

# Maximum parameter length (default: 10000)
MAX_PARAM_LENGTH=10000

# Dangerous patterns (regex, JSON array)
DANGEROUS_PATTERNS='["[;&|`$(){}\\[\\]<>]", "\\.\\.[\\\/]", "[\\x00-\\x1f\\x7f-\\x9f]"]'
```

### Roll-out Phases

#### Phase 0: Feature Flag (Off by Default)
```bash
EXPERIMENTAL_VALIDATE_IO=false  # Disabled
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
ALLOWED_ROOTS='["/srv/data"]'
```

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

### Running Tests

```bash
# Run all security validation tests
pytest tests/security/test_validation.py -v

# Run specific test
pytest tests/security/test_validation.py::TestSecurityValidator::test_path_traversal_blocked -v

# Run with coverage
pytest tests/security/test_validation.py --cov=mcpgateway.middleware.validation_middleware --cov=mcpgateway.common.validators
```

### Test Coverage

- Path traversal detection
- Command injection prevention
- SQL injection prevention
- Output sanitization
- Middleware behavior
- Configuration handling
- Error handling

## Acceptance Criteria

### ✅ User Story 1: Path Traversal Defense

- [x] Normalizes and confines resource paths to declared roots
- [x] Blocks traversal payloads like `../../../etc/passwd`
- [x] Returns 400 "invalid_path" on violations
- [x] Prevents file I/O outside allowed roots

### ✅ User Story 2: Command Injection Prevention

- [x] Escapes or rejects shell metacharacters
- [x] Prevents command injection via filename parameters
- [x] Returns 422 "validation_failed" in strict mode
- [x] Escapes values in non-strict mode
- [x] No unintended commands execute

### ✅ User Story 3: Output Sanitization

- [x] Removes control characters from responses
- [x] Strips ANSI escape sequences
- [x] Preserves newlines and tabs
- [x] Verifies Content-Type matches payload
- [x] Sanitizes nested JSON structures

## Upstream Spec Proposal

The following clauses are proposed for inclusion in the MCP specification:

### Validation Clause
> Servers MUST treat all inbound values as untrusted and validate them against JSON Schema or allow-lists.

### Path-Safety Clause
> Resource paths MUST resolve inside configured roots; otherwise reject with 400 status.

### Dangerous-Sink Clause
> Parameters passed to shells/SQL MUST be escaped or rejected to prevent injection attacks.

### Output-Sanitization Clause
> Before emission, servers SHOULD strip control chars and MUST ensure MIME correctness.

## Security Best Practices

1. **Enable Validation in Production**
   ```bash
   EXPERIMENTAL_VALIDATE_IO=true
   VALIDATION_STRICT=true
   SANITIZE_OUTPUT=true
   ```

2. **Configure Allowed Roots**
   ```bash
   ALLOWED_ROOTS='["/srv/data", "/var/app/uploads"]'
   ```

3. **Use Strict Mode**
   ```bash
   VALIDATION_STRICT=true
   ```

4. **Monitor Validation Failures**
   - Set up alerts for validation failures
   - Review logs regularly
   - Track metrics

5. **Regular Security Audits**
   - Review validation logs
   - Update dangerous patterns
   - Test with security tools

## Troubleshooting

### Issue: Legitimate Paths Blocked

**Solution**: Add path to `ALLOWED_ROOTS`:
```bash
ALLOWED_ROOTS='["/srv/data", "/var/app", "/opt/resources"]'
```

### Issue: Tool Parameters Escaped

**Solution**: Use non-strict mode:
```bash
VALIDATION_STRICT=false  # Escape instead of reject
```

### Issue: Output Appears Corrupted

**Solution**: Control characters were sanitized (expected behavior for security).

## References

- [OWASP Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
- [OWASP Command Injection](https://owasp.org/www-community/attacks/Command_Injection)
- [OWASP SQL Injection](https://owasp.org/www-community/attacks/SQL_Injection)
- [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html)
- [CWE-78: OS Command Injection](https://cwe.mitre.org/data/definitions/78.html)
- [CWE-89: SQL Injection](https://cwe.mitre.org/data/definitions/89.html)

## Next Steps

1. ✅ Spike the middleware + unit tests
2. ✅ Draft JSON Schemas for core built-in tools/resources
3. ⏳ Open PR to toggle `EXPERIMENTAL_VALIDATE_IO` in CI
4. ⏳ Share results with MCP working groups
5. ⏳ Iterate on spec language based on feedback

## Contributors

- Implementation: Amazon Q Developer
- Specification: Feature specification document
- Review: MCP Gateway maintainers
