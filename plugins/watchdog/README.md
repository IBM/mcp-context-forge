# Watchdog Plugin

Enforces a max runtime for tool executions, warning or blocking when exceeded.

Hooks
- tool_pre_invoke
- tool_post_invoke

Configuration (example)
```yaml
- name: "Watchdog"
  kind: "plugins.watchdog.watchdog.WatchdogPlugin"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  mode: "enforce_ignore_error"
  priority: 85
  config:
    max_duration_ms: 30000
    action: "warn"           # warn | block
    tool_overrides: {}
```

Notes
- Adds `watchdog_elapsed_ms` and `watchdog_limit_ms` to metadata; sets `watchdog_violation` on warn.
