# Response Cache by Prompt Plugin

Advisory approximate cache of tool results using cosine similarity over selected string fields (e.g., `prompt`, `input`, `query`).

How it works
- tool_pre_invoke: computes a vector from configured fields and checks the in-memory cache for a similar entry; exposes `approx_cache` and `similarity` in metadata.
- tool_post_invoke: stores the result with TTL; evicts expired entries and caps cache size.

Notes
- The plugin framework does not short-circuit tool execution at pre-hook; this plugin exposes hints via metadata for higher layers to optionally use.
- Lightweight implementation with simple token frequency vectors; no external dependencies.

Configuration (example)
```yaml
- name: "ResponseCacheByPrompt"
  kind: "plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  mode: "permissive"
  priority: 120
  config:
    cacheable_tools: ["search", "retrieve"]
    fields: ["prompt", "input"]
    ttl: 900
    threshold: 0.9
    max_entries: 2000
```
