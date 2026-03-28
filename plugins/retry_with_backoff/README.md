# Retry With Backoff Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Exponential backoff retry plugin: detects transient failures and asks the gateway to re-invoke the tool after a jittered delay. The gateway owns the sleep and the retry loop (see `tool_service.py`); this plugin owns the failure detection and delay calculation.

## Hooks
- `tool_post_invoke` — active retry (detects failure, computes delay, requests re-invocation)
- `resource_post_fetch` — advisory only (attaches retry policy metadata; see Limitations)

## Config
```yaml
config:
  max_retries: 2
  backoff_base_ms: 200
  max_backoff_ms: 5000
  retry_on_status: [429, 500, 502, 503, 504]
  jitter: true
  check_text_content: false
  tool_overrides: {}
```

## Design

The plugin checks three failure signals in order:

1. **`isError`** — set to `true` when the tool raises an exception. When the
   gateway can determine the HTTP status code of the failure (e.g. from an
   `httpx.HTTPStatusError`), it includes the code in `structuredContent`.
   If a status code is present, `retry_on_status` is checked — non-transient
   errors like 400 or 404 are **not** retried. Generic exceptions without a
   status code (connection resets, timeouts) are always retried.
2. **`structuredContent.status_code`** — for tools on MCP spec 2025-03-26+; the gateway places a plain dict in `structuredContent`.
3. **Text content JSON parsing** — opt-in (`check_text_content: true`) for older MCP servers that return HTTP-style error dicts as serialised JSON in text content instead of raising exceptions. Disabled by default to avoid false-positives.

Backoff uses full-jitter exponential delay:

```
delay = random(0, min(max_backoff_ms, backoff_base_ms × 2^attempt))
```

A Rust extension (`retry_with_backoff_rust`) is used when available for signals 1 and 2, falling back to the pure-Python implementation otherwise.

### State Management

Per-invocation retry state is keyed by `(tool_name, request_id)` and cleaned up
on success or budget exhaustion. Entries orphaned by cancelled retries (e.g.
client disconnect during the backoff sleep) are automatically evicted after a
5-minute TTL.

## Tool-Level Overrides

Individual tools can override any config field:

```yaml
config:
  tool_overrides:
    my_flaky_tool:
      max_retries: 4
      backoff_base_ms: 500
```

## Limitations

- `max_retries` is clamped to the gateway-level `max_tool_retries` setting.
- `check_text_content` is off by default to avoid false-positives on tools that legitimately return status codes as informational data.
- Per-tool overrides are also clamped to the gateway ceiling.
- **Resource retry is not yet implemented.** The `resource_post_fetch` hook registers successfully and returns retry policy metadata, but does not trigger actual retries. Resource fetch failures raise exceptions before the post-fetch hook fires, so transient resource errors are not retried. Only `tool_post_invoke` performs active retry logic.
