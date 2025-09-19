# Rate Limiter Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Applies fixed-window, in-memory rate limits by user, tenant, and tool.

## Hooks
- prompt_pre_fetch
- tool_pre_invoke

## Config
```yaml
config:
  by_user: "60/m"
  by_tenant: "600/m"
  by_tool:
    search: "10/m"
```

## Design
- Fixed-window counters tracked in-process using second/minute/hour buckets based on rate unit.
- Separate buckets per user, tenant, and tool; all must be within limits for a request to pass.
- Returns violations in `enforce` mode; includes remaining and reset hints in metadata.

## Limitations
- In-memory only; not shared across processes/hosts and resets on restart.
- Fixed windows are susceptible to burst-at-boundary effects; not a sliding window.
- No Redis/distributed backend in this implementation.

## TODOs
- Add Redis backend for distributed rate limiting.
- Support sliding window or token-bucket algorithms for smoother throttling.
- Add per-route/per-prompt overrides and dynamic config reload.
