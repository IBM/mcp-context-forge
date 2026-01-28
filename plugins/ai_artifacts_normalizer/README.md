# AI Artifacts Normalizer Plugin

Normalizes common AI output artifacts: replaces smart quotes and ligatures, converts en/em dashes to '-', ellipsis to '...', removes bidi/zero-width controls, and collapses excessive spacing.

Hooks
- prompt_pre_fetch
- resource_post_fetch
- tool_post_invoke

Configuration (example)
```yaml
- name: "AIArtifactsNormalizer"
  kind: "plugins.ai_artifacts_normalizer.ai_artifacts_normalizer.AIArtifactsNormalizerPlugin"
  hooks: ["prompt_pre_fetch", "resource_post_fetch", "tool_post_invoke"]
  mode: "permissive"
  priority: 138
  config:
    replace_smart_quotes: true
    replace_ligatures: true
    remove_bidi_controls: true
    collapse_spacing: true
    normalize_dashes: true
    normalize_ellipsis: true
```

Notes
- Complements ArgumentNormalizer (Unicode NFC, whitespace) with safety-oriented cleanup (bidi controls, ligatures, smart punctuation).
