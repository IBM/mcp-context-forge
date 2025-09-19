# Robots and License Guard Plugin

Respects basic robots/noai and license metadata embedded in HTML content.

Hooks
- resource_pre_fetch (adds User-Agent header)
- resource_post_fetch (parses HTML meta and enforces policy)

Configuration (example)
```yaml
- name: "RobotsLicenseGuard"
  kind: "plugins.robots_license_guard.robots_license_guard.RobotsLicenseGuardPlugin"
  hooks: ["resource_pre_fetch", "resource_post_fetch"]
  mode: "enforce"
  priority: 63
  config:
    user_agent: "MCP-Context-Forge/1.0"
    respect_noai_meta: true
    block_on_violation: true
    license_required: false
    allow_overrides: []
```

Notes
- Looks for `<meta name="robots" ...>`, `x-robots-tag`, `genai`, and `license` tags.
- Blocks when `noai|noimageai|nofollow|noindex` are encountered (if enabled), unless `allow_overrides` matches the URI.
