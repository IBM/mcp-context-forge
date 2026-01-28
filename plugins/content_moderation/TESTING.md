# Testing the Content Moderation Plugin

This guide covers comprehensive testing strategies for the Content Moderation Plugin including unit tests, integration tests, and manual testing with various AI providers.

## Test Structure

```
tests/unit/mcpgateway/plugins/plugins/content_moderation/
├── test_content_moderation.py              # Unit tests
├── test_content_moderation_integration.py  # Integration tests
└── __init__.py                             # Test package init
```

## 1. Unit Tests

### Running Unit Tests
```bash
# Run all content moderation tests
pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/ -v

# Run specific test file
pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation.py -v

# Run with coverage
pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/ --cov=plugins.content_moderation --cov-report=html
```

### Unit Test Coverage
- ✅ Plugin initialization and configuration
- ✅ IBM Watson NLU moderation
- ✅ IBM Granite Guardian moderation
- ✅ OpenAI moderation API
- ✅ Pattern-based fallback moderation
- ✅ Content caching functionality
- ✅ Text extraction from payloads
- ✅ Moderation action application
- ✅ Error handling and fallbacks
- ✅ Category threshold evaluation
- ✅ Audit logging functionality

## 2. Integration Tests

### Running Integration Tests
```bash
# Run integration tests with plugin manager
pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py -v
```

### Integration Test Scenarios
- ✅ Plugin manager initialization with content moderation
- ✅ End-to-end content moderation through hooks
- ✅ Fallback provider handling
- ✅ Multi-provider configurations
- ✅ Content blocking and redaction workflows

## 3. Manual Testing

### Prerequisites

#### For IBM Granite Guardian Testing
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull Granite Guardian model
ollama pull granite3-guardian

# Verify model is available
ollama list
```

#### For IBM Watson NLU Testing
```bash
# Set environment variables
export IBM_WATSON_API_KEY="your-api-key"
export IBM_WATSON_URL="https://api.us-south.natural-language-understanding.watson.cloud.ibm.com"
```

#### For OpenAI Testing
```bash
# Set environment variables
export OPENAI_API_KEY="your-openai-api-key"
```

### Testing Approach 1: Pattern-Based Fallback (No API Keys Required)

1. **Configure Plugin for Pattern Testing**:
```yaml
# Update plugins/config.yaml
- name: "ContentModeration"
  config:
    provider: "ibm_watson"  # Will fallback to patterns when API fails
    fallback_provider: null
    fallback_on_error: "warn"
    # Don't set ibm_watson config - will force fallback to patterns
```

2. **Start Gateway**:
```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/mcp-context-forge
export PLUGINS_ENABLED=true
export AUTH_REQUIRED=false
make dev
```

3. **Test Content Moderation**:
```bash
# Test hate speech detection
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "test_tool",
      "arguments": {"query": "I hate all those racist people"}
    }
  }'

# Test violence detection
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "call_tool",
    "params": {
      "name": "search",
      "arguments": {"query": "I am going to kill you"}
    }
  }'

# Test profanity detection
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "call_tool",
    "params": {
      "name": "search",
      "arguments": {"query": "This fucking thing does not work"}
    }
  }'

# Test clean content (should pass)
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "call_tool",
    "params": {
      "name": "search",
      "arguments": {"query": "What is the weather like today?"}
    }
  }'
```

### Testing Approach 2: IBM Granite Guardian (Local)

1. **Ensure Ollama is Running**:
```bash
# Start Ollama (if not already running)
ollama serve

# Test Granite model
ollama run granite3-guardian "Analyze this text for harmful content: I hate everyone"
```

2. **Configure Plugin for Granite**:
```yaml
# Update plugins/config.yaml
- name: "ContentModeration"
  config:
    provider: "ibm_granite"
    ibm_granite:
      ollama_url: "http://localhost:11434"
      model: "granite3-guardian"
      temperature: 0.1
```

3. **Test with Granite**:
```bash
# Test various content types
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "analyze",
      "arguments": {"text": "I want to hurt myself and end it all"}
    }
  }'
```

### Testing Approach 3: IBM Watson NLU (API Key Required)

1. **Set Environment Variables**:
```bash
export IBM_WATSON_API_KEY="your-api-key"
export IBM_WATSON_URL="your-watson-url"
```

2. **Configure Plugin**:
```yaml
# Update plugins/config.yaml
- name: "ContentModeration"
  config:
    provider: "ibm_watson"
    ibm_watson:
      api_key: "${env.IBM_WATSON_API_KEY}"
      url: "${env.IBM_WATSON_URL}"
      version: "2022-04-07"
```

3. **Test Watson Integration**:
```bash
# Test emotional content analysis
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "sentiment_analysis",
      "arguments": {"text": "I am so angry at this terrible situation"}
    }
  }'
```

### Testing Approach 4: OpenAI Moderation (API Key Required)

1. **Set Environment Variables**:
```bash
export OPENAI_API_KEY="your-openai-api-key"
```

2. **Configure Plugin**:
```yaml
# Update plugins/config.yaml
- name: "ContentModeration"
  config:
    provider: "openai"
    openai:
      api_key: "${env.OPENAI_API_KEY}"
      model: "text-moderation-latest"
```

3. **Test OpenAI Integration**:
```bash
# Test OpenAI moderation
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "content_check",
      "arguments": {"message": "I want to kill all politicians"}
    }
  }'
```

## 4. Testing Different Actions

### Testing Block Action
```yaml
categories:
  hate:
    threshold: 0.5  # Lower threshold for easier testing
    action: "block"
```

```bash
# Should be blocked
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "test",
      "arguments": {"query": "I hate everyone"}
    }
  }'
```

### Testing Redact Action
```yaml
categories:
  profanity:
    threshold: 0.5
    action: "redact"
```

```bash
# Content should be redacted
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "test",
      "arguments": {"query": "This damn thing is broken"}
    }
  }'
```

### Testing Warn Action
```yaml
categories:
  toxic:
    threshold: 0.5
    action: "warn"
```

```bash
# Should continue but log warning
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "test",
      "arguments": {"query": "You are such an idiot"}
    }
  }'
```

## 5. Testing Webhook Integration

If you have the webhook plugin enabled, content moderation violations should trigger webhook notifications:

1. **Enable Both Plugins**:
```yaml
plugins:
  - name: "ContentModeration"
    # ... config
  - name: "WebhookNotification"
    # ... config with harmful_content event
```

2. **Test Violation Webhook**:
```bash
# This should trigger both moderation and webhook
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "test",
      "arguments": {"query": "violent harmful content here"}
    }
  }'
```

3. **Check webhook.site** for notifications with:
   - Event type: "harmful_content" or "violation"
   - Moderation details in metadata

## 6. Performance Testing

### Load Testing Content Moderation
```python
import asyncio
import aiohttp

async def test_concurrent_moderation():
    """Test concurrent content moderation requests."""

    test_contents = [
        "This is clean content",
        "I hate this stupid thing",
        "What is the weather today?",
        "This damn computer is broken",
        "I want to hurt someone",
    ]

    async with aiohttp.ClientSession() as session:
        tasks = []
        for i, content in enumerate(test_contents * 20):  # 100 total requests
            payload = {
                "jsonrpc": "2.0",
                "id": i,
                "method": "call_tool",
                "params": {
                    "name": "test",
                    "arguments": {"query": content}
                }
            }

            task = session.post(
                'http://localhost:8000/',
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            tasks.append(task)

        # Execute concurrently
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        print(f"Completed {len(responses)} requests")
        print(f"Successful: {len([r for r in responses if not isinstance(r, Exception)])}")

# Run the test
asyncio.run(test_concurrent_moderation())
```

## 7. Error Scenario Testing

### Testing Provider Failures
```yaml
# Set invalid configuration to test fallback
ibm_watson:
  api_key: "invalid-key"
  url: "https://invalid-url.com"
```

### Testing Network Timeouts
```yaml
# Set very short timeout
ibm_watson:
  timeout: 1  # 1 second - may cause timeouts
```

### Testing Content Size Limits
```bash
# Test with very large content
large_content=$(python -c "print('test content ' * 1000)")
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"id\": 1,
    \"method\": \"call_tool\",
    \"params\": {
      \"name\": \"test\",
      \"arguments\": {\"query\": \"$large_content\"}
    }
  }"
```

## 8. Monitoring and Debugging

### Enable Debug Logging
```bash
export LOG_LEVEL=DEBUG
make dev

# Look for content moderation logs
tail -f logs/mcpgateway.log | grep -i moderation
```

### Check Plugin Status
```bash
# Verify plugin is loaded
curl http://localhost:8000/health
```

### Audit Trail Analysis
```bash
# Check audit logs for moderation decisions
grep "Content moderation" logs/mcpgateway.log | jq .
```

## 9. Test Data Sets

### Harmful Content Samples
```python
HATE_SPEECH_SAMPLES = [
    "I hate all people from that country",
    "Those people should not exist",
    "All [group] are terrible people"
]

VIOLENCE_SAMPLES = [
    "I'm going to kill you",
    "Let's bomb that building",
    "How to make weapons"
]

SELF_HARM_SAMPLES = [
    "I want to kill myself",
    "Life is not worth living",
    "How to end it all"
]

PROFANITY_SAMPLES = [
    "This fucking system sucks",
    "What the hell is wrong",
    "Damn this stupid thing"
]

CLEAN_CONTENT_SAMPLES = [
    "What is the weather today?",
    "How do I learn programming?",
    "Can you help me with math?"
]
```

### Edge Cases
```python
EDGE_CASES = [
    "",  # Empty content
    "a" * 50000,  # Very long content
    "Mixed clean and I hate everyone together",  # Mixed content
    "Context matters: 'I hate' is in this quote",  # Quoted content
    "Medical: patient shows self-harm ideation",  # Medical context
]
```

## 10. CI/CD Integration

### GitHub Actions Test
```yaml
name: Content Moderation Tests
on: [push, pull_request]

jobs:
  test-content-moderation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: make venv install-dev

      - name: Install Ollama for Granite testing
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          ollama pull granite3-guardian

      - name: Run unit tests
        run: |
          pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/ -v --cov

      - name: Run integration tests
        run: |
          pytest tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py -v
```

## Summary

This comprehensive testing guide ensures the Content Moderation Plugin works correctly across all supported providers and scenarios. The plugin provides robust content safety with multiple fallback layers, making it suitable for production environments requiring reliable content moderation.
