# Gateway-Level Input Validation & Output Sanitization

This document describes the experimental security validation and sanitization features in MCP Gateway.

## Overview

The MCP Gateway includes an experimental validation layer that provides:

- **Input Validation**: Validates all inbound parameters (tool args, resource URIs, prompt vars)
- **Output Sanitization**: Sanitizes all outbound payloads before delivery
- **Path Traversal Defense**: Normalizes and confines resource paths to declared roots
- **Shell Injection Prevention**: Escapes or rejects dangerous shell metacharacters
- **SQL Injection Protection**: Validates parameters for SQL injection patterns

## Configuration

Enable experimental validation by setting:

```bash
EXPERIMENTAL_VALIDATE_IO=true
VALIDATION_STRICT=true          # Reject on violations (default: true)
SANITIZE_OUTPUT=true           # Sanitize output (default: true)
ALLOWED_ROOTS="/srv/data,/tmp" # Allowed root paths for resources
MAX_PATH_DEPTH=10              # Maximum path depth (default: 10)
MAX_PARAM_LENGTH=10000         # Maximum parameter length (default: 10000)
```

## Validation Rules

### Path Traversal Defense

Resource paths are validated against:
- Path traversal patterns (`../`, `..\\`)
- Allowed root directories
- Maximum path depth

Example:
```python
# BLOCKED: Path traversal
"/srv/data/../../etc/passwd"

# ALLOWED: Within allowed root
"/srv/data/file.txt"
```

### Dangerous Parameter Validation

Parameters are checked for:
- Shell metacharacters: `;`, `&`, `|`, `` ` ``, `$`, `()`, `{}`, `[]`, `<>` 
- SQL injection patterns: quotes, comments, SQL keywords
- Control characters: ASCII 0x00-0x1F, 0x7F-0x9F

### Output Sanitization

All text output is sanitized to remove:
- Control characters (except newlines and tabs)
- Escape sequences that could affect terminals
- Invalid UTF-8 sequences

## Security Patterns

### Tool Parameter Validation

```python
from mcpgateway.validators import SecurityValidator

# Validate shell parameters
safe_filename = SecurityValidator.validate_shell_parameter("file.txt")

# Validate SQL parameters  
safe_query = SecurityValidator.validate_sql_parameter("user input")

# Validate parameter length
SecurityValidator.validate_parameter_length(value, max_length=1000)
```

### Resource Path Validation

```python
# Validate and normalize paths
safe_path = SecurityValidator.validate_path(
    "/srv/data/file.txt", 
    allowed_roots=["/srv/data"]
)
```

### Output Sanitization

```python
from mcpgateway.validators import OutputSanitizer

# Sanitize text output
clean_text = OutputSanitizer.sanitize_text("Hello\x1b[31mWorld")
# Result: "HelloWorld"

# Sanitize JSON responses
clean_data = OutputSanitizer.sanitize_json_response({
    "message": "Hello\x00World",
    "items": ["test\x1f", "clean"]
})
```

## Validation Modes

### Strict Mode (Default)
- Rejects requests with dangerous patterns
- Returns HTTP 422 validation errors
- Logs all violations

### Non-Strict Mode
- Attempts to sanitize dangerous input
- Logs warnings for violations
- Continues processing when possible

## Error Responses

Validation failures return structured errors:

```json
{
  "detail": "Parameter filename contains dangerous characters",
  "type": "validation_error",
  "code": "dangerous_input"
}
```

## Performance Impact

The validation middleware adds minimal overhead:
- ~1-2ms per request for parameter validation
- ~0.5ms per response for output sanitization
- Regex compilation is cached for performance

## Testing

Run validation tests:

```bash
pytest tests/security/test_validation.py -v
```

## Limitations

Current limitations of the experimental validation:
- Binary content validation is basic
- Some legitimate use cases may be blocked
- Performance impact on large payloads
- Limited to common attack patterns

## Future Enhancements

Planned improvements:
- Machine learning-based anomaly detection
- Configurable validation rules per tool
- Integration with external security scanners
- Support for custom validation plugins

## Security Considerations

This validation layer provides defense-in-depth but should not be the only security measure:

- Always use proper authentication and authorization
- Implement rate limiting and request throttling  
- Monitor and log all security events
- Keep the gateway and dependencies updated
- Use network-level security controls

## Reporting Issues

If you find security issues or false positives, please report them following our Security Policy.