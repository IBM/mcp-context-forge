# Webhook Notification Plugin

> Author: Manav Gupta
> Version: 1.0.0

Sends HTTP webhook notifications on specific events, violations, or state changes. Supports multiple webhooks, event filtering, retry logic with exponential backoff, and various authentication methods.

## Hooks
- `prompt_pre_fetch`
- `prompt_post_fetch`
- `tool_pre_invoke`
- `tool_post_invoke`
- `resource_pre_fetch`
- `resource_post_fetch`

## Event Types
- `violation` - General plugin violations
- `rate_limit_exceeded` - Rate limiting violations
- `pii_detected` - PII detection violations
- `harmful_content` - Harmful content violations
- `tool_success` - Successful tool invocations
- `tool_error` - Failed tool invocations
- `prompt_success` - Successful prompt fetches
- `resource_success` - Successful resource fetches
- `plugin_error` - Plugin execution errors

## Authentication Methods
- `none` - No authentication
- `bearer` - Bearer token authentication
- `api_key` - API key in custom header
- `hmac` - HMAC signature authentication

## Configuration

### Basic Configuration
```yaml
config:
  webhooks:
    - url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
      events: ["violation", "rate_limit_exceeded"]
      authentication:
        type: "none"
      retry_attempts: 3
      retry_delay: 1000
      timeout: 10
      enabled: true
```

### Advanced Configuration with Authentication
```yaml
config:
  webhooks:
    # Slack webhook for violations
    - url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
      events: ["violation", "pii_detected", "harmful_content"]
      authentication:
        type: "bearer"
        token: "${env.SLACK_WEBHOOK_TOKEN}"
      retry_attempts: 3
      retry_delay: 1000

    # API endpoint with HMAC authentication
    - url: "https://api.example.com/webhooks/mcp-gateway"
      events: ["tool_success", "tool_error"]
      authentication:
        type: "hmac"
        hmac_secret: "${env.WEBHOOK_HMAC_SECRET}"
        hmac_algorithm: "sha256"
        hmac_header: "X-Hub-Signature-256"
        hmac_include_timestamp: true   # opt in to replay protection (see "HMAC Signatures")
      retry_attempts: 5
      retry_delay: 2000
      timeout: 30

    # Monitoring service with API key
    - url: "https://monitoring.service.com/events"
      events: ["violation", "tool_error", "plugin_error"]
      authentication:
        type: "api_key"
        api_key: "${env.MONITORING_API_KEY}"
        api_key_header: "X-API-Key"
      retry_attempts: 2
      retry_delay: 500

  # Custom payload templates per event type
  payload_templates:
    violation: |
      {
        "alert": "ContextForge Violation",
        "severity": "warning",
        "message": "{{violation.reason}}: {{violation.description}}",
        "plugin": "{{plugin_name}}",
        "timestamp": "{{timestamp}}",
        "request_id": "{{request_id}}",
        "user": "{{user}}",
        "details": {{violation}}
      }

    rate_limit_exceeded: |
      {
        "alert": "Rate Limit Exceeded",
        "severity": "error",
        "message": "Rate limit exceeded for {{user}}",
        "timestamp": "{{timestamp}}",
        "request_id": "{{request_id}}",
        "violation_details": {{violation}}
      }

  # Include request payload data in notifications (be careful with sensitive data)
  include_payload_data: false
  max_payload_size: 1000
```

## Template Variables

The following variables are available in payload templates:

- `{{event}}` - Event type (violation, tool_success, etc.)
- `{{plugin_name}}` - Name of the webhook plugin
- `{{timestamp}}` - ISO timestamp of the event
- `{{request_id}}` - Unique request identifier
- `{{user}}` - User identifier (if available)
- `{{tenant_id}}` - Tenant identifier (if available)
- `{{server_id}}` - Server identifier (if available)
- `{{violation}}` - Full violation object (JSON)
- `{{metadata}}` - Event metadata (JSON)
- `{{payload}}` - Request payload data (if enabled, JSON)

## Features

### Retry Logic
- Configurable retry attempts (0-10)
- Exponential backoff starting from configured delay
- Individual timeout per webhook request
- Comprehensive error logging

### Authentication Support
- **Bearer Token**: `Authorization: Bearer <token>`
- **API Key**: Custom header with API key
- **HMAC**: Request signing with configurable algorithm
- **Environment Variables**: Secure credential management

### Event Filtering
- Subscribe to specific event types per webhook
- Smart event detection based on violation details
- Separate templates for different event types

### Concurrent Delivery
- Multiple webhooks sent concurrently
- Non-blocking execution (fire-and-forget)
- Individual retry logic per webhook

## Security Considerations

1. **Credential Management**: Use environment variables for sensitive data
2. **Payload Size**: Limit included payload data to prevent sensitive data leaks
3. **HMAC Signatures**: Verify webhook authenticity on receiving end
4. **Network Security**: Use HTTPS endpoints only
5. **Timeout Configuration**: Prevent hanging requests

## HMAC Signatures

`type: hmac` signs each delivery with `hmac_secret`. The `X-Signature` value (or `hmac_header`) has the form `{hmac_algorithm}={hex}`.

| Setting | Default | Purpose |
|---------|---------|---------|
| `hmac_algorithm` | `sha256` | Hash algorithm for the HMAC |
| `hmac_header` | `X-Signature` | Header that carries the signature |
| `hmac_include_timestamp` | `false` | Bind the signature to a timestamp and delivery ID |
| `hmac_timestamp_header` | `X-Timestamp` | Header that carries the Unix time in seconds |
| `hmac_delivery_id_header` | `X-Delivery-Id` | Header that carries the delivery ID |

The three header names must be non-empty and different from each other.

**Legacy scheme** (`hmac_include_timestamp: false`, default). The signed material is the request body. A captured request can be replayed at any time.

**Replay-protected scheme** (`hmac_include_timestamp: true`). The signed material is `{timestamp}.{delivery_id}.{body}`. The plugin signs each retry again with a fresh timestamp. The delivery ID stays the same across retries of one delivery.

Receivers must:

1. Recompute the HMAC over `{timestamp}.{delivery_id}.{body}` and compare with `hmac.compare_digest`.
2. Reject a timestamp outside a freshness window, for example 300 seconds.
3. Reject a delivery ID that was already accepted inside the window.

```python
import hashlib
import hmac
import time

FRESHNESS_SECONDS = 300
seen_delivery_ids: set[str] = set()  # use a shared store with expiry in production


def verify_webhook(body: bytes, headers: dict, secret: str) -> bool:  # pragma: allowlist secret
    timestamp = headers["X-Timestamp"]
    delivery_id = headers["X-Delivery-Id"]
    if abs(time.time() - int(timestamp)) > FRESHNESS_SECONDS or delivery_id in seen_delivery_ids:
        return False
    material = f"{timestamp}.{delivery_id}.".encode() + body
    expected = "sha256=" + hmac.new(secret.encode(), material, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, headers["X-Signature"]):
        return False
    seen_delivery_ids.add(delivery_id)
    return True
```

The default flips to `true` in a later minor release. Set `hmac_include_timestamp: true` and update receivers before then.

## Example Webhook Payloads

### Violation Event
```json
{
  "event": "violation",
  "plugin": "WebhookNotificationPlugin",
  "timestamp": "2025-01-15T10:30:45.123Z",
  "request_id": "req-12345",
  "user": "user@example.com",
  "tenant_id": "tenant-abc",
  "server_id": "server-xyz",
  "violation": {
    "reason": "Rate limit exceeded",
    "description": "User user@example.com rate limit exceeded",
    "code": "RATE_LIMIT",
    "details": {"remaining": 0, "reset_in": 45}
  },
  "metadata": {}
}
```

### Tool Success Event
```json
{
  "event": "tool_success",
  "plugin": "WebhookNotificationPlugin",
  "timestamp": "2025-01-15T10:30:45.123Z",
  "request_id": "req-12346",
  "user": "user@example.com",
  "violation": null,
  "metadata": {"tool_name": "search"}
}
```

## Usage Tips

1. **Start Simple**: Begin with basic Slack webhooks for violations
2. **Test Thoroughly**: Use tools like ngrok for local webhook testing
3. **Monitor Logs**: Check gateway logs for webhook delivery status
4. **Gradual Rollout**: Enable events incrementally to avoid notification spam
5. **Template Testing**: Test payload templates with various event types

## Performance Notes

- Webhooks are sent asynchronously and don't block request processing
- Failed webhooks are retried with exponential backoff
- HTTP client connection pooling optimizes performance
- Memory usage scales with number of concurrent webhook deliveries

## Troubleshooting

### Common Issues
- **Authentication Failures**: Verify tokens and secrets in environment variables
- **Timeout Errors**: Increase timeout values for slow webhook endpoints
- **Template Errors**: Check Jinja2 syntax in custom templates
- **SSL Errors**: Ensure webhook URLs use valid HTTPS certificates

### Debug Logging
Enable debug logging to see webhook delivery attempts:
```bash
export LOG_LEVEL=DEBUG
```
