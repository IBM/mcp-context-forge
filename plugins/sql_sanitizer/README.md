# SQL Sanitizer Plugin

Detects risky SQL patterns and optionally sanitizes or blocks.

Capabilities
- Strip comments (`--`, `/* ... */`)
- Block dangerous statements: DROP, TRUNCATE, ALTER, GRANT, REVOKE
- Detect `DELETE` and `UPDATE` without `WHERE`
- Heuristic detection of string interpolation (optional)

Hooks
- prompt_pre_fetch
- tool_pre_invoke

Configuration (example)
```yaml
- name: "SQLSanitizer"
  kind: "plugins.sql_sanitizer.sql_sanitizer.SQLSanitizerPlugin"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
  mode: "enforce"
  priority: 40
  config:
    fields: ["sql", "query", "statement"]  # null = scan all string args
    strip_comments: true
    block_delete_without_where: true
    block_update_without_where: true
    require_parameterization: false
    blocked_statements: ["\\bDROP\\b", "\\bTRUNCATE\\b", "\\bALTER\\b"]
    block_on_violation: true
```

Notes
- This plugin uses simple, safe heuristics (no SQL parsing). For strict enforcement, use alongside SchemaGuard and policy engines.
- When `block_on_violation` is false, issues are reported via metadata while allowing execution.
