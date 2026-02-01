# Circuit Breaker Plugin

Trips a per-tool breaker on high error rates or consecutive failures. Blocks calls during a cooldown period and implements half-open state for recovery testing.

## Hooks
- `tool_pre_invoke` - Checks if circuit is open, blocks request or allows through
- `tool_post_invoke` - Records success/failure, evaluates thresholds, updates state

## Configuration
```yaml
- name: "CircuitBreaker"
  kind: "plugins.circuit_breaker.circuit_breaker.CircuitBreakerPlugin"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  mode: "enforce_ignore_error"
  priority: 70
  config:
    error_rate_threshold: 0.5      # Fraction of failures to trip breaker (0-1)
    window_seconds: 60             # Time window for error rate calculation
    min_calls: 10                  # Minimum calls before evaluating error rate
    consecutive_failure_threshold: 5  # Consecutive failures to trip breaker
    cooldown_seconds: 60           # Duration circuit stays open
    tool_overrides: {}             # Per-tool config overrides
```

## Features

### Half-Open State
After cooldown expires, the circuit transitions to half-open state:
1. A single test request is allowed through
2. If the test succeeds, the circuit fully closes
3. If the test fails, the circuit immediately reopens for another cooldown

### Timeout Integration
Tool timeouts are counted as failures when `tool_service` sets the context flag `cb_timeout_failure`.

### Metadata Exposed
- `circuit_calls_in_window`: Total calls in sliding window
- `circuit_failures_in_window`: Failed calls in window
- `circuit_failure_rate`: Calculated failure rate (0-1)
- `circuit_consecutive_failures`: Current consecutive failure count
- `circuit_open_until`: Unix timestamp when circuit will close (0 if closed)
- `circuit_half_open`: True if in half-open testing state
- `circuit_retry_after_seconds`: Seconds until circuit closes (for retry headers)

## Notes
- Error detection uses `ToolResult.is_error` or dict keys `is_error`/`isError` (supports both snake_case and camelCase serialization)
- Violation response includes `retry_after_seconds` for rate limiting headers

## Example Scenario: Unstable Payment Gateway

**Goal**: Prevent cascading failures when the `payment_api` tool becomes unstable, slow, or times out repeatedly.

**Configuration**:
```yaml
config:
  # 1. Base Strategy (General Tools)
  window_seconds: 60
  min_calls: 10
  error_rate_threshold: 0.5
  consecutive_failure_threshold: 5
  cooldown_seconds: 30

  # 2. Specific Strategy (Critical Payment Tool)
  tool_overrides:
    payment_api:
      consecutive_failure_threshold: 2
      cooldown_seconds: 120
      min_calls: 3
```

**Configuration Breakdown & Reasons:**

| Parameter | Value | Reason |
|-----------|-------|--------|
| **`window_seconds`** | `60` | **Sliding Window**: We only care about errors in the last minute. Failures from an hour ago shouldn't affect current availability. |
| **`min_calls`** | `10` | **Sample Size**: Prevents tripping on the very first call of the day. We wait for 10 attempts (generic) or 3 (payment) to have statistical confidence before blocking. |
| **`error_rate_threshold`** | `0.5` | **Threshold**: If 50% of calls fail (e.g., 5 out of 10), the service is likely overloaded. Stop sending requests to give it breathing room. |
| **`consecutive_failure_threshold`** | `5` / `2` | **Fast Fail**: Even if the error rate is low, 5 hard failures in a row (e.g., 500 Internal Server Error) means it's down. **Override**: For `payment_api`, we stop after just 2 failures to avoid risking duplicate transactions or bad user experience. |
| **`cooldown_seconds`** | `30` / `120` | **Recovery Time**: Wait 30 seconds before trying again (Half-Open state). **Override**: Payment systems often restart slowly; we give `payment_api` a full 2 minutes (120s) to recover to prevent "flapping" (rapidly opening/closing). |
