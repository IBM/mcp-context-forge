# Citation Validator Plugin

Validates citations/links by checking reachability (HTTP status) and optional content keywords; annotates results or blocks on policy.

Hooks
- resource_post_fetch
- tool_post_invoke

Configuration (example)
```yaml
- name: "CitationValidator"
  kind: "plugins.citation_validator.citation_validator.CitationValidatorPlugin"
  hooks: ["resource_post_fetch", "tool_post_invoke"]
  mode: "permissive"
  priority: 122
  config:
    fetch_timeout: 6.0
    require_200: true
    content_keywords: ["research", "paper"]
    max_links: 20
    block_on_all_fail: false
    block_on_any_fail: false
    user_agent: "MCP-Context-Forge/1.0 CitationValidator"
```

Notes
- Adds `citation_results` with per-URL `{ ok, status }` metadata when not blocking.
- To block on any failures set `block_on_any_fail: true`; to block only when all links fail set `block_on_all_fail: true`.
