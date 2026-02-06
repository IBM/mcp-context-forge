# Plugin Examples

This directory contains example plugins demonstrating various plugin patterns.

## CDM (Common Data Model) Examples

These examples demonstrate using the unified CDM and MessageView for policy evaluation.

### cdm_role_guard

Role-based access control using MessageView's principal accessors.

**Demonstrates:**
- Accessing `view.roles` and `view.permissions`
- Using `view.has_role()` and `view.has_permission()`
- Checking `view.environment` for environment-specific rules
- Tool-level RBAC with patterns

**Use Case:** Restrict dangerous tools to admin users, block tools in production.

```yaml
tool_permissions:
  - tool_pattern: "dangerous_*"
    required_roles: ["admin", "security"]
    denied_environments: ["production"]
```

### cdm_content_scanner

Content scanning for sensitive patterns using MessageView's content accessor.

**Demonstrates:**
- Using `view.content` to get scannable text
- Filtering by `view.is_pre` / `view.is_post`
- Filtering by `view.kind` (text, tool_call, tool_result)
- Pattern-based scanning with severity levels

**Use Case:** Detect PII, secrets, API keys in messages before/after LLM processing.

```yaml
patterns:
  - name: "ssn"
    pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    severity: "critical"
    block: true
    scan_pre: true
    scan_post: true
```

### cdm_tool_allowlist

URI-based access control using MessageView's URI matching.

**Demonstrates:**
- Using `view.uri` to get tool/resource URIs
- Using `view.matches_uri_pattern()` for glob matching
- Filtering by `view.kind` (TOOL_CALL, RESOURCE, PROMPT_REQUEST)
- Using `view.action` to understand operation type

**Use Case:** Allowlist safe tools, block access to sensitive files.

```yaml
allowed_tools:
  - "tool://*/search"
  - "tool://mcp/**"
blocked_resources:
  - "file:///etc/**"
  - "file:///**/.env"
```

### cdm_opa_policy

External policy evaluation using OPA (Open Policy Agent).

**Demonstrates:**
- Using `view.to_dict()` to serialize views to JSON
- Using `view.to_opa_input()` for OPA-compatible format
- Using `message.to_opa_input()` for full message serialization
- Sending policy requests to OPA server
- Handling OPA responses with deny reasons

**Use Case:** Externalize policy decisions to OPA for complex rules.

Includes `example_policy.rego` with sample Rego rules:
```rego
package apex

# Allow read-only tools
allow {
    input.kind == "tool_call"
    startswith(input.name, "read_")
}

# Deny dangerous tools
deny[msg] {
    input.kind == "tool_call"
    input.name == "execute_shell"
    msg := "Shell execution is not allowed"
}
```

## Other Examples

### simple_token_auth

Example of HTTP authentication using token-based auth.

### custom_auth_example

Example of custom authentication provider integration.

## Using CDM Examples

These plugins use the `message_evaluate` hook which receives a CDM `Message` as payload:

```python
async def message_evaluate(
    self, payload: MessagePayload, context: PluginContext
) -> MessageResult:
    # Get views from the message, passing context for principal access
    views = payload.view(context)

    for view in views:
        # Check view type
        if view.kind == ViewKind.TOOL_CALL:
            # Access tool properties
            print(f"Tool: {view.name}, URI: {view.uri}")

        # Check content
        if view.content and "secret" in view.content:
            return MessageResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Secret detected",
                    code="SECRET_DETECTED",
                )
            )

    return MessageResult()
```

## MessageView Properties

| Property | Description |
|----------|-------------|
| `view.kind` | ViewKind enum (TEXT, TOOL_CALL, RESOURCE, etc.) |
| `view.content` | Text content for scanning |
| `view.uri` | URI for tools, resources, prompts |
| `view.name` | Human-readable name |
| `view.is_pre` | True if input/request content |
| `view.is_post` | True if output/response content |
| `view.role` | Message role (USER, ASSISTANT, etc.) |
| `view.principal` | Authenticated principal |
| `view.roles` | Principal's roles |
| `view.permissions` | Principal's permissions |
| `view.environment` | Execution environment |
| `view.headers` | HTTP headers |
| `view.labels` | Data classification labels |

## Serialization for External Policy Engines

MessageView can be serialized to JSON for external policy engines like OPA:

```python
# Single view to JSON dict
view_dict = view.to_dict()

# Single view in OPA format
opa_input = view.to_opa_input()
# {"input": {"kind": "tool_call", "name": "search", ...}}

# Full message to OPA format
opa_input = message.to_opa_input(context)
# {"input": {"message": {...}, "views": [...]}}
```

The `to_dict()` output includes:
- `kind`, `is_pre`, `is_post`, `role`
- `uri`, `name`, `action`
- `content`, `size_bytes`, `mime_type`
- `arguments` (for tool calls)
- `properties` (type-specific)
- `context` (principal, environment, labels, headers)
