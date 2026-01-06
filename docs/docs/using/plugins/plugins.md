# Available Plugins

MCP Context Forge provides a comprehensive collection of production-ready plugins for security, performance, content transformation, and compliance. This page catalogs all available native and external plugins.

## Plugin Categories

- [Security & Safety](#security-safety)
- [Reliability & Performance](#reliability-performance)
- [Observability & Monitoring](#observability-monitoring)
- [Content Transformation & Formatting](#content-transformation-formatting)
- [Content Filtering & Validation](#content-filtering-validation)
- [Compliance & Governance](#compliance-governance)
- [Network & Integration](#network-integration)
- [Policy Enforcement](#policy-enforcement)

## Security & Safety

Plugins for protecting against security threats, detecting sensitive data, and moderating content.

| Plugin | Type | Description |
|--------|------|-------------|
| [Simple Token Auth](https://github.com/IBM/mcp-context-forge/tree/main/plugins/examples/simple_token_auth) | Native | Custom token-based authentication with file storage, expiration, and CLI management. Complete example of HTTP authentication hooks (http_pre_request, http_auth_resolve_user, http_auth_check_permission, http_post_request) |
| [PII Filter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/pii_filter) | Native | Detects and masks sensitive information including SSN, credit cards, and emails with configurable masking strategies |
| [Secrets Detection](https://github.com/IBM/mcp-context-forge/tree/main/plugins/secrets_detection) | Native | Detects likely credentials/secrets (AWS keys, API keys, JWT tokens, private keys) in inputs and outputs with optional redaction and blocking |
| [Code Safety Linter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/code_safety_linter) | Native | Detects unsafe code patterns in tool outputs (eval, exec, os.system, subprocess, rm -rf) |
| [Safe HTML Sanitizer](https://github.com/IBM/mcp-context-forge/tree/main/plugins/safe_html_sanitizer) | Native | Sanitizes HTML to remove XSS vectors, dangerous tags, event handlers, and bad URL schemes with optional text conversion |
| [SQL Sanitizer](https://github.com/IBM/mcp-context-forge/tree/main/plugins/sql_sanitizer) | Native | Detects risky SQL patterns and sanitizes/blocks dangerous statements (DROP, TRUNCATE, DELETE/UPDATE without WHERE) |
| [Harmful Content Detector](https://github.com/IBM/mcp-context-forge/tree/main/plugins/harmful_content_detector) | Native | Detects harmful content (self-harm, violence, hate speech) via lexicons and blocks or annotates accordingly |
| [Content Moderation](https://github.com/IBM/mcp-context-forge/tree/main/plugins/content_moderation) | Native | Advanced AI-powered content moderation using IBM Watson, IBM Granite Guardian, OpenAI, Azure, or AWS with configurable thresholds and actions |
| [URL Reputation](https://github.com/IBM/mcp-context-forge/tree/main/plugins/url_reputation) | Native | Static URL reputation checks using blocked domains and patterns |
| [VirusTotal Checker](https://github.com/IBM/mcp-context-forge/tree/main/plugins/virus_total_checker) | Native | Integrates with VirusTotal v3 to check URLs, domains, IPs, and file hashes before fetching with configurable blocking policies |
| [LLMGuard](https://github.com/IBM/mcp-context-forge/tree/main/plugins/external/llmguard) | External | Comprehensive AI guardrails utilizing LLM Guard library with filters and sanitizers for input prompts and model outputs. Supports complex policy expressions and vault-based anonymization |
| [ClamAV Remote](https://github.com/IBM/mcp-context-forge/tree/main/plugins/external/clamav_server) | External | External MCP server plugin that scans files and text content using ClamAV for malware detection in resources, prompts, and tool outputs |

## Reliability & Performance

Plugins for improving system reliability, performance, and resource management.

| Plugin | Type | Description |
|--------|------|-------------|
| [Circuit Breaker](https://github.com/IBM/mcp-context-forge/tree/main/plugins/circuit_breaker) | Native | Trips per-tool breaker on high error rates or consecutive failures and blocks during cooldown |
| [Watchdog](https://github.com/IBM/mcp-context-forge/tree/main/plugins/watchdog) | Native | Enforces maximum runtime for tools with warn or block actions on threshold violations |
| [Rate Limiter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/rate_limiter) | Native | Fixed-window in-memory rate limiting by user, tenant, or tool |
| [Cached Tool Result](https://github.com/IBM/mcp-context-forge/tree/main/plugins/cached_tool_result) | Native | Caches idempotent tool results in-memory with configurable TTL and key fields |
| [Response Cache by Prompt](https://github.com/IBM/mcp-context-forge/tree/main/plugins/response_cache_by_prompt) | Native | Advisory response cache using cosine similarity over prompt/input fields with configurable threshold |
| [Retry with Backoff](https://github.com/IBM/mcp-context-forge/tree/main/plugins/retry_with_backoff) | Native | Annotates retry/backoff policy in metadata with exponential backoff on specific HTTP status codes |

## Observability & Monitoring

Plugins for telemetry, tracing, and monitoring tool invocations.

| Plugin | Type | Description |
|--------|------|-------------|
| [Tools Telemetry Exporter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/tools_telemetry_exporter) | Native | Export comprehensive tool invocation telemetry to OpenTelemetry for observability and monitoring with configurable payload export |

## Content Transformation & Formatting

Plugins for transforming, formatting, and normalizing content.

| Plugin | Type | Description |
|--------|------|-------------|
| [AI Artifacts Normalizer](https://github.com/IBM/mcp-context-forge/tree/main/plugins/ai_artifacts_normalizer) | Native | Normalizes AI artifacts including smart quotes, ligatures, dashes, ellipses; removes bidi/zero-width characters; collapses spacing |
| [Argument Normalizer](https://github.com/IBM/mcp-context-forge/tree/main/plugins/argument_normalizer) | Native | Normalizes user/tool arguments with Unicode normalization, whitespace cleanup, casing strategies, date/number normalization to improve robustness |
| [Code Formatter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/code_formatter) | Native | Formats code/text outputs with lightweight normalization (indentation, trailing whitespace, newlines, optional JSON pretty-print) |
| [HTML to Markdown](https://github.com/IBM/mcp-context-forge/tree/main/plugins/html_to_markdown) | Native | Converts HTML resource content to Markdown format |
| [Markdown Cleaner](https://github.com/IBM/mcp-context-forge/tree/main/plugins/markdown_cleaner) | Native | Normalizes and tidies Markdown in prompts and resources |
| [JSON Repair](https://github.com/IBM/mcp-context-forge/tree/main/plugins/json_repair) | Native | Conservative JSON string repair for tool outputs |
| [Summarizer](https://github.com/IBM/mcp-context-forge/tree/main/plugins/summarizer) | Native | Summarizes long text using configurable LLM provider (OpenAI, Anthropic) with threshold-based activation |
| [Timezone Translator](https://github.com/IBM/mcp-context-forge/tree/main/plugins/timezone_translator) | Native | Converts ISO-like timestamps between server and user timezones |


## Content Filtering & Validation

Plugins for filtering, validating, and controlling content.

| Plugin | Type | Description |
|--------|------|-------------|
| [Deny Filter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/deny_filter) | Native | Deny list plugin for blocking specific content patterns |
| [Regex Filter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/regex_filter) | Native | Search and replace plugin using regex patterns for content filtering |
| [Resource Filter](https://github.com/IBM/mcp-context-forge/tree/main/plugins/resource_filter) | Native | Resource filtering with max content size, protocol restrictions, blocked domains, and content pattern replacement |
| [File Type Allowlist](https://github.com/IBM/mcp-context-forge/tree/main/plugins/file_type_allowlist) | Native | Allows only configured MIME types and file extensions for resources |
| [Output Length Guard](https://github.com/IBM/mcp-context-forge/tree/main/plugins/output_length_guard) | Native | Guards tool outputs by length with block or truncate strategies |
| [Schema Guard](https://github.com/IBM/mcp-context-forge/tree/main/plugins/schema_guard) | Native | Validates tool arguments and results against JSONSchema subset with optional blocking |
| [Citation Validator](https://github.com/IBM/mcp-context-forge/tree/main/plugins/citation_validator) | Native | Validates citations/links by checking reachability and optional content keywords |


## Compliance & Governance

Plugins for ensuring compliance with licenses, regulations, and governance policies.

| Plugin | Type | Description |
|--------|------|-------------|
| [Robots License Guard](https://github.com/IBM/mcp-context-forge/tree/main/plugins/robots_license_guard) | Native | Honors robots/noai and license meta tags from HTML; blocks or annotates per policy |
| [License Header Injector](https://github.com/IBM/mcp-context-forge/tree/main/plugins/license_header_injector) | Native | Injects configurable license header into code outputs with language-appropriate comments |
| [Privacy Notice Injector](https://github.com/IBM/mcp-context-forge/tree/main/plugins/privacy_notice_injector) | Native | Injects configurable privacy notice into rendered prompts (prepend/append or separate message) |


## Network & Integration

Plugins for network operations and external system integration.

| Plugin | Type | Description |
|--------|------|-------------|
| [Header Injector](https://github.com/IBM/mcp-context-forge/tree/main/plugins/header_injector) | Native | Injects custom HTTP headers for resource fetch requests via payload metadata |
| [Webhook Notification](https://github.com/IBM/mcp-context-forge/tree/main/plugins/webhook_notification) | Native | Sends HTTP webhook notifications on events, violations, and state changes with customizable templates |
| [Vault](https://github.com/IBM/mcp-context-forge/tree/main/plugins/vault) | Native | Generates bearer tokens based on vault-saved tokens for secure authentication |


## Policy Enforcement

Plugins for enforcing custom policies and business rules.

| Plugin | Type | Description |
|--------|------|-------------|
| [OPA Plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/external/opa) | External | Enforces Rego policies on tool invocations via an OPA server. Allows selective policy application per tool with context injection and customizable policy endpoints |
| [Cedar (RBAC) Plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/external/cedar) | External | Enforces RBAC-based policies on MCP servers using Cedar (leveraging the cedarpy library) or a custom DSL, for local evaluation with flexible configuration and output redaction. |

## Plugin Types

### Native Plugins

Native plugins run in-process within the gateway for maximum performance:

- **Location**: `plugins/` directory
- **Language**: Python
- **Performance**: Lowest latency
- **Configuration**: Fully-qualified class path in `plugins/config.yaml`
- **Use Cases**: PII filtering, input validation, content transformation, business rules

Example configuration:
```yaml
plugins:

  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 50
```

### External Plugins

External plugins run as separate MCP servers for independent scaling and isolation:

- **Location**: `plugins/external/` directory
- **Protocol**: MCP (STDIO or Streamable HTTP)
- **Performance**: 10-100ms latency (cached: <5ms)
- **Configuration**: `kind: "external"` with MCP connection details
- **Use Cases**: Advanced AI safety, complex ML inference, policy engines

Example configuration:
```yaml
plugins:

  - name: "OPAPluginFilter"
    kind: "external"
    priority: 10
    mcp:
      proto: STREAMABLEHTTP
      url: http://localhost:8000/mcp
```

## Getting Started

### Using Native Plugins

1. Choose plugins from the catalog above
2. Add configuration to `plugins/config.yaml`
3. Set `PLUGINS_ENABLED=true` in `.env`
4. Restart the gateway: `make dev`

### Using External Plugins

1. Build the external plugin: `cd plugins/external/opa && make build`
2. Start the plugin server: `make start`
3. Configure gateway to use external plugin in `plugins/config.yaml`
4. Restart the gateway: `make dev`

## Plugin Development

To create your own plugin, see:

- [Plugin Framework Guide](./index.md)
- [Plugin Lifecycle Guide](./lifecycle.md)
- [Plugin Architecture Specification](../../architecture/plugins/)

## Support & Contributing

- **Documentation**: [Plugin Framework Guide](./index.md)
- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Contributing**: Follow plugin structure guidelines and include comprehensive tests

For plugin-specific questions, consult the README in each plugin directory.
