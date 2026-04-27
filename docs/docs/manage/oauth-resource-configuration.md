# OAuth Resource (Audience) Configuration

This guide explains how to configure the OAuth `resource` parameter (also known as the token audience) for gateways and A2A agents in ContextForge.

## Overview

When ContextForge performs an OAuth 2.0 Authorization Code flow, it needs to tell the Identity Provider (IdP) which resource it is requesting access to. This is done using the `resource` parameter as defined in [RFC 8707](https://datatools.ietf.org/doc/html/rfc8707).

The IdP uses this parameter to mint an access token with a matching `aud` (audience) claim. If the audience in the token doesn't match what the upstream MCP server expects, the server will reject the token with a 401 Unauthorized error.

## Automatic Handling

In most cases, you don't need to manually configure the resource field. ContextForge uses a two-stage automatic process:

1.  **Auto-Derivation**: If no resource is configured, the gateway automatically derives the origin (`scheme://netloc`) from its own URL to use as a fallback audience.
2.  **Auto-Learning**: On the first successful OAuth flow, the gateway inspects the returned access token, "learns" the actual audience used by the IdP, and persists it to the gateway configuration.

This "zero-config" approach works out of the box for most providers, including Salesforce, Azure AD, Okta, Auth0, and Authentik.

## When to Configure Explicitly

You may need to set the **Resource** field explicitly in the Admin UI if:

-   **Multiple Audiences**: Your IdP returns multiple audiences in the token and you want to enforce a specific one.
-   **Multi-tenant Entra ID**: You are using a multi-tenant Microsoft Entra ID setup with multiple app registrations where the default derivation might be ambiguous.
-   **Correcting Auto-Learn**: The first OAuth flow learned an undesirable audience (e.g., a temporary internal ID) and you want to override it with a stable one.
-   **Authoritative Validation**: You want "blocking validation" where ContextForge rejects tokens with mismatched audiences before they are even forwarded to the MCP server.

## Common Provider Patterns

| Provider | Typical Resource Value | Notes |
|----------|------------------------|-------|
| **Salesforce** | `https://api.salesforce.com` | Salesforce tokens typically use origin-level audiences. |
| **Azure AD (Entra ID)** | `api://your-application-id` | Use the Application ID URI configured in your App Registration. |
| **Authentik / ServiceNow** | *Leave Empty* | These providers often use the `client_id` as the audience. Auto-learning will pick this up automatically. |
| **Keycloak** | `account` or `your-client-name` | Keycloak often uses the client ID or a specific client role as the audience. |

## Multi-Resource Configurations

RFC 8707 allows requesting multiple resources simultaneously. In the ContextForge Admin UI, you can enter multiple values separated by commas:

`https://api.salesforce.com, api://my-custom-resource`

ContextForge will send multiple `resource` parameters in the OAuth request. During validation, a token is accepted if its `aud` claim matches *any* of the configured resources.

## Forcing a Re-learn

If your IdP configuration changes (e.g., you migrate to a new tenant or rotate client IDs) and the persisted audience becomes stale:

1.  Open the **Admin UI**.
2.  Edit the affected **Gateway** or **A2A Agent**.
3.  Clear the **Resource** field (set it to empty).
4.  Save the changes.

The next successful OAuth flow will re-trigger the auto-learning process and persist the new audience.

## Validation Behavior

ContextForge performs local validation of the token audience before forwarding:

-   **Authoritative (Blocking)**: If you have explicitly set a resource or if one has been auto-learned, validation is authoritative. Tokens that don't match are rejected locally.
-   **Advisory (Non-blocking)**: If the gateway is using the auto-derived fallback (no resource configured or learned yet), validation is advisory. A warning is logged, but the token is still forwarded to the MCP server, which remains the final authority.

!!! note
    Even if ContextForge validation passes, the upstream MCP server may still reject the token if its own internal audience configuration doesn't match what the IdP provided.
