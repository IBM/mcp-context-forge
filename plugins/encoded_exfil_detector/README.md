# Encoded Exfil Detector Plugin

> Author: Mihai Criveti

Detects suspicious encoded payload exfiltration patterns in prompt arguments and tool outputs.

## Hooks
- `prompt_pre_fetch`
- `tool_post_invoke`

## What it detects
- Base64 segments
- URL-safe base64 segments
- Hex-encoded payloads
- Percent-encoded byte streams
- `\xNN` escaped hex streams

The detector decodes candidates, scores them using entropy/printability/context heuristics, then blocks or redacts based on configuration.

## Configuration example
```yaml
- name: "EncodedExfilDetector"
  kind: "plugins.encoded_exfil_detector.encoded_exfil_detector.EncodedExfilDetectorPlugin"
  hooks: ["prompt_pre_fetch", "tool_post_invoke"]
  mode: "enforce"
  priority: 52
  config:
    enabled:
      base64: true
      base64url: true
      hex: true
      percent_encoding: true
      escaped_hex: true

    min_encoded_length: 24
    min_decoded_length: 12
    min_entropy: 3.3
    min_printable_ratio: 0.70
    min_suspicion_score: 3

    max_scan_string_length: 200000
    max_findings_per_value: 50

    redact: false
    redaction_text: "***ENCODED_REDACTED***"
    block_on_detection: true
    min_findings_to_block: 1
    include_detection_details: true
```

## Behavior
- If `block_on_detection: true`, returns violation code `ENCODED_EXFIL_DETECTED`.
- If `redact: true`, replaces detected segments with `redaction_text`.
- Emits metadata with finding count and sample findings.
- Uses Rust acceleration automatically when `encoded_exfil_detection` is installed, otherwise Python fallback is used.
