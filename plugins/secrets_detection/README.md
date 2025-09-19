# Secrets Detection Plugin

Detects likely credentials and secrets in inputs and outputs using regex and simple heuristics.

Hooks
- prompt_pre_fetch
- tool_post_invoke
- resource_post_fetch

Configuration (example)
```yaml
- name: "SecretsDetection"
  kind: "plugins.secrets_detection.secrets_detection.SecretsDetectionPlugin"
  hooks: ["prompt_pre_fetch", "tool_post_invoke", "resource_post_fetch"]
  mode: "enforce"
  priority: 45
  config:
    enabled:
      aws_access_key_id: true
      aws_secret_access_key: true
      google_api_key: true
      slack_token: true
      private_key_block: true
      jwt_like: true
      hex_secret_32: true
      base64_24: true
    redact: false                # replace matches with redaction_text
    redaction_text: "***REDACTED***"
    block_on_detection: true
    min_findings_to_block: 1
```

Notes
- Emits metadata (`secrets_findings`, `count`) when not blocking; includes up to 5 example types.
- Uses conservative regexes; combine with PII filter for broader coverage.
