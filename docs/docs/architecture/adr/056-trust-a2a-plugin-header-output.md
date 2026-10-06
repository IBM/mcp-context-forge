# ADR-056: Trust A2A Plugin Header Output

- *Status:* Accepted
- *Date:* 2026-10-06
- *Deciders:* Platform Team

## Context

A2A plugins supply per-call downstream credentials. The existing A2A paths filter returned plugin headers as caller input. This drops plugin credentials and can produce duplicate logical headers when casing differs.

## Decision

Trust headers returned by the A2A pre-invoke hook. Keep caller filtering and sanitized hook input unchanged.

Resolve caller, configured, plugin, and protocol headers in the shared A2A protocol layer. Compare names case-insensitively. Plugin values override configured authentication. An empty `Authorization` removes authorization from every lower-priority source. Omission removes only caller headers that the plugin received. The gateway owns required protocol headers and removes `X-Vault-Tokens` before egress.

## Consequences

Trusted plugins can inject custom credentials without an A2A caller-header allowlist entry. Operators must restrict plugin installation and bindings to trusted plugins.
