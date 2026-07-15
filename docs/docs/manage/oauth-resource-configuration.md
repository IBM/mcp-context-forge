# OAuth Resource (Audience) Configuration

This guide explains how to configure the OAuth `resource` parameter (also known as the token audience) for gateways and A2A agents in ContextForge.

## Overview

When ContextForge performs an OAuth 2.0 Authorization Code flow, it needs to tell the Identity Provider (IdP) which resource it is requesting access to. This is done using the `resource` parameter as defined in [RFC 8707](https://datatools.ietf.org/doc/html/rfc8707).

The IdP uses this parameter to mint an access token with a matching `aud` (audience) claim. If the audience in the token doesn't match what the upstream MCP server expects, the server will reject the token with a 401 Unauthorized error.

## Automatic Handling

In most cases, you don't need to manually configure the resource field. ContextForge uses a two-stage automatic process:

1.  **Auto-Derivation**: If no resource is configured, the gateway automatically derives the origin (`scheme://netloc`) from its own URL to use as a fallback audience. Real-world providers (Salesforce, Azure AD, Okta) typically issue origin-level audiences, so origin-derivation maximizes first-flow success.
2.  **Auto-Learning**: On the first successful OAuth flow, the gateway inspects the returned access token, "learns" the actual audience used by the IdP, and persists it to the gateway configuration.

This "zero-config" approach works out of the box for most providers, including Salesforce, Azure AD, Okta, Auth0, and Authentik.

### Auto-Learning Failure Recovery

If the IdP does not return an RFC 8707-compliant response on the first OAuth callback (e.g., the token has no `aud` claim, or the claim is malformed), the auto-learning step is silently skipped. The gateway will continue to use the auto-derived origin fallback for subsequent requests. This fallback remains in effect until:

-   An admin explicitly sets the **Resource** field in the gateway configuration, or
-   A future OAuth callback succeeds with a well-formed audience that can be learned

The gateway logs a DEBUG-level message when auto-learning is skipped. Set `LOG_LEVEL=DEBUG` to see these messages. Typical formats:

```
DEBUG - Skipping audience persistence for gateway X: token_aud absent or malformed
DEBUG - Skipping audience persistence for gateway X: resource already set
DEBUG - Skipping audience persistence for gateway X: token iss does not match configured issuer
```

No manual intervention is required — the system will automatically recover when a valid audience becomes available.

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

If your IdP configuration changes (e.g., you migrate to a new tenant or rotate client IDs) and the persisted audience becomes stale, **clearing the Admin UI field does not wipe the stored value**. This is a deliberate race-safety guard: an admin dialog opened before the OAuth callback ran can otherwise silently overwrite the callback's learned value on save.

To explicitly clear a stored resource and trigger re-learning on the next OAuth flow, use the API with an explicit `null`:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"oauth_config": {"resource": null, "grant_type": "authorization_code", "client_id": "...", "token_url": "...", "authorization_url": "...", "redirect_uri": "..."}}' \
  https://gateway.example.com/gateways/<gateway_id>
```

The next successful OAuth flow will re-trigger auto-learning and persist the new audience. Any oauth_config fields you omit from the PUT payload are preserved (backfilled) from the stored config, so a minimal payload targeting only `resource` works.

!!! tip "Debugging Auto-Learning"
    The gateway logs DEBUG-level messages when audience persistence is skipped (e.g., `Skipping audience persistence for gateway X: ...`). These messages are invisible at the default `LOG_LEVEL=ERROR` or `INFO`. Set `LOG_LEVEL=DEBUG` in your environment configuration to see these diagnostic messages.

## Validation Behavior

ContextForge performs local validation of the token audience before forwarding:

-   **Authoritative (Blocking)**: If you have explicitly set a resource or if one has been auto-learned, validation is authoritative. Tokens that don't match are rejected locally with a `GatewayConnectionError` and never reach the upstream MCP server.
-   **Advisory (Non-blocking, default)**: If the gateway is using the auto-derived fallback (no resource configured or learned yet), validation is advisory. A warning is logged, but the token is still forwarded to the MCP server, which remains the final authority.

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
