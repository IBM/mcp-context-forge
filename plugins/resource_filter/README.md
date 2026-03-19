# Resource Filter Plugin

> Author: Mihai Criveti

A sample plugin that demonstrates the use of resource pre-fetch and post-fetch hooks in ContextForge plugin system.

## Features

### Pre-Fetch Hook (`resource_pre_fetch`)
- **Protocol Validation**: Blocks resources from non-allowed protocols
- **Domain Blocking**: Prevents fetching from blocked domains
- **URI Validation**: Ensures URIs are properly formatted
- **Metadata Addition**: Adds tracking metadata to resource requests

### Post-Fetch Hook (`resource_post_fetch`)
- **Content Size Limiting**: Blocks resources exceeding maximum size
- **Content Filtering**: Redacts sensitive patterns from text content
- **Metadata Tracking**: Records what modifications were made

## Configuration

```yaml
name: resource_filter
kind: plugins.resource_filter.resource_filter.ResourceFilterPlugin
hooks:
  - resource_pre_fetch
  - resource_post_fetch
config:
  # Maximum allowed content size in bytes (default: 1MB)
  max_content_size: 1048576

  # List of allowed protocols
  allowed_protocols:
    - file
    - http
    - https

  # List of blocked domains
  blocked_domains:
    - blocked-site.com
    - malicious.example.com

  # Content filters to apply (regex patterns)
  content_filters:
    - pattern: "password\\s*[:=]\\s*\\S+"
      replacement: "password: ***"
    - pattern: "api[_-]?key\\s*[:=]\\s*\\S+"
      replacement: "api_key: ***"
    - pattern: "secret\\s*[:=]\\s*\\S+"
      replacement: "secret: ***"
```

## Usage Examples

### Basic Setup

1. Add the plugin to your `plugins/config.yaml`:

```yaml
plugins:
  - name: resource_filter_example
    description: "Filters and validates resources"
    author: "ContextForge Team"
    kind: plugins.resource_filter.resource_filter.ResourceFilterPlugin
    version: "1.0.0"
    hooks:
      - resource_pre_fetch
      - resource_post_fetch
    tags:
      - resource
      - security
      - filter
    mode: enforce  # or 'permissive' for logging only
    priority: 50
    config:
      max_content_size: 524288  # 512KB
      allowed_protocols:
        - file
        - https
      blocked_domains:
        - untrusted.com
      content_filters:
        - pattern: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
          replacement: "[EMAIL REDACTED]"
```

### Conditional Execution

Apply the plugin only to specific resources:

```yaml
plugins:
  - name: sensitive_resource_filter
    kind: plugins.resource_filter.resource_filter.ResourceFilterPlugin
    hooks:
      - resource_pre_fetch
      - resource_post_fetch
    conditions:
      - resources:
          - "file:///etc/passwd"
          - "file:///var/log/*"
          - "https://api.internal.com/*"
    config:
      # Strict configuration for sensitive resources
      max_content_size: 102400  # 100KB
      content_filters:
        - pattern: "\\d{3}-\\d{2}-\\d{4}"  # SSN pattern
          replacement: "XXX-XX-XXXX"
```

## Plugin Behavior

### Pre-Fetch Phase

1. **URI Parsing**: Validates the resource URI format
2. **Protocol Check**: Ensures the protocol is in the allowed list
3. **Domain Check**: Blocks requests to blacklisted domains
4. **Metadata Addition**: Adds plugin-specific metadata for tracking

### Post-Fetch Phase

1. **Size Check**: Validates content doesn't exceed maximum size
2. **Content Filtering**: Applies regex patterns to redact sensitive data
3. **Metadata Update**: Records what modifications were made

## Error Codes

- `INVALID_URI`: The resource URI could not be parsed
- `PROTOCOL_BLOCKED`: The URI protocol is not allowed
- `DOMAIN_BLOCKED`: The domain is in the blocked list
- `CONTENT_TOO_LARGE`: Resource content exceeds maximum size

## Development

To extend this plugin:

1. Add new validation rules in `resource_pre_fetch()`
2. Add new content transformations in `resource_post_fetch()`
3. Store state between hooks using `context.set_state()` and `context.get_state()`

## Testing

Test the plugin with various resource types:

```python
# Test protocol blocking
payload = ResourcePreFetchPayload("ftp://example.com/file.txt")
# Should block if 'ftp' not in allowed_protocols

# Test content filtering
content = ResourceContent(
    uri="file:///config.txt",
    contents=[TextContent(type="text", text="password: mysecret123")]
)
payload = ResourcePostFetchPayload("file:///config.txt", content)
# Should redact password to "password: ***"
```
