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
-   **State Security**: State is HMAC-signed, single-use, and has a short expiration (300 seconds).
-   **Scoping**: Tokens are scoped per gateway and app user (email) to prevent cross-user reuse.
-   **Resource Indicator**: The gateway derives a resource value from the gateway URL if not explicitly configured.
-   **Transport**: HTTPS is recommended in production.

## Token Verification

### Gateway OAuth Tokens

OAuth tokens obtained through the Authorization Code flow are used to authenticate requests to upstream MCP servers. These tokens are:

1. **Stored encrypted**: Using `AUTH_ENCRYPTION_SECRET`
2. **Scoped per user**: Each user's token is stored separately per gateway
3. **Automatically refreshed**: When access tokens expire and refresh tokens are available
4. **Not validated locally**: The gateway trusts the upstream OAuth provider's token response

### Relationship to Gateway Authentication

This OAuth flow is **separate** from user authentication to the ContextForge itself:

| Aspect | Gateway OAuth (this doc) | User Auth to Gateway |
|--------|-------------------------|---------------------|
| Purpose | Authenticate to upstream MCP servers | Authenticate users to the gateway |
| Token storage | `oauth_tokens` table | JWT in client, session in browser |
| Verification | By upstream MCP server | By gateway (`verify_jwt_token_cached`) |
| Scope | Per gateway + user pair | Gateway-wide |

For user authentication details, see [RBAC Configuration](../manage/rbac.md).

## Future Enhancements

-   Wire UI toggles for token storage and auto-refresh to backend logic.
-   Make PKCE method configurable.
-   Add Admin UI for managing token status and revocation.
-   Implement scheduled cleanup of expired OAuth tokens.
