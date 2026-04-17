# cpex-content-moderation

[![PyPI](https://img.shields.io/pypi/v/cpex-content-moderation)](https://pypi.org/project/cpex-content-moderation/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Content moderation plugin for [ContextForge](https://github.com/IBM/mcp-context-forge) — AI-powered content safety using IBM Watson, IBM Granite Guardian, OpenAI, Azure, or AWS with configurable thresholds and actions.

## Installation

```bash
pip install cpex-content-moderation
```

Or via the ContextForge gateway `[plugins]` extra (recommended):

```bash
pip install "mcp-contextforge-gateway[plugins]"
```

## Usage

In your ContextForge plugin configuration YAML:

```yaml
plugins:
  - name: "ContentModeration"
    kind: "cpex_content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    config:
      provider: "ibm_granite"
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
      audit_decisions: true
      enable_caching: true
      cache_ttl: 3600
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
