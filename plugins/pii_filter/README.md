# PII Filter Plugin for MCP Gateway

> Author: Mihai Criveti
> Version: 0.1.0

A plugin for detecting and masking Personally Identifiable Information (PII) in MCP Gateway prompts and responses.

## Features

### PII Detection Types
- **Social Security Numbers (SSN)** - US format (123-45-6789 or 123456789)
- **Credit Card Numbers** - Major card formats with various separators
- **Email Addresses** - Standard email format validation
- **Phone Numbers** - US and international formats
- **IP Addresses** - IPv4 and IPv6
- **Dates of Birth** - Various date formats with context
- **Passport Numbers** - International passport formats
- **Driver's License Numbers** - US state formats
- **Bank Account Numbers** - Including IBAN
- **Medical Record Numbers** - MRN formats
- **AWS Access Keys** - AKIA prefixed keys and secrets
- **API Keys** - Generic API key patterns
- **Custom Patterns** - Define your own PII patterns

### Masking Strategies
- **REDACT** - Complete replacement with `[REDACTED]` or custom text
- **PARTIAL** - Show partial info (e.g., `***-**-1234` for SSN, `j***e@example.com` for email)
- **HASH** - Replace with hash value for consistency
- **TOKENIZE** - Replace with unique token for reversibility
- **REMOVE** - Complete removal of PII

### Operating Modes
- **ENFORCE** - Block or mask PII (based on configuration)
- **PERMISSIVE** - Log detections but don't block
- **DISABLED** - Turn off the plugin

## Installation

1. Copy .env.example .env
2. Enable plugins in `.env`
3. Add the plugin configuration to `plugins/config.yaml`:

```yaml
plugins:
  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    description: "Detects and masks Personally Identifiable Information"
    version: "1.0"
    author: "Security Team"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch"]
    tags: ["security", "pii", "compliance", "filter", "gdpr", "hipaa"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 10  # Lower number = higher priority (runs first)
    conditions:
      - prompts: []  # Empty list = apply to all prompts
        server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      # PII Detection Settings
      detect_ssn: true
      detect_credit_card: true
      detect_email: true
      detect_phone: true
      detect_ip_address: true
      detect_aws_keys: true
      detect_api_keys: true
      # Masking Settings
      default_mask_strategy: "partial"
      redaction_text: "[PII_REDACTED]"
      # Behavior Settings
      block_on_detection: false
      log_detections: true
      include_detection_details: true
      # Whitelist patterns
      whitelist_patterns:
        - "test@example.com"
        - "555-555-5555"
```

## Configuration Examples

### Development Environment (Permissive)
```yaml
config:
  mode: "permissive"  # Only log, don't block
  detect_email: false  # Allow emails in dev
  detect_phone: false  # Allow phones in dev
  default_mask_strategy: "partial"  # Show partial info for debugging
  block_on_detection: false
```

### Production Environment (Strict Compliance)
```yaml
config:
  mode: "enforce"
  block_on_detection: true  # Block any request with PII
  default_mask_strategy: "redact"  # Complete redaction
  log_detections: true
  detect_ssn: true
  detect_credit_card: true
  detect_email: true
  # ... enable all detection types
```

### API Keys Only
```yaml
config:
  detect_ssn: false
  detect_credit_card: false
  detect_email: false
  detect_phone: false
  detect_aws_keys: true  # Only detect API keys
  detect_api_keys: true
  block_on_detection: true  # Always block if keys detected
  default_mask_strategy: "redact"
```

## Testing

### Run All Tests
```bash
# Run all PII filter tests
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py -v

# Run with coverage
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py --cov=plugins.pii_filter --cov-report=term-missing
```

### Run Specific Test Classes
```bash
# Test only the detector functionality
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py::TestPIIDetector -v

# Test only the plugin integration
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py::TestPIIFilterPlugin -v
```

### Run Individual Tests
```bash
# Test SSN detection
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py::TestPIIDetector::test_ssn_detection -v

# Test masking strategies
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py::TestPIIDetector::test_masking_strategies -v

# Test blocking mode
pytest tests/unit/mcpgateway/plugins/pii_filter/test_pii_filter.py::TestPIIFilterPlugin::test_prompt_pre_fetch_blocking -v
```

### Manual Testing with the Gateway

1. Enable the plugin in your `.env`:
```bash
PLUGINS_ENABLED=true
```

2. Start the gateway:
```bash
python -m mcpgateway.main
```

3. Test with curl:
```bash
# Test PII detection in prompt arguments
curl -X POST http://localhost:8000/prompts/test_prompt \
  -H "Content-Type: application/json" \
  -d '{
    "args": {
      "user_input": "My SSN is 123-45-6789 and email is john@example.com"
    }
  }'

# Response should have masked PII:
# "user_input": "My SSN is ***-**-6789 and email is j***n@example.com"
```

### Test Custom Patterns

Add custom patterns in your config:
```yaml
config:
  custom_patterns:
    - type: "custom"
      pattern: "\\bEMP\\d{6}\\b"
      description: "Employee ID"
      mask_strategy: "redact"
      enabled: true
```

Test the custom pattern:
```python
from plugins.pii_filter.pii_filter import PIIFilterPlugin, PIIFilterConfig, PIIDetector

config = PIIFilterConfig(
    custom_patterns=[{
        "type": "custom",
        "pattern": r"\bEMP\d{6}\b",
        "description": "Employee ID",
        "mask_strategy": "redact",
        "enabled": True
    }]
)
detector = PIIDetector(config)

text = "Employee ID: EMP123456"
detections = detector.detect(text)
masked = detector.mask(text, detections)
print(masked)  # Output: "Employee ID: [REDACTED]"
```

## Debugging

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# The plugin will log all PII detections
logger = logging.getLogger("plugins.pii_filter.pii_filter")
logger.setLevel(logging.DEBUG)
```

### Check Detection Results
```python
from plugins.pii_filter.pii_filter import PIIDetector, PIIFilterConfig

config = PIIFilterConfig(detect_ssn=True, detect_email=True)
detector = PIIDetector(config)

text = "SSN: 123-45-6789, Email: test@example.com"
detections = detector.detect(text)

# Inspect what was detected
for pii_type, items in detections.items():
    print(f"Type: {pii_type}")
    for item in items:
        print(f"  - Value: {item['value']}")
        print(f"  - Position: {item['start']}-{item['end']}")
        print(f"  - Strategy: {item['mask_strategy']}")
```

## Common Issues and Solutions

### Issue: PII not being detected
**Solution**: Check that the specific detection type is enabled in config:
```yaml
config:
  detect_ssn: true  # Make sure this is true
  detect_email: true
```

### Issue: False positives (detecting non-PII)
**Solution**: Use whitelist patterns:
```yaml
config:
  whitelist_patterns:
    - "test@example.com"
    - "555-555-5555"
    - "000-00-0000"
```

### Issue: Overlapping detections
**Solution**: The plugin automatically handles overlapping patterns by keeping only the first match. If you need different behavior, adjust pattern priorities or use custom patterns.

### Issue: Plugin not running
**Solution**: Verify:
1. `PLUGINS_ENABLED=true` in `.env`
2. Plugin priority is set correctly (lower number = runs first)
3. Plugin mode is not set to "disabled"
4. Conditions match your prompts/servers

## Performance Considerations

- **Pattern Compilation**: Patterns are compiled once during initialization
- **Detection Speed**: O(n*m) where n = text length, m = number of patterns
- **Memory Usage**: Minimal - only stores compiled patterns and current detections
- **Caching**: No caching by default (stateless detection)

## Security Best Practices

1. **Production Settings**:
   - Always use `mode: "enforce"` in production
   - Enable `block_on_detection: true` for sensitive environments
   - Use `default_mask_strategy: "redact"` for complete removal

2. **Logging**:
   - Enable `log_detections: true` for audit trails
   - Monitor logs for PII detection patterns
   - Never log the actual PII values

3. **Testing**:
   - Test with realistic data patterns
   - Verify whitelist patterns don't expose real PII
   - Regularly update patterns for new PII formats


## Sample Prompt

Here's a prompt that trips the checks:

```text
Personal Info:
SSN: 123-45-6789 or 987654321
Email: john@example.com
Phone: (555) 123-4567 or +1-800-555-0199
DOB: 01/15/1985
```

## CURL Command to Test

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key)

# Then test with a prompt containing various PII
curl -X GET "http://localhost:4444/prompts/test_prompt" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "user_input": "My SSN is 123-45-6789 and email is john@example.com. Credit card: 4111-1111-1111-1111, phone (555) 123-4567. Server IP: 192.168.1.1, AWS Key: AKIAIOSFODNN7EXAMPLE"
    }
  }'
```

## Contributing

To add new PII detection patterns:

1. Add the pattern to `_compile_patterns()` method:
```python
if self.config.detect_my_pattern:
    patterns.append(PIIPattern(
        type=PIIType.MY_PATTERN,
        pattern=r'your-regex-here',
        description="Description",
        mask_strategy=MaskingStrategy.REDACT
    ))
```

2. Add configuration option to `PIIFilterConfig`:
```python
detect_my_pattern: bool = Field(default=True, description="Detect my pattern")
```

3. Add tests to verify detection and masking

## License

Apache-2.0

## Support

For issues or questions, please open an issue in the MCP Gateway repository.
