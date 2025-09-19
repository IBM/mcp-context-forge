# Harmful Content Detector Plugin

Detects harmful content categories (self-harm, violence, hate) via regex lexicons.

Hooks
- prompt_pre_fetch
- tool_post_invoke

Configuration (example)
```yaml
- name: "HarmfulContentDetector"
  kind: "plugins.harmful_content_detector.harmful_content_detector.HarmfulContentDetectorPlugin"
  hooks: ["prompt_pre_fetch", "tool_post_invoke"]
  mode: "enforce"
  priority: 96
  config:
    categories:
      self_harm: ["\\bkill myself\\b", "\\bsuicide\\b"]
      violence: ["\\bkill (?:him|her)\\b"]
      hate: ["\\bhate speech\\b"]
    block_on: ["self_harm", "violence", "hate"]
```

Notes
- Lightweight baseline; combine with external moderation for higher recall.
