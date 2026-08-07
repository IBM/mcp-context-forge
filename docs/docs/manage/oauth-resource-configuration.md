# OAuth Resource (Audience) Configuration

This guide explains how to configure the OAuth `resource` parameter (also known as the token audience) for gateways and A2A agents in ContextForge.

## Overview

When ContextForge performs an OAuth 2.0 Authorization Code flow, it needs to tell the Identity Provider (IdP) which resource it is requesting access to. This is done using the `resource` parameter as defined in [RFC 8707](https://datatools.ietf.org/doc/html/rfc8707).

The IdP uses this parameter to mint an access token with a matching `aud` (audience) claim. If the audience in the token doesn't match what the upstream MCP server expects, the server will reject the token with a 401 Unauthorized error.

## Automatic Handling

In most cases, you don't need to manually configure the resource field. ContextForge uses a two-stage automatic process:

1.  **Auto-Derivation** (outbound): If no resource is configured, the gateway automatically derives the origin (`scheme://netloc`) from its own URL and sends it to the IdP as the RFC 8707 `resource` parameter. Real-world providers (Salesforce, Azure AD, Okta) typically issue origin-level audiences, so origin-derivation maximizes first-flow success.
2.  **Per-User Auto-Learning** (inbound validation): On each user's OAuth callback, the gateway inspects the returned access token's `aud` (and `iss`) claims and persists them **on that user's own OAuth token row** (`OAuthToken.learned_aud`). Subsequent validation for THAT USER checks their token's `aud` against their own learned value.

This "zero-config" approach works out of the box for most providers, including Salesforce, Azure AD, Okta, Auth0, and Authentik, without any shared-config mutation.

### Why per-user learning?

Storing learned audience per-user (instead of on shared gateway config) prevents two failure modes:

-   **Multi-tenant DoS**: A single gateway can serve users from multiple IdP tenants with per-tenant `aud` values. Each tenant's users get their own learned value; one tenant cannot lock out others by pinning the audience for everyone.
-   **RBAC bypass**: The OAuth callback path only enforces gateway *access* (visibility/team membership), not `gateways.update`. Per-user storage keeps writes scoped to the caller's own OAuthToken row, so no user can mutate config on behalf of others.

### Auto-Learning Failure Recovery

If the IdP returns a token whose `aud` cannot be extracted (opaque tokens, decode failures, missing claims), the learned value stays `None` for that user. The validator then falls back to `oauth_config.resource` if configured, or to the gateway URL origin (advisory). The next successful OAuth flow for that user will populate their learned value.

## When to Configure Explicitly

You may need to set the **Resource** field explicitly in the Admin UI if:

-   **Multiple Audiences**: Your IdP returns multiple audiences in the token and you want to enforce a specific set. Configure as a comma-, whitespace-, or newline-separated list.
-   **Multi-tenant Entra ID**: You are using a multi-tenant Microsoft Entra ID setup with multiple app registrations where the default derivation might be ambiguous.
-   **Correcting Auto-Learn**: The first OAuth flow learned an undesirable audience (e.g., a temporary internal ID) and you want to override it with a stable one.
-   **Authoritative Validation**: You want "blocking validation" where ContextForge rejects tokens with mismatched audiences before they are even forwarded to the MCP server. See also `OAUTH_REQUIRE_CONFIGURED_RESOURCE` below for making the auto-derived-fallback case authoritative too.

## Common Provider Patterns

| Provider | Typical Resource Value | Notes |
|----------|------------------------|-------|
| **Salesforce** | `https://api.salesforce.com` | Salesforce tokens typically use origin-level audiences; ContextForge's origin-derivation fallback matches this automatically. |
| **Azure AD (Entra ID)** | `api://your-application-id` | Use the Application ID URI configured in your App Registration. |
| **Authentik / ServiceNow** | *Leave Empty* | These providers often use the `client_id` as the audience. Auto-learning will pick this up automatically on the first successful flow. |
| **Keycloak** | *Configuration-dependent* | Keycloak audience behavior depends on client scope configuration, audience mappers, and whether "Use Client ID As Audience" is enabled. Consult your Keycloak audience mapper documentation. Auto-learning typically handles this. |

## Multi-Resource Configurations

RFC 8707 allows requesting multiple resources simultaneously. In the ContextForge Admin UI, enter multiple values separated by commas, whitespace, or newlines:

`https://api.salesforce.com, api://my-custom-resource`

ContextForge will send multiple `resource` parameters in the OAuth request. During validation, a token is accepted if its `aud` claim matches *any* of the configured resources.

!!! note "Resource URIs containing commas"
    URI paths and query components can legitimately contain unescaped commas (RFC 3986 pchar). The parser splits on `[,\s]+` **only when every resulting piece parses as an absolute URI**; if any piece would fail that check (no scheme), the whole input is stored as a single-URI resource. In practice: a single resource URI with commas in its query string is preserved intact.

## Forcing a Re-learn

Two scenarios, two workflows:

**Per-user learned audience is stale for one user** (typical case: IdP config changed, that user's next login will still match their old learned value):

- Nothing to do — that user simply re-authenticates. The next OAuth callback overwrites their `OAuthToken.learned_aud` with the new audience. No admin action needed.

**Admin-configured `oauth_config.resource` is stale** (typical case: you set it explicitly and now want to clear it):

1.  Open the **Admin UI**, edit the affected gateway or A2A agent.
2.  Clear the **Resource** field.
3.  Save.

The stored `oauth_config.resource` is wiped. Subsequent OAuth flows fall back to origin derivation for the outbound `resource` parameter, and inbound validation uses per-user learned values (or the origin fallback for users who haven't authenticated yet).

Equivalent API workflow:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"oauth_config": {"resource": null, "grant_type": "authorization_code", "client_id": "..."}}' \
  https://gateway.example.com/gateways/<gateway_id>
```

## Validation Behavior

ContextForge performs local validation of the token audience before forwarding, with a three-level precedence:

| Precedence | Source | Severity |
|---|---|---|
| 1 (highest) | `oauth_config.resource` — admin-configured | Authoritative (blocking on mismatch) |
| 2 | `OAuthToken.learned_aud` — this user's own learned value | Authoritative (blocking on mismatch for THIS USER) |
| 3 (fallback) | Gateway URL origin — auto-derived | Advisory (warning-only; upstream MCP server is the final authority) |

The advisory fallback (#3) only applies to users whose OAuth flow has not yet successfully populated a learned value. Once a user completes at least one successful OAuth flow, their subsequent tokens are validated authoritatively against their own learned audience.

To make the auto-derived-fallback case authoritative too — that is, to have ContextForge itself reject audience mismatches in strict deployments — set:

```bash
# .env
OAUTH_REQUIRE_CONFIGURED_RESOURCE=true
```

With this setting on, an audience mismatch is blocking regardless of whether the expected value was configured, learned, or auto-derived.

!!! warning "Advisory Validation Security Exposure"
    When validation is advisory (auto-derived fallback mode with `OAUTH_REQUIRE_CONFIGURED_RESOURCE=false`), a token with a mismatched audience will still be forwarded to the upstream MCP server. If the MCP server does not enforce its own audience validation, the token may be accepted — creating a privilege-escalation risk rooted in IdP or MCP server misconfiguration. Operators relying on advisory validation must ensure their upstream MCP servers perform strict audience checks, or enable `OAUTH_REQUIRE_CONFIGURED_RESOURCE=true` to make the gateway itself authoritative.

!!! note
    Even if ContextForge validation passes, the upstream MCP server may still reject the token if its own internal audience configuration doesn't match what the IdP provided.
