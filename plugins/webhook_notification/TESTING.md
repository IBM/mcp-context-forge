# Testing the Webhook Notification Plugin

This guide covers comprehensive testing strategies for the Webhook Notification Plugin at unit, integration, and end-to-end levels.

## Test Structure

```
tests/unit/mcpgateway/plugins/plugins/webhook_notification/
├── test_webhook_notification.py      # Unit tests
├── test_webhook_integration.py       # Integration tests
└── __init__.py                       # Test package init
```

## 1. Unit Tests

### Running Unit Tests
```bash
# Run all webhook plugin tests
pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/ -v

# Run specific test file
pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_notification.py -v

# Run with coverage
pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/ --cov=plugins.webhook_notification --cov-report=html
```

### Unit Test Coverage
- ✅ Plugin initialization and configuration
- ✅ Template rendering with context variables
- ✅ HMAC signature creation
- ✅ Webhook delivery success scenarios
- ✅ Authentication methods (Bearer, API Key, HMAC)
- ✅ Retry logic on failures
- ✅ Event type determination
- ✅ Hook execution (tool_post_invoke, prompt_post_fetch, etc.)
- ✅ Event filtering by webhook configuration
- ✅ Disabled webhook handling
- ✅ Custom payload templates
- ✅ Payload size limiting

### Key Test Cases

#### Authentication Testing
```python
# Test Bearer token authentication
config = {
    "webhooks": [{
        "authentication": {
            "type": "bearer",
            "token": "test-token-123"
        }
    }]
}

# Test API key authentication
config = {
    "webhooks": [{
        "authentication": {
            "type": "api_key",
            "api_key": "test-key",
            "api_key_header": "X-API-Key"
        }
    }]
}
```

#### Retry Logic Testing
```python
# Mock HTTP client to return 500 errors
mock_response.status_code = 500
mock_client.post.return_value = mock_response

# Verify retries (1 initial + 3 retries = 4 total calls)
assert mock_client.post.call_count == 4
```

## 2. Integration Tests

### Running Integration Tests
```bash
# Run integration tests
pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py -v

# Run with plugin manager setup
pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py::test_webhook_plugin_with_manager -v
```

### Integration Test Scenarios
- ✅ Plugin manager initialization with webhook plugin
- ✅ End-to-end hook execution through plugin manager
- ✅ Multiple webhook delivery
- ✅ Custom template usage
- ✅ Plugin interaction with other plugins (PII filter, rate limiter)

### Sample Integration Test Config
```yaml
plugins:
  - name: "WebhookNotification"
    kind: "plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin"
    hooks: ["tool_post_invoke"]
    mode: "permissive"
    priority: 900
    config:
      webhooks:
        - url: "https://test.example.com/webhook"
          events: ["tool_success"]
          authentication:
            type: "bearer"
            token: "test-token"
```

## 3. Manual Testing

### Local Webhook Server Setup

#### Using Python HTTP Server
```bash
# Simple webhook receiver
cat << 'EOF' > webhook_server.py
#!/usr/bin/env python3
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        print(f"\n--- Webhook Received ---")
        print(f"Headers: {dict(self.headers)}")
        print(f"Body: {post_data.decode('utf-8')}")

        # Parse and pretty print JSON
        try:
            data = json.loads(post_data.decode('utf-8'))
            print(f"Parsed JSON:")
            print(json.dumps(data, indent=2))
        except:
            pass

        print("--- End Webhook ---\n")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

if __name__ == '__main__':
    server = HTTPServer(('localhost', 3000), WebhookHandler)
    print("Webhook server running on http://localhost:3000")
    server.serve_forever()
EOF

python3 webhook_server.py
```

#### Using ngrok for Public URLs
```bash
# Install ngrok (if not installed)
# Mac: brew install ngrok
# Linux: snap install ngrok

# Expose local webhook server
ngrok http 3000

# Use the https URL from ngrok in your webhook config
```

### Manual Testing Steps

1. **Start Local Webhook Server**
   ```bash
   python3 webhook_server.py
   ```

2. **Configure Test Environment**
   ```bash
   cp plugins/webhook_notification/test_config.yaml plugins/config.yaml
   # Edit the webhook URL to point to your local server
   ```

3. **Start MCP Gateway**
   ```bash
   export PLUGINS_ENABLED=true
   export PLUGINS_CONFIG_FILE=plugins/config.yaml
   make dev
   ```

4. **Generate Test Bearer Token**
   ```bash
   export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username test@example.com --exp 60 --secret test-secret)
   ```

5. **Trigger Webhook Events**

   **Tool Success Event:**
   ```bash
   curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"test_tool","params":{"query":"hello world"}}' \
        http://localhost:8000/
   ```

   **PII Detection Event:**
   ```bash
   curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":2,"method":"search","params":{"query":"my email is john@example.com"}}' \
        http://localhost:8000/
   ```

   **Rate Limit Event (call rapidly):**
   ```bash
   for i in {1..10}; do
     curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"jsonrpc":"2.0","id":'$i',"method":"test_tool","params":{"query":"test"}}' \
          http://localhost:8000/ &
   done
   wait
   ```

## 4. External Service Testing

### Testing with Webhook.site
1. Visit https://webhook.site
2. Copy your unique URL
3. Update config with the URL:
   ```yaml
   webhooks:
     - url: "https://webhook.site/YOUR-UNIQUE-ID"
       events: ["violation", "tool_success"]
       enabled: true
   ```

### Testing with Slack
1. Create a Slack webhook in your workspace
2. Set environment variable:
   ```bash
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
   ```
3. Enable Slack webhook in config:
   ```yaml
   webhooks:
     - url: "${env.SLACK_WEBHOOK_URL}"
       events: ["violation", "pii_detected"]
       enabled: true
   ```

## 5. Performance Testing

### Load Testing Webhook Delivery
```python
# Test concurrent webhook delivery
import asyncio
import time
from plugins.webhook_notification.webhook_notification import WebhookNotificationPlugin

async def test_concurrent_webhooks():
    plugin = create_test_plugin()

    # Send 100 concurrent notifications
    tasks = []
    start_time = time.time()

    for i in range(100):
        context = create_test_context(f"user-{i}")
        task = plugin._notify_webhooks(EventType.TOOL_SUCCESS, context)
        tasks.append(task)

    await asyncio.gather(*tasks)

    end_time = time.time()
    print(f"Sent 100 webhooks in {end_time - start_time:.2f} seconds")

# Run the test
asyncio.run(test_concurrent_webhooks())
```

### Memory Usage Testing
```bash
# Monitor memory usage during webhook delivery
pip install memory_profiler

# Profile webhook plugin
python -m memory_profiler test_webhook_memory.py
```

## 6. Error Scenario Testing

### Testing Network Failures
```python
# Mock network timeouts
mock_client.post.side_effect = asyncio.TimeoutError("Request timed out")

# Mock connection errors
mock_client.post.side_effect = httpx.ConnectError("Connection failed")

# Mock HTTP errors
mock_response.status_code = 503
mock_client.post.return_value = mock_response
```

### Testing Authentication Failures
```bash
# Test with invalid bearer token
curl -X POST -H "Authorization: Bearer invalid-token" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"test","params":{}}' \
     http://localhost:8000/
```

## 7. Security Testing

### Testing HMAC Signatures
```python
import hmac
import hashlib

def verify_webhook_signature(payload, signature, secret):
    expected = hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={expected}" == signature

# Test signature verification in your webhook receiver
```

### Testing Credential Security
- ✅ Verify tokens are not logged
- ✅ Verify environment variables are used for secrets
- ✅ Test with expired/invalid credentials

## 8. Debugging Tips

### Enable Debug Logging
```bash
export LOG_LEVEL=DEBUG
make dev
```

### View Webhook Plugin Logs
```bash
# Filter for webhook plugin logs
tail -f logs/mcpgateway.log | grep -i webhook

# Or use structured logging
export MCPGATEWAY_LOG_FORMAT=json
```

### Common Issues and Solutions

**Issue**: Webhooks not being sent
- Check `enabled: true` in webhook config
- Verify events match what's being triggered
- Check plugin priority and hooks configuration

**Issue**: Authentication failures
- Verify environment variables are set correctly
- Check token/key format and headers
- Test authentication separately

**Issue**: Template rendering errors
- Validate JSON syntax in templates
- Check variable names match available context
- Test templates with sample data

**Issue**: Network timeouts
- Increase timeout values in webhook config
- Check network connectivity to webhook URLs
- Verify firewall and proxy settings

## 9. CI/CD Integration

### GitHub Actions Test Configuration
```yaml
name: Webhook Plugin Tests
on: [push, pull_request]

jobs:
  test-webhook-plugin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          make venv install-dev

      - name: Run webhook plugin tests
        run: |
          pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/ -v --cov

      - name: Run integration tests
        run: |
          pytest tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py -v
```

### Test Coverage Requirements
- Unit tests: > 95% line coverage
- Integration tests: All major user scenarios
- Error handling: All exception paths covered

## 10. Test Data and Fixtures

### Sample Test Payloads
```json
{
  "tool_success": {
    "event": "tool_success",
    "tool_name": "search",
    "user": "test@example.com",
    "timestamp": "2025-01-15T10:30:45.123Z"
  },
  "violation": {
    "event": "violation",
    "violation": {
      "reason": "Rate limit exceeded",
      "code": "RATE_LIMIT"
    }
  }
}
```

This comprehensive testing approach ensures the Webhook Notification Plugin is robust, reliable, and ready for production use.
