# OAuth 2.0 Integration Design for ContextForge

**Version**: 1.2
**Status**: Design + implementation notes
**Date**: February 2026
**Related**: [OAuth 2.0 Authorization Code Flow UI Implementation Design](./oauth-authorization-code-ui-design.md)

## Executive Summary

This document describes the design for the Admin UI initiated OAuth 2.0 Authorization Code flow for MCP gateways and how the backend stores and uses user-delegated tokens.

!!! note "Scope of This Document"
    This document covers **gateway OAuth token delegation** - how ContextForge obtains and uses OAuth tokens to authenticate with upstream MCP servers on behalf of users.

    For information about **user authentication to ContextForge** (SSO, JWT tokens, RBAC), see:

    - [RBAC Configuration](../manage/rbac.md) - Token scoping, permissions, and access control
    - [Multi-Tenancy Architecture](./multitenancy.md) - User authentication flows and team management
    - [RFC 9728 Compliance](./rfc9728-compliance.md) - OAuth Protected Resource Metadata for MCP client discovery

## Current Implementation Snapshot

### Implemented Capabilities

- Admin UI exposes OAuth configuration fields for gateways and an "Authorize" action.
- Authorization Code flow uses PKCE (S256) and an HMAC-signed state value with a 300-second TTL.
- OAuth state is stored in Redis when configured, in the database when configured, and in memory otherwise.
- Tokens are stored per gateway and app user (email) in the database, encrypted with a dedicated encryption secret.
- Refresh tokens are used when access tokens are near expiry; invalid refresh tokens are cleared.
- Dynamic Client Registration (DCR) auto-registration can run during authorization when an issuer is set but a client ID is missing.

### Known Gaps and Constraints

- Some UI options (like storing tokens and auto-refresh toggles) are not yet persisted or enforced by the backend.
- PKCE method is currently fixed to S256.
- No admin UI exists to list or revoke stored OAuth tokens per user.
- Token cleanup is currently a helper method only; there is no automated scheduler invoking it.

## Architecture Overview

The system involves interactions between the Admin UI, the Backend services (OAuth Router, OAuth Manager, Token Storage Service), a State Store (Redis/Database/Memory), the Database, and External entities (User Browser, OAuth Provider).

The "Authorize" action in the UI redirects the user through the gateway's authorization endpoint. The OAuth Manager handles the PKCE generation and state management.

## Data Model

### Gateway OAuth Configuration

Stored as JSON within the gateway record and assembled from Admin UI fields or API payloads. It includes:

- **Grant Type**: Authorization code, client credentials, or password.
- **Issuer**: OAuth Authorization Server issuer URL (required for DCR).
- **Endpoints**: Authorization URL and Token URL.
- **Redirect URI**: Must match the OAuth client registration.
- **Client Credentials**: Client ID and encrypted Client Secret.
- **User Credentials**: Username and password (for password grant only).
- **Scopes**: Array of requested scopes.
- **Resource**: Optional resource parameter; derived from the gateway URL if omitted.

### OAuth Tokens

One token record is stored per gateway and app user (email). It contains:

- **Identifiers**: Gateway ID and App User Email (unique pair), plus the User ID from the OAuth provider.
- **Tokens**: Encrypted Access Token and Refresh Token.
- **Metadata**: Token type, expiration time, granted scopes, and creation/update timestamps.

### OAuth States

Used for state storage when a database backend is configured. It tracks:

- **Identifiers**: Gateway ID and State (unique pair).
- **PKCE**: Code verifier.
- **Lifecycle**: Expiration time, used status, and creation timestamp. TTL is enforced in logic (300 seconds).

### Registered OAuth Clients

Stored when Dynamic Client Registration succeeds. It includes:

- **Configuration**: Issuer, Client ID, encrypted Client Secret.
- **Metadata**: Redirect URIs, Grant Types, Response Types, Scopes, Token Endpoint Auth Method, and Registration Client URI.
- **Lifecycle**: Creation time, expiration time, and active status.

## UI and Flow

### Admin UI Touchpoints

The gateway configuration form maps user inputs to the OAuth configuration structure. The gateway list provides an **Authorize** button for OAuth gateways, which initiates the flow.

### Authorization Code Flow

1.  **Configuration**: Admin configures gateway OAuth settings via the UI, which are saved to the database.
2.  **Initiation**: Admin clicks "Authorize". The UI requests authorization from the gateway.
3.  **Setup**: The Gateway initiates the auth code flow via the OAuth Manager, storing state and PKCE verifier in the State Store.
4.  **Redirection**: The Gateway redirects the Admin to the OAuth Provider.
5.  **Consent**: Admin logs in and grants consent at the Provider.
6.  **Callback**: Provider redirects back to the Gateway with a code and state.
7.  **Exchange**: Gateway validates state via OAuth Manager and exchanges the code for tokens.
8.  **Storage**: OAuth Manager stores access and refresh tokens via Token Store into the Database.
9.  **Completion**: Gateway shows a success page to the Admin.

### Tool Invocation using Stored Tokens

1.  **Invocation**: A Client (authenticated user) invokes a tool on the Gateway.
2.  **Retrieval**: Gateway requests a token from the Token Store for the gateway and user.
3.  **Validation**: Token Store checks expiration.
    *   **Valid**: Decrypted access token is returned.
    *   **Expired**: Token Store requests a refresh from the Provider. New tokens are stored and returned.
4.  **Execution**: Gateway forwards the tool request with the Bearer token to the MCP Server.
5.  **Response**: MCP Server responds, and the Gateway returns the result to the Client.

## Security and Operational Notes

-   **Encryption**: Tokens are encrypted at rest using a configured encryption secret.
-   **State Security**: State is an opaque random token (`secrets.token_urlsafe`), stored server-side with associated metadata, single-use, and has a short expiration (300 seconds).
-   **Scoping**: Tokens are scoped per gateway and app user (email) to prevent cross-user reuse.
-   **Resource Indicator**: The gateway derives a resource value from the gateway URL if not explicitly configured.
-   **Transport**: HTTPS is recommended in production.

## Token Exchange (RFC 8693 / On-Behalf-Of)

In addition to the Authorization Code, Client Credentials, and Password grants described above, a gateway's `oauth_config` can use `grant_type: "token-exchange"` to implement [RFC 8693 OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693) — also known as an On-Behalf-Of (OBO) flow.

### When to Use It

Use token exchange when a downstream MCP server needs to act **as the calling user**, not as a shared service identity. Unlike Client Credentials (which authenticates the gateway itself) or a stored per-user OAuth token (which requires the user to complete an interactive authorization flow against the upstream provider), token exchange lets the gateway present the user's **already-authenticated ContextForge identity** to an Authorization Server and receive back a token scoped for the downstream audience — without any extra user interaction.

Typical use case: the user authenticates to ContextForge once (JWT/SSO), and every downstream MCP server they reach through federated tools receives a token that identifies *them*, enabling per-user authorization and audit trails at the upstream service.

### Configuration Keys

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `grant_type` | yes | — | Must be `"token-exchange"` to enable this flow. |
| `token_url` | yes | — | The Authorization Server's token endpoint. Validated at config time (SSRF guard — see below). |
| `target_audience` | yes | — | The `audience` parameter sent to the AS, identifying the downstream resource the exchanged token is for. |
| `subject_token_source` | no | `inbound_user_jwt` | Where the `subject_token` for the exchange comes from. See below. |
| `requested_token_type` | no | `urn:ietf:params:oauth:token-type:access_token` | The `requested_token_type` parameter sent to the AS. |
| `client_id` / `client_secret` | yes | — | Client credentials used to authenticate the exchange request itself. `client_secret` is stored encrypted. |
| `scopes` | no | — | Optional scopes requested for the exchanged token. |

### Subject Token Sources

- **`inbound_user_jwt`** (default): The ContextForge JWT presented by the calling user on the current request is used as the `subject_token` in the exchange. This requires the inbound request to carry a verifiable JWT (not an opaque API key).
- **`user_oauth_token`**: The user's previously stored per-gateway OAuth access token (obtained via the Authorization Code flow described above) is used as the `subject_token` instead. This is supported on the tool-invocation path; gateway connection/health-check paths fail closed for `token-exchange` because they have no per-request user context.

### Security Boundary: The Inbound JWT Is Never Forwarded

!!! warning "The user's ContextForge JWT never reaches the upstream MCP server"
    With `subject_token_source: inbound_user_jwt`, the user's inbound ContextForge JWT is POSTed to `token_url` as the `subject_token`. Therefore `token_url` MUST be a trusted Identity Provider — it is validated at config time (SSRF guard), but operators must treat the ability to create or modify token-exchange gateways as a **privileged action**.

    Only the **exchanged token** returned by the Authorization Server is ever sent to the downstream MCP server as the `Bearer` credential. The gateway's own JWT is used solely as the subject of the exchange request to the trusted IdP and is discarded afterward.

### Caching

Exchanged tokens are cached (`TokenExchangeCache`, Redis-backed with an in-memory fallback) under a key derived from the gateway, user, and `target_audience`. Cache behavior:

- **TTL**: Taken from the Authorization Server's `expires_in` response field.
- **Single-flight**: Concurrent requests for the same cache key share one in-flight exchange instead of issuing duplicate calls to the AS.
- **Negative caching**: A failed exchange is cached briefly so repeated failures don't hammer the AS; callers see a "token exchange unavailable" degraded-mode error until the cooldown expires.
- **401 invalidation**: If the downstream MCP server rejects the exchanged token with `401`, the cache entry is evicted and exactly **one** re-exchange is attempted before failing.

### Shared-Issuer Trust Requirement

The Authorization Server at `token_url` must **trust the ContextForge JWT issuer** — i.e., it must be configured (directly, or via federated SSO) to accept ContextForge-issued JWTs as valid `subject_token` values for RFC 8693 exchange. Without this trust relationship, every exchange will fail with a 4xx from the AS. See [Identity Propagation](../manage/identity-propagation.md#migrating-oauth-gateways-to-token-exchange) for migration guidance and the shared-issuer setup.

### Example Configuration

```json
// inbound_user_jwt: exchange the caller's ContextForge JWT
{
  "name": "downstream-mcp",
  "url": "https://downstream.example.com/mcp",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "token-exchange",
    "token_url": "https://idp.example.com/realms/cf/protocol/openid-connect/token",
    "client_id": "contextforge",
    "client_secret": "<encrypted-at-rest>",
    "target_audience": "https://downstream.example.com",
    "subject_token_source": "inbound_user_jwt",
    "scopes": ["mcp.invoke"]
  }
}
```

`client_secret` is stored encrypted at rest (same mechanism as other gateway OAuth credentials). `target_audience` is required — gateway creation/update fails validation without it. If `subject_token_source` is omitted, it defaults to `inbound_user_jwt`.

### Troubleshooting

| Symptom (caller) | Likely cause | Where to look |
|---|---|---|
| "User authentication required…" | No inbound bearer, or an opaque (non-JWT) bearer was presented with `subject_token_source: inbound_user_jwt` | Confirm the request carried a verifiable JWT; check client auth configuration |
| "Token exchange failed… Contact your administrator." | The Authorization Server returned a 4xx/5xx for the exchange request | Server WARNING log (with stack trace) and audit entry with `error` status, searchable by `correlation_id` |
| "Token exchange unavailable…" | Negative cache is open after a recent failure (degraded mode) | Wait for the cooldown to expire; investigate the original failure that triggered the negative cache entry |
| `ValueError: target_audience is required` / `token_url` rejected at config time | Invalid or incomplete `oauth_config` for a `token-exchange` gateway | Review the gateway create/update response; check for an SSRF-validation WARNING in logs |

## Token Verification

### Gateway OAuth Tokens

OAuth tokens obtained through the Authorization Code flow are used to authenticate requests to upstream MCP servers. These tokens are:

1. **Stored encrypted**: Using `AUTH_ENCRYPTION_SECRET`
2. **Scoped per user**: Each user's token is stored separately per gateway
3. **Automatically refreshed**: When access tokens expire and refresh tokens are available
4. **Forwarded as-is**: The stored token is sent directly to the upstream MCP server as a `Bearer` header. The MCP server is responsible for validating the token's audience, scopes, and issuer.

!!! note "Known Gap: No local audience/scope pre-validation"
    The gateway does not currently inspect the token's `aud` or `scope` claims before forwarding it to the MCP server. In multi-tenant Entra ID setups with multiple app registrations, a misconfigured resource parameter could produce a token scoped for the wrong audience; the MCP server will return a 401 but the error message will not identify the root cause. Tracked for a future hardening pass.

### Relationship to Gateway Authentication

This OAuth flow is **separate** from user authentication to ContextForge itself:

| Aspect | Gateway OAuth (this doc) | User Auth to Gateway |
|--------|-------------------------|---------------------|
| Purpose | Authenticate to upstream MCP servers | Authenticate users to the gateway |
| Token storage | `oauth_tokens` table | JWT in client, session in browser |
| Verification | By upstream MCP server | By gateway (`verify_jwt_token_cached`) |
| Scope | Per gateway + user pair | Gateway-wide |

For user authentication details, see [RBAC Configuration](../manage/rbac.md).

## Inbound External-Token Validation (M2M API Auth)

The flows above describe ContextForge as an OAuth **client** delegating to upstream MCP servers. ContextForge can also act as a **resource server** for its own API/MCP endpoints, accepting access tokens minted by a trusted external SSO provider directly as `Bearer` credentials — see [SSO: Machine-to-machine API auth with external IdP tokens](../manage/sso.md#machine-to-machine-api-auth-with-external-idp-tokens) for operator-facing setup.

This path is gated by `SSO_API_TOKEN_AUTH_ENABLED` (global) and `SSOProvider.trusted_for_api_auth` + `SSOProvider.api_audience` (per provider), and is dispatched from `mcpgateway/utils/verify_credentials.py`:

1. **Issuer discrimination** (`_maybe_verify_external`): the inbound bearer token is unsigned-decoded to read its `iss` claim. If no enabled provider has `trusted_for_api_auth=True`, this path is skipped entirely and the token is evaluated only as an internal JWT. Otherwise `resolve_trusted_provider_by_issuer(iss, db)` looks up the matching `SSOProvider`.
2. **Token validation** (`verify_external_idp_token`): the token is fully verified against the matched provider's JWKS — signature, expiry, issuer, and `aud == provider.api_audience`. ID tokens are rejected; only access tokens are accepted.
3. **JIT provisioning** (`build_external_identity`): the validated token is used to provision/look up a local `EmailUser` via the same SSO service used for browser logins. `client_credentials` tokens with no `email` claim are detected (`_is_clientless_token`) and provisioned as synthetic service principals (`svc-<client_id>@<provider-id>.service.local`); both human and service principals receive teams via the provider's existing role/group → team mapping.
4. **Session-semantics payload**: the resulting identity is returned with `token_use="session"` and `source="external_idp"`. `is_admin` is read from the persisted local user record (`db_user.is_admin`), and `teams` are resolved via `resolve_session_teams()` — both DB-authoritative, never derived directly from the external token's claims. This identity then flows through the normal Layer 1 (token scoping) / Layer 2 (RBAC) pipeline exactly like any other session token.
5. **Caching**: successful resolutions are cached per-token (SHA-256 of the raw token) for `EXTERNAL_IDENTITY_CACHE_TTL` seconds (clamped to the token's `exp`), shared via Redis when `CACHE_TYPE=redis`, to avoid re-provisioning on every M2M call.

!!! note "Revocation and role-sync caveats"
    ContextForge cannot revoke an externally-issued token before its own expiry — only local user-deactivation/team-membership changes take effect immediately. If role-sync is enabled for the provider, teams/admin status are re-derived from token claims into the local DB on each provisioning pass. See the [SSO documentation](../manage/sso.md#machine-to-machine-api-auth-with-external-idp-tokens) for details.

## Future Enhancements

-   Wire UI toggles for token storage and auto-refresh to backend logic.
-   Make PKCE method configurable.
-   Add Admin UI for managing token status and revocation.
-   Implement scheduled cleanup of expired OAuth tokens.
