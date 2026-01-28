# Circuit Breaker Plugin

Trips a per-tool breaker on high error rates or consecutive failures. Blocks calls during a cooldown period.

Hooks
- tool_pre_invoke
- tool_post_invoke

Configuration (example)
```yaml
- name: "CircuitBreaker"
  kind: "plugins.circuit_breaker.circuit_breaker.CircuitBreakerPlugin"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  mode: "enforce_ignore_error"
  priority: 70
  config:
    error_rate_threshold: 0.5
    window_seconds: 60
    min_calls: 10
    consecutive_failure_threshold: 5
    cooldown_seconds: 60
    tool_overrides: {}
```

Notes
- Error detection uses ToolResult.is_error when available, or a dict key "is_error".
- Exposes metadata: failure rate, counts, open_until.
