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
      github_token: true
      stripe_secret_key: true
      generic_api_key_assignment: false  # Broad heuristic; enable only if you want generic header/assignment coverage
      slack_token: true
      private_key_block: true
      jwt_like: true
      hex_secret_32: true
      base64_24: false  # Broad intrinsic-shape heuristic; leave opt-in unless you explicitly want aggressive blocking
    redact: false                # replace matches with redaction_text
    redaction_text: "***REDACTED***"
    block_on_detection: true
    min_findings_to_block: 1
```

Notes
- Emits metadata (`secrets_findings`, `count`) when not blocking; includes up to 5 example types.
- Uses conservative regexes; combine with PII filter for broader coverage.
- High-confidence, label-independent detectors include `aws_access_key_id`, `google_api_key`, `github_token`, `stripe_secret_key`, and `slack_token`.
- `generic_api_key_assignment`, `jwt_like`, `hex_secret_32`, and `base64_24` are broader heuristics and can increase false positives.
- Findings are selected on the strongest surviving match for a secret-like substring, so a longer heuristic match such as `base64_24` may still catch an assignment-style value even when `generic_api_key_assignment` stays disabled.
- When broad heuristics are enabled, the plugin logs a warning at initialization so operators know blocking behavior may become noisier.

What it can do
- Reliably catch supported vendor formats that have strong intrinsic prefixes or structure, even when pasted without labels.
- Catch generic key/value assignments such as `X-API-Key: ...` or `api_key=...` when `generic_api_key_assignment` is enabled. <!-- pragma: allowlist secret -->
- Still catch some assignment-style values through broader intrinsic-shape heuristics when the value itself looks like a secret.
- Redact or block when matches are found.

What it cannot do
- It cannot guarantee 100% detection for every possible secret format across every vendor without increasing false positives.
- It does not try to detect arbitrary high-entropy strings with no recognizable structure or provider prefix.
- The generic assignment heuristic intentionally favors lower false positives over maximum recall; some unlabeled vendor-specific tokens will still require adding a dedicated pattern.

## Testing

```bash
make benchmark    # Compare Python vs Rust performance
make test         # Run integration tests
```

Benchmark shows speedup metrics and detects active implementation (Python/Rust). Integration tests use Python by default; Rust used automatically if available. Build Rust: `cd plugins_rust/secrets_detection && maturin develop --release`
