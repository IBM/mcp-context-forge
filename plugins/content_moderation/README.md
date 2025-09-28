# Content Moderation Plugin

> Author: Manav Gupta
> Version: 1.0.0

Advanced content moderation plugin using multiple AI providers including IBM Watson, IBM Granite Guardian, OpenAI, Azure, and AWS to detect and handle harmful content.

## Hooks
- `prompt_pre_fetch` - Moderate prompts before processing
- `tool_pre_invoke` - Moderate tool arguments before execution
- `tool_post_invoke` - Moderate tool outputs after execution

## Supported Providers

### IBM Watson Natural Language Understanding
- **Strengths**: Enterprise-grade, emotion analysis, multi-language support
- **Categories**: Hate speech, toxicity, harassment detection via emotion/sentiment analysis
- **Requirements**: IBM Cloud API key and service URL

### IBM Granite Guardian (via Ollama)
- **Strengths**: Local deployment, privacy-focused, no external API calls
- **Categories**: Comprehensive content safety classification
- **Requirements**: Ollama running locally with `granite3-guardian` model

### OpenAI Moderation API
- **Strengths**: High accuracy, real-time processing
- **Categories**: Hate, violence, sexual content, self-harm, harassment
- **Requirements**: OpenAI API key

### Azure Content Safety
- **Strengths**: Granular controls, custom model training
- **Categories**: Hate, violence, sexual, self-harm with severity levels
- **Requirements**: Azure Content Safety API key and endpoint

### AWS Comprehend
- **Strengths**: AWS ecosystem integration, multilingual
- **Categories**: Toxic content detection
- **Requirements**: AWS credentials and region configuration

## Event Types Detected

- **Hate Speech**: Discrimination, racist content, religious intolerance
- **Violence**: Threats, violent imagery, weapon instructions
- **Sexual Content**: Adult content, sexual harassment
- **Self-Harm**: Suicide ideation, self-injury content
- **Harassment**: Bullying, targeted abuse
- **Spam**: Promotional content, repetitive messaging
- **Profanity**: Offensive language, swear words
- **Toxic**: Generally toxic or offensive content

## Moderation Actions

- **Block**: Stop processing entirely (for severe violations)
- **Warn**: Log violation but continue processing
- **Redact**: Replace content with `[CONTENT REMOVED BY MODERATION]`
- **Transform**: Replace problematic words with filtered alternatives

## Configuration

### Basic Configuration
```yaml
- name: "ContentModeration"
  kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
  mode: "enforce"
  priority: 30
  config:
    provider: "ibm_watson"
    fallback_provider: "ibm_granite"
    fallback_on_error: "warn"

    categories:
      hate:
        threshold: 0.7
        action: "block"
      violence:
        threshold: 0.8
        action: "block"
      profanity:
        threshold: 0.6
        action: "redact"
```

### IBM Watson Configuration
```yaml
config:
  provider: "ibm_watson"
  ibm_watson:
    api_key: "${env.IBM_WATSON_API_KEY}"
    url: "${env.IBM_WATSON_URL}"
    version: "2022-04-07"
    language: "en"
    timeout: 30
```

### IBM Granite Guardian Configuration
```yaml
config:
  provider: "ibm_granite"
  ibm_granite:
    ollama_url: "http://localhost:11434"
    model: "granite3-guardian"
    temperature: 0.1
    timeout: 30
```

### OpenAI Configuration
```yaml
config:
  provider: "openai"
  openai:
    api_key: "${env.OPENAI_API_KEY}"
    api_base: "https://api.openai.com/v1"
    model: "text-moderation-latest"
    timeout: 30
```

### Multi-Provider Configuration
```yaml
config:
  provider: "ibm_watson"
  fallback_provider: "ibm_granite"
  fallback_on_error: "warn"

  ibm_watson:
    api_key: "${env.IBM_WATSON_API_KEY}"
    url: "${env.IBM_WATSON_URL}"

  ibm_granite:
    ollama_url: "http://localhost:11434"
    model: "granite3-guardian"

  openai:
    api_key: "${env.OPENAI_API_KEY}"

  categories:
    hate:
      threshold: 0.7
      action: "block"
      providers: ["ibm_watson", "ibm_granite"]
    violence:
      threshold: 0.8
      action: "block"
      providers: ["ibm_watson", "openai"]
    profanity:
      threshold: 0.6
      action: "redact"
      custom_patterns: ["\\b(specific|bad|words)\\b"]
```

## Category Configuration

Each category supports:

```yaml
categories:
  hate:
    threshold: 0.7          # Confidence threshold (0.0-1.0)
    action: "block"         # Action: block, warn, redact, transform
    providers: ["ibm_watson", "ibm_granite"]  # Which providers to use
    custom_patterns: []     # Additional regex patterns
```

## Environment Variables

### IBM Watson NLU
```bash
IBM_WATSON_API_KEY=your-watson-api-key
IBM_WATSON_URL=https://api.us-south.natural-language-understanding.watson.cloud.ibm.com
```

### OpenAI
```bash
OPENAI_API_KEY=your-openai-api-key
```

### Azure Content Safety
```bash
AZURE_CONTENT_SAFETY_KEY=your-azure-key
AZURE_CONTENT_SAFETY_ENDPOINT=https://your-resource.cognitiveservices.azure.com
```

### AWS Comprehend
```bash
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_DEFAULT_REGION=us-east-1
```

## Features

### Intelligent Fallbacks
- Primary provider failure automatically triggers fallback provider
- Pattern-based fallback when all AI providers are unavailable
- Configurable error handling (allow/block on service failure)

### Performance Optimization
- Content caching to avoid duplicate API calls
- Configurable cache TTL
- Text length limiting to control API costs
- Concurrent provider support for redundancy

### Audit and Compliance
- Comprehensive audit logging of all moderation decisions
- Confidence score reporting
- Detailed violation categorization
- Request/response metadata tracking

### Customization
- Per-category threshold configuration
- Custom regex patterns for organization-specific rules
- Flexible action mapping (block, warn, redact, transform)
- Provider-specific category routing

## Example Responses

### Clean Content
```json
{
  "flagged": false,
  "categories": {
    "hate": 0.1,
    "violence": 0.05,
    "sexual": 0.02
  },
  "action": "warn",
  "provider": "ibm_watson",
  "confidence": 0.1
}
```

### Harmful Content
```json
{
  "flagged": true,
  "categories": {
    "hate": 0.92,
    "violence": 0.15,
    "harassment": 0.78
  },
  "action": "block",
  "provider": "ibm_granite",
  "confidence": 0.92,
  "details": {
    "granite_response": "High hate speech confidence detected"
  }
}
```

## Usage Tips

1. **Start with Pattern Matching**: Use the built-in pattern fallback while setting up API providers
2. **Tune Thresholds**: Adjust category thresholds based on your content tolerance
3. **Test Incrementally**: Start with `warn` actions, then move to `block` for production
4. **Monitor Performance**: Use audit logs to track false positives/negatives
5. **Provider Selection**: Use IBM Granite for privacy, Watson for accuracy, OpenAI for speed

## Performance Considerations

- **API Costs**: Enable caching and set reasonable text length limits
- **Latency**: Consider timeout settings for user experience
- **Accuracy**: Use multiple providers for critical content paths
- **Privacy**: Use local models (Granite) for sensitive content

## Security Best Practices

1. **Secure API Keys**: Store credentials in environment variables
2. **Network Security**: Use HTTPS endpoints and validate certificates
3. **Content Privacy**: Consider local models for sensitive data
4. **Audit Logging**: Enable comprehensive decision logging
5. **Threshold Tuning**: Regularly review and adjust detection thresholds

## Troubleshooting

### Common Issues

**Plugin not loading**:
- Check plugin configuration syntax in `plugins/config.yaml`
- Verify hook names are correct
- Ensure plugin class path is accurate

**Provider authentication errors**:
- Verify API keys in environment variables
- Check service URLs and endpoints
- Test credentials with provider documentation

**High false positives**:
- Lower category thresholds
- Adjust provider selection
- Add custom whitelist patterns

**Performance issues**:
- Enable caching
- Reduce text length limits
- Optimize timeout settings
- Use faster providers for real-time scenarios

### Debug Logging
```bash
export LOG_LEVEL=DEBUG
# Check logs for detailed moderation decisions
```

## Integration Examples

### With Slack Notifications
Combine with webhook plugin to send moderation alerts:
```yaml
# Webhook plugin config
events: ["harmful_content", "violation"]
```

### With Rate Limiting
Sequential processing for comprehensive safety:
```yaml
# ContentModeration: priority 30
# RateLimiter: priority 50
```

### Enterprise Deployment
Multi-provider redundancy for high-availability:
```yaml
provider: "ibm_watson"
fallback_provider: "azure"
# Plus OpenAI for specific categories
```
