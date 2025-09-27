
## 9. Error Handling

The plugin framework implements a comprehensive error handling system designed to provide clear error reporting, graceful degradation, and operational resilience. The system distinguishes between **technical errors** (plugin failures, timeouts, infrastructure issues) and **policy violations** (security breaches, content violations, access control failures).

### 9.1 Error Classification

The framework categorizes errors into distinct types, each with specific handling strategies:

#### 9.1.1 Technical Errors
**Definition**: Infrastructure, execution, or implementation failures that prevent plugins from operating correctly.

**Examples**:
- Plugin execution timeouts
- Network connectivity failures for external plugins
- Memory allocation errors
- Invalid plugin configuration
- Missing dependencies

**Characteristics**:
- Usually temporary and recoverable
- Don't necessarily indicate policy violations
- Can be retried or worked around
- Should not block valid requests in permissive mode

#### 9.1.2 Policy Violations
**Definition**: Detected violations of security policies, content rules, or access controls that indicate potentially harmful requests.

**Examples**:
- PII detection in request content
- Unauthorized access attempts
- Malicious file path traversal
- Content that violates safety policies
- Rate limit exceedances

**Characteristics**:
- Indicate intentional or accidental policy breaches
- Should typically block request processing
- Require human review or policy adjustment
- Generate security alerts and audit logs

#### 9.1.3 System Protection Errors
**Definition**: Framework-level protections that prevent resource exhaustion or system abuse.

**Examples**:
- Payload size limits exceeded
- Plugin execution timeout
- Memory usage limits
- Request rate limiting

### 9.2 Exception Hierarchy

The framework defines a structured exception hierarchy that enables precise error handling and reporting:

```python
class PluginError(Exception):
    """Base plugin framework exception for technical errors

    Used for: Plugin failures, configuration errors, infrastructure issues
    Behavior: Can be ignored in permissive mode, blocks in enforce mode
    """
    def __init__(self, message: str, error: Optional[PluginErrorModel] = None):
        self.error = error                     # Structured error details
        super().__init__(message)

class PluginViolationError(PluginError):
    """Plugin policy violation exception

    Used for: Security violations, policy breaches, content violations
    Behavior: Always blocks requests (except in permissive mode with logging)
    """
    def __init__(self, message: str, violation: Optional[PluginViolation] = None):
        self.violation = violation             # Structured violation details
        super().__init__(message)

class PluginTimeoutError(Exception):
    """Plugin execution timeout exception

    Used for: Plugin execution exceeds configured timeout
    Behavior: Treated as technical error, handled by plugin mode
    """
    pass

class PayloadSizeError(ValueError):
    """Payload size exceeds limits exception

    Used for: Request payloads exceeding size limits (default 1MB)
    Behavior: Immediate request rejection, security protection
    """
    pass
```

**Exception Hierarchy Usage Patterns**:

```python
# Technical error example
try:
    result = await external_service_call()
except ConnectionError as e:
    error_model = PluginErrorModel(
        message="Failed to connect to external service",
        code="CONNECTION_FAILED",
        details={"service_url": service_url, "timeout": 30},
        plugin_name=self.name
    )
    raise PluginError("External service unavailable", error=error_model)

# Policy violation example
if contains_pii(content):
    violation = PluginViolation(
        reason="Personal information detected",
        description="Content contains Social Security Numbers",
        code="PII_SSN_DETECTED",
        details={"pattern_count": 2, "confidence": 0.95}
    )
    raise PluginViolationError("PII violation", violation=violation)

# System protection example
if len(payload_data) > MAX_PAYLOAD_SIZE:
    raise PayloadSizeError(f"Payload size {len(payload_data)} exceeds limit {MAX_PAYLOAD_SIZE}")
```

### 9.3 Error Models

The framework uses structured data models to capture comprehensive error information for debugging, monitoring, and audit purposes:

#### 9.3.1 PluginErrorModel

```python
class PluginErrorModel(BaseModel):
    """Structured technical error information"""
    message: str                               # Human-readable error description
    code: Optional[str] = ""                   # Machine-readable error code
    details: Optional[dict[str, Any]] = Field(default_factory=dict) # Additional context
    plugin_name: str                           # Plugin that generated error
```

**PluginErrorModel Usage**:
- **message**: Clear, actionable description for developers and operators
- **code**: Standardized error codes for programmatic handling and monitoring
- **details**: Structured context for debugging (configuration, inputs, state)
- **plugin_name**: Attribution for error tracking and plugin health monitoring

**Example Error Codes**:
- `CONNECTION_TIMEOUT`: External service connection timeout
- `INVALID_CONFIGURATION`: Plugin configuration validation failure
- `DEPENDENCY_MISSING`: Required dependency not available
- `SERVICE_UNAVAILABLE`: External service temporarily unavailable
- `AUTHENTICATION_FAILED`: External service authentication failure

#### 9.3.2 PluginViolation

```python
class PluginViolation(BaseModel):
    """Plugin policy violation details"""
    reason: str                                # High-level violation category
    description: str                           # Detailed human-readable description
    code: str                                  # Machine-readable violation code
    details: dict[str, Any]                    # Structured violation context
    _plugin_name: str = PrivateAttr(default="") # Plugin attribution (set by manager)

    @property
    def plugin_name(self) -> str:
        """Get plugin name that detected violation"""
        return self._plugin_name

    @plugin_name.setter
    def plugin_name(self, name: str) -> None:
        """Set plugin name (used by plugin manager)"""
        self._plugin_name = name
```

**PluginViolation Usage**:
- **reason**: Broad category for violation (e.g., "Unauthorized access", "Content violation")
- **description**: Detailed explanation suitable for audit logs and user feedback
- **code**: Specific violation identifier for policy automation and reporting
- **details**: Structured data for analysis, metrics, and investigation
- **plugin_name**: Attribution for violation source tracking

**Example Violation Codes**:
- `PII_DETECTED`: Personal identifiable information found
- `ACCESS_DENIED`: User lacks required permissions
- `PATH_TRAVERSAL`: Attempted directory traversal attack
- `RATE_LIMIT_EXCEEDED`: Request rate exceeds policy limits
- `CONTENT_BLOCKED`: Content violates safety policies
- `MALICIOUS_PATTERN`: Known attack pattern detected

#### 9.3.3 Error Model Examples

```python
# Comprehensive technical error
technical_error = PluginErrorModel(
    message="OpenAI API request failed with rate limit error",
    code="EXTERNAL_API_RATE_LIMITED",
    details={
        "api_endpoint": "https://api.openai.com/v1/moderations",
        "response_code": 429,
        "retry_after": 60,
        "request_id": "req_abc123",
        "usage_info": {
            "requests_this_minute": 60,
            "limit_per_minute": 60
        }
    },
    plugin_name="OpenAIModerationPlugin"
)

# Detailed policy violation
security_violation = PluginViolation(
    reason="Suspicious file access attempt",
    description="User attempted to access system configuration file outside allowed directory",
    code="PATH_TRAVERSAL_BLOCKED",
    details={
        "requested_path": "../../../etc/passwd",
        "normalized_path": "/etc/passwd",
        "user_id": "user_12345",
        "allowed_paths": ["/app/data", "/tmp/uploads"],
        "risk_level": "HIGH",
        "detection_method": "path_validation"
    }
)
# plugin_name set automatically by PluginManager
```

### 9.4 Error Handling Strategy

The framework implements a comprehensive error handling strategy that adapts behavior based on both global plugin settings and individual plugin modes. This dual-layer approach enables fine-grained control over error handling while maintaining operational flexibility.

#### 9.4.1 Global Plugin Settings

The `PluginSettings` class controls framework-wide error handling behavior:

```python
class PluginSettings(BaseModel):
    fail_on_plugin_error: bool = False         # Continue on plugin errors globally
    plugin_timeout: int = 30                   # Per-plugin timeout in seconds
```

**fail_on_plugin_error**:
- **Purpose**: Controls global plugin error propagation behavior
- **Default**: `False` - Framework continues processing when plugins encounter technical errors
- **When True**: Any plugin technical error immediately stops request processing across the entire plugin chain
- **When False**: Plugin technical errors are logged but don't halt execution (unless plugin mode overrides)
- **Use Cases**:
  - `True` for critical production environments where plugin failures indicate system issues
  - `False` for resilient operation where partial plugin functionality is acceptable

**plugin_timeout**:
- **Purpose**: Sets maximum execution time for any single plugin
- **Default**: 30 seconds - Prevents plugins from causing request delays
- **Scope**: Applied to all plugins regardless of type (native or external)
- **Behavior**: Timeout triggers `PluginTimeoutError` handled according to plugin mode
- **Considerations**: External plugins may need higher timeouts due to network latency

#### 9.4.2 Plugin Mode-Based Error Handling

Each plugin's `mode` setting determines how violations and errors are handled for that specific plugin:

```python
# Error handling logic varies by plugin mode
if plugin.mode == PluginMode.ENFORCE:
    # Both violations and errors block requests
    if violation or error:
        raise PluginViolationError("Request blocked")

elif plugin.mode == PluginMode.ENFORCE_IGNORE_ERROR:
    # Violations block, errors are logged and ignored
    if violation:
        raise PluginViolationError("Policy violation")
    if error:
        logger.error(f"Plugin error ignored: {error}")

elif plugin.mode == PluginMode.PERMISSIVE:
    # Log violations and errors, continue processing
    if violation:
        logger.warning(f"Policy violation (permissive): {violation}")
    if error:
        logger.error(f"Plugin error (permissive): {error}")

elif plugin.mode == PluginMode.DISABLED:
    # Plugin is loaded but never executed
    return PluginResult()  # Skip plugin entirely
```

#### 9.4.3 Plugin Mode Detailed Behavior

**ENFORCE Mode**:
- **Policy Violations**: Always block requests, raise `PluginViolationError`
- **Technical Errors**: Always block requests, raise `PluginError`
- **Use Cases**: Critical security plugins, compliance enforcement, production safety checks
- **Logging**: Errors and violations logged at ERROR level with full context
- **Client Impact**: Request immediately rejected with violation/error details
- **Example Plugins**: PII detection, path traversal protection, authentication validation

**ENFORCE_IGNORE_ERROR Mode**:
- **Policy Violations**: Block requests, raise `PluginViolationError` (same as ENFORCE)
- **Technical Errors**: Log errors but continue processing (graceful degradation)
- **Use Cases**: Security plugins that should block violations but not fail on technical issues
- **Logging**: Violations at ERROR level, technical errors at WARN level
- **Client Impact**: Blocked only on policy violations, continues on technical failures
- **Example Plugins**: External AI safety services that may be temporarily unavailable

**PERMISSIVE Mode**:
- **Policy Violations**: Log violations but allow request to continue
- **Technical Errors**: Log errors but allow request to continue
- **Use Cases**: Development environments, monitoring plugins, gradual rollout of new policies
- **Logging**: Violations at WARN level, technical errors at INFO level
- **Client Impact**: No request blocking, violations/errors recorded for analysis
- **Example Plugins**: Experimental content filters, new security rules being tested

**DISABLED Mode**:
- **Plugin Execution**: Plugin is completely skipped during hook execution
- **Resource Usage**: No CPU/memory overhead, plugin not invoked
- **Configuration**: Plugin remains in configuration but has no runtime effect
- **Use Cases**: Temporary plugin deactivation, maintenance windows, A/B testing
- **Logging**: No execution logs, only configuration loading messages

#### 9.4.4 Error Handling Decision Matrix

| Plugin Mode | Policy Violation | Technical Error | Request Continues | Logging Level |
|-------------|------------------|-----------------|-------------------|---------------|
| `ENFORCE` | ❌ Block | ❌ Block | No | ERROR |
| `ENFORCE_IGNORE_ERROR` | ❌ Block | ✅ Continue | Violation: No, Error: Yes | ERROR (violation), WARN (error) |
| `PERMISSIVE` | ✅ Continue | ✅ Continue | Yes | WARN (violation), INFO (error) |
| `DISABLED` | ➖ N/A | ➖ N/A | Yes | DEBUG |

#### 9.4.5 Global vs Plugin-Level Interaction

The interaction between global `PluginSettings` and individual plugin modes:

```python
# Global setting overrides plugin mode for technical errors
if global_settings.fail_on_plugin_error and technical_error:
    # Override plugin mode - always fail on technical errors
    raise PluginError("Global fail_on_plugin_error enabled")

# Plugin mode still controls violation handling
if plugin.mode == PluginMode.PERMISSIVE and violation:
    # Log violation but don't block (plugin mode takes precedence)
    logger.warning(f"Policy violation in permissive mode: {violation}")

# Timeout handling respects plugin mode
if execution_time > global_settings.plugin_timeout:
    timeout_error = PluginTimeoutError(f"Plugin {plugin.name} timed out")
    # Handle timeout according to plugin mode
    if plugin.mode == PluginMode.ENFORCE:
        raise timeout_error
    else:
        logger.error(f"Timeout in {plugin.name} (mode: {plugin.mode})")
```

#### 9.4.6 Operational Considerations

**Production Configuration**:
```yaml
# Recommended production settings
plugin_settings:
  fail_on_plugin_error: false      # Allow graceful degradation
  plugin_timeout: 30               # Reasonable timeout for most operations

# Security plugins in ENFORCE mode
- name: "PIIFilter"
  mode: "enforce"                  # Block all violations and errors

# External services with ENFORCE_IGNORE_ERROR
- name: "OpenAIModeration"
  mode: "enforce_ignore_error"     # Block violations, continue on service errors

# Monitoring plugins in PERMISSIVE mode
- name: "MetricsCollector"
  mode: "permissive"               # Never block requests
```

**Development Configuration**:
```yaml
# Development/testing settings
plugin_settings:
  fail_on_plugin_error: false      # Continue on errors for development
  plugin_timeout: 60               # Longer timeout for debugging

# Most plugins in permissive mode for testing
- name: "NewSecurityFilter"
  mode: "permissive"               # Test without blocking requests
```

This error handling strategy ensures that the plugin framework can operate reliably in production while providing flexibility for development and gradual policy rollout scenarios.

### 9.5 Error Recovery

```python
async def execute(self, plugins: list[PluginRef], ...) -> tuple[PluginResult[T], PluginContextTable]:
    combined_metadata = {}

    for plugin in plugins:
        try:
            result = await self._execute_with_timeout(plugin, ...)

            # Process successful result
            if result.modified_payload:
                payload = result.modified_payload

        except asyncio.TimeoutError:
            logger.error(f"Plugin {plugin.name} timed out")
            if self.config.fail_on_plugin_error or plugin.mode == PluginMode.ENFORCE:
                raise PluginError(f"Plugin timeout: {plugin.name}")
            # Continue with next plugin

        except PluginViolationError:
            raise  # Re-raise violations

        except Exception as e:
            logger.error(f"Plugin {plugin.name} failed: {e}")
            if self.config.fail_on_plugin_error or plugin.mode == PluginMode.ENFORCE:
                raise PluginError(f"Plugin error: {plugin.name}")
            # Continue with next plugin
```
