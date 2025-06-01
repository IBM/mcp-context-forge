# ADR-0004: Combine JWT & Basic Auth

- *Status:* Accepted
- *Date:* 2025-02-01
- *Deciders:* Core Engineering Team

## Context

The gateway needs to support two types of clients:

- **Browser-based users** using the Admin UI
- **Headless clients** such as scripts, services, and tools

These use cases require different authentication workflows:

- Browsers prefer form-based login and session cookies.
- Automation prefers stateless, token-based access.

The current config exposes both:

- `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`
- `JWT_SECRET_KEY`, `JWT_EXPIRY_SECONDS`, and cookie settings

## Decision

We will combine both authentication modes as follows:

- **Basic Auth** secures access to `/admin`. Upon success, a short-lived **JWT cookie** is issued.
- **JWT Bearer token** (via header or cookie) is required for all API, WebSocket, and SSE requests.
- Tokens are signed using the shared `JWT_SECRET_KEY` and include standard claims (sub, exp, scopes).
- When `AUTH_REQUIRED=false`, the gateway allows unauthenticated access (dev only).

## Consequences

- ✅ Developers can log in once via browser and obtain an authenticated session.
- ✅ Scripts can use a generated JWT directly, with no credential storage.
- ❌ Tokens must be signed, rotated, and verified securely (TLS required).
- 🔄 JWTs expire and must be refreshed periodically by clients.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **JWT only** | CLI tools need a pre-acquired token; not friendly for interactive login. |
| **Basic only** | Password sent on every request; cannot easily revoke or expire credentials. |
| **OAuth2 / OpenID Connect** | Too complex for self-hosted setups; requires external identity provider. |
| **mTLS client auth** | Secure but heavy; not usable in browsers or simple HTTP clients. |

## Status

This combined authentication mechanism is implemented and enabled by default in the gateway.
