# Cached Tool Result Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Caches idempotent tool results in-memory using a configurable key derived from tool name and selected argument fields.

## Hooks
- tool_pre_invoke (advisory read: sets metadata.cache_hit)
- tool_post_invoke (write-through store)

## Config
```yaml
config:
  cacheable_tools: ["search"]
  ttl: 300
  key_fields:
    search: ["q", "lang"]
```

## Design
- Pre-invoke computes a deterministic key from tool name and selected argument fields.
- Pre-invoke reads the cache and annotates `metadata.cache_hit`; post-invoke writes result with TTL.
- Uses in-memory dict; per-process cache suitable for small deployments or development.

## Limitations
- Cannot short-circuit tool execution in pre-hook (framework constraint); orchestration must decide how to act on `cache_hit`.
- In-memory cache is not shared across processes or hosts and is cleared on restart.
- No size-based eviction; simple TTL expiration only.

## TODOs
- Add Redis/Memcached backend and LRU/size-based eviction.
- Introduce a gateway-level short-circuit mechanism for cache hits.
- Configurable serialization and hashing strategies for large arguments.
