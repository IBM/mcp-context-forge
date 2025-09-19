# Retry With Backoff Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Annotates retry/backoff policy in metadata for downstream orchestration. Does not re-execute tools.

## Hooks
- tool_post_invoke
- resource_post_fetch

## Config
```yaml
config:
  max_retries: 2
  backoff_base_ms: 200
  max_backoff_ms: 5000
  retry_on_status: [429, 500, 502, 503, 504]
```

## Design
- Adds a retry policy descriptor to metadata for tools and resource fetches; no side effects.
- Fields include max retries and exponential backoff parameters; downstream decides how to apply.

## Limitations
- Purely advisory; does not perform any retry logic.
- No per-tool/resource overrides in current version.

## TODOs
- Add per-tool/resource overrides; dynamic tuning based on payload size.
- Include jitter strategy hints and orchestration examples.
