# File Type Allowlist Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Allows only configured file extensions and MIME types for resource requests.

## Hooks
- resource_pre_fetch (extension check)
- resource_post_fetch (MIME check)

## Config
```yaml
config:
  allowed_extensions: [".md", ".txt", ".json"]
  allowed_mime_types: ["text/markdown", "text/plain", "application/json"]
```

## Design
- Pre-hook: checks file extension from URI against an allowlist.
- Post-hook: checks `ResourceContent.mime_type` against an allowlist.
- Fast-fail in pre-hook reduces unnecessary fetches when blocked.

## Limitations
- MIME guessing is not performed; relies on provided `mime_type` in ResourceContent.
- Extension check is simplistic and path-based; query params are not considered.
- No per-protocol rules or content sniffing.

## TODOs
- Add optional MIME detection and content sniffing safeguards.
- Add per-protocol and per-domain overrides.
- Support allow-by-size and explicit deny rules.
