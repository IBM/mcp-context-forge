# Notion MCP Server Setup Guide

This guide explains how to configure ContextForge to work with Notion's MCP server, which requires HTTP Basic Authentication for OAuth token exchange.

## Overview

Notion's MCP server (`https://mcp.notion.com/mcp`) uses OAuth 2.0 for authentication but requires client credentials to be sent as HTTP Basic Authentication during the token exchange step, as specified in [RFC 6749 Section 2.3.1](https://datatracker.ietf.org/doc/html/rfc6749#section-2.3.1).

## Configuration

To connect ContextForge to Notion's MCP server, you need to set `token_endpoint_auth_method: "client_secret_basic"` in your OAuth configuration:

```json
{
  "name": "notion-mcp",
  "url": "https://mcp.notion.com/mcp",
  "transport": "SSE",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type": "authorization_code",
    "client_id": "YOUR_NOTION_CLIENT_ID",
    "client_secret": "YOUR_NOTION_CLIENT_SECRET",
    "authorization_url": "https://api.notion.com/v1/oauth/authorize",
    "token_url": "https://api.notion.com/v1/oauth/token",
    "redirect_uri": "https://your-contextforge-domain.com/oauth/callback",
    "scopes": [],
    "token_endpoint_auth_method": "client_secret_basic"
  },
  "enabled": true
}
```

### Key Configuration Parameter

**`token_endpoint_auth_method`**: Controls how client credentials are sent during OAuth token exchange

- `"client_secret_basic"` (Required for Notion): Sends credentials as HTTP Basic Auth header
  ```
  Authorization: Basic base64(client_id:client_secret)
  ```

- `"client_secret_post"` (Default): Sends credentials in POST body
  ```
  client_id=...&client_secret=...
  ```

## Setup Steps

### 1. Create Notion Integration

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click "New integration" → "Public integration"
3. Configure:
   - **Name**: Your integration name
   - **Redirect URIs**: `https://your-contextforge-domain.com/oauth/callback`
   - **Capabilities**: Select required permissions
4. Save and note your **Client ID** and **Client Secret**

### 2. Configure ContextForge Gateway

Using the API:

```bash
curl -X POST https://your-contextforge-domain.com/gateways \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "notion-mcp",
    "url": "https://mcp.notion.com/mcp",
    "transport": "SSE",
    "auth_type": "oauth",
    "oauth_config": {
      "grant_type": "authorization_code",
      "client_id": "YOUR_NOTION_CLIENT_ID",
      "client_secret": "YOUR_NOTION_CLIENT_SECRET",
      "authorization_url": "https://api.notion.com/v1/oauth/authorize",
      "token_url": "https://api.notion.com/v1/oauth/token",
      "redirect_uri": "https://your-contextforge-domain.com/oauth/callback",
      "token_endpoint_auth_method": "client_secret_basic"
    },
    "enabled": true
  }'
```

### 3. Complete OAuth Flow

1. Navigate to the gateway in ContextForge Admin UI
2. Click "Authorize" to initiate OAuth flow
3. Grant permissions in Notion
4. You'll be redirected back to ContextForge with an active connection

### 4. Grant Page Access

After OAuth authorization, grant the integration access to specific Notion pages:

1. Open a Notion page
2. Click **•••** → **Add connections**
3. Select your integration
4. Click **Confirm**

## Troubleshooting

### Error: "401 Unauthorized" during token exchange

**Cause**: Missing or incorrect `token_endpoint_auth_method` configuration.

**Solution**: Ensure `"token_endpoint_auth_method": "client_secret_basic"` is set in your `oauth_config`.

### Error: "Integration does not have access to this page"

**Cause**: Integration hasn't been granted page access.

**Solution**: Follow step 4 above to grant access to specific pages.

### Error: "Invalid redirect_uri"

**Cause**: Redirect URI mismatch between Notion integration and ContextForge configuration.

**Solution**: Ensure the redirect URI exactly matches in both places (including protocol and path).

## References

- [Notion API Documentation](https://developers.notion.com/)
- [Notion OAuth Guide](https://developers.notion.com/docs/authorization)
- [RFC 6749 Section 2.3.1 - Client Authentication](https://datatracker.ietf.org/doc/html/rfc6749#section-2.3.1)
