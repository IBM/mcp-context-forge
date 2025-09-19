# URL Reputation Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Blocks URLs based on configured blocked domains and string patterns before resource fetch.

## Hooks
- resource_pre_fetch

## Config
```yaml
config:
  blocked_domains: ["malicious.example.com"]
  blocked_patterns: []
```

## Design
- Checks URL host against a blocked domain list (exact or subdomain match).
- Checks URL string for blocked substring patterns.
- Enforces block at `resource_pre_fetch` with structured violation details.

## Limitations
- Static lists only; no external reputation providers.
- Substring patterns only; no regex or anchors.
- Ignores scheme/port nuances beyond simple parsing.

## TODOs
- Add regex patterns and allowlist support.
- Optional threat-intel lookups with caching.
- Per-tenant/per-server override configuration.
