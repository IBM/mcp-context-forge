# OAuth 2.0 Setup Guide for MCP Gateway

This guide explains how to configure OAuth 2.0 authentication for federated gateways in MCP Gateway.

## Overview

MCP Gateway supports OAuth 2.0 authentication for connecting to external MCP servers that require OAuth-based authentication. This eliminates the need to store long-lived personal access tokens and provides secure, scoped access to external services.

## Supported OAuth Flows

### 1. Client Credentials Flow (Machine-to-Machine)
- **Use Case**: Server-to-server communication where no user interaction is required
- **Best For**: Automated services, background jobs, API integrations
- **Configuration**: Requires client ID, client secret, and token URL

### 2. Authorization Code Flow (User Delegation)
- **Use Case**: User-authorized access to external services
- **Best For**: User-specific integrations, services requiring user consent
- **Configuration**: Requires additional authorization URL and redirect URI

## Configuration

### Environment Variables

Add these to your `.env` file:

```env
# OAuth Configuration
OAUTH_REQUEST_TIMEOUT=30        # OAuth request timeout in seconds
OAUTH_MAX_RETRIES=3            # Max retries for token requests

# Encryption (for client secrets)
AUTH_ENCRYPTION_SECRET=your-secure-encryption-key  # Must be at least 32 characters
```

### Gateway Configuration

When adding a new gateway through the Admin UI:

1. **Authentication Type**: Select "OAuth 2.0"
2. **Grant Type**: Choose between "Client Credentials" or "Authorization Code"
3. **Client ID**: Your OAuth application's client ID
4. **Client Secret**: Your OAuth application's client secret (will be encrypted)
5. **Token URL**: OAuth provider's token endpoint
6. **Scopes**: Space-separated list of required scopes (e.g., "repo read:user")

#### Authorization Code Flow Additional Fields

If using Authorization Code flow, also configure:

- **Authorization URL**: OAuth provider's authorization endpoint
- **Redirect URI**: Callback URL (typically `https://your-gateway.com/oauth/callback`)

## Example Configurations

### GitHub OAuth App

```json
{
  "grant_type": "authorization_code",
  "client_id": "your_github_app_id",
  "client_secret": "your_github_app_secret",
  "authorization_url": "https://github.com/login/oauth/authorize",
  "token_url": "https://github.com/login/oauth/access_token",
  "redirect_uri": "https://gateway.example.com/oauth/callback",
  "scopes": ["repo", "read:user"]
}
```

### Generic OAuth Provider (Client Credentials)

```json
{
  "grant_type": "client_credentials",
  "client_id": "your_client_id",
  "client_secret": "your_client_secret",
  "token_url": "https://oauth.example.com/token",
  "scopes": ["api:read", "api:write"]
}
```

## Security Features

### Client Secret Encryption
- Client secrets are automatically encrypted using AES-256 encryption
- Encryption key derived from `AUTH_ENCRYPTION_SECRET`
- Secrets are never stored in plain text

### Token Management
- Access tokens are requested fresh for each operation
- No token caching or storage
- Automatic retry with exponential backoff on failures

### HTTPS Enforcement
- All OAuth endpoints must use HTTPS
- Redirect URIs must use secure protocols

## Troubleshooting

### Common Issues

1. **Invalid Client Credentials**
   - Verify client ID and secret are correct
   - Ensure OAuth app is properly configured with the provider

2. **Invalid Redirect URI**
   - Check that redirect URI matches exactly what's configured in OAuth app
   - Ensure protocol (http/https) matches

3. **Scope Issues**
   - Verify requested scopes are available for your OAuth app
   - Check provider's scope documentation

4. **Network Issues**
   - Verify token and authorization URLs are accessible
   - Check firewall and network configuration

### Debug Logging

Enable debug logging to troubleshoot OAuth issues:

```env
LOG_LEVEL=DEBUG
```

Look for OAuth-related log messages in the gateway logs.

## API Endpoints

### OAuth Callback
- **URL**: `GET /oauth/callback`
- **Purpose**: Handle authorization code exchange
- **Parameters**: `code`, `state`, `gateway_id`
- **Authentication**: Required

## Testing

### Test OAuth Configuration

1. Configure OAuth settings in the Admin UI
2. Test the gateway connection
3. Verify tools/resources are accessible
4. Check logs for OAuth-related messages

### Unit Tests

Run OAuth unit tests:

```bash
pytest tests/unit/mcpgateway/test_oauth_manager.py -v
```

## Best Practices

1. **Use Strong Encryption Keys**: Generate a strong `AUTH_ENCRYPTION_SECRET`
2. **Minimal Scopes**: Request only the scopes you actually need
3. **Secure Storage**: Keep encryption keys secure and rotate regularly
4. **Monitor Usage**: Watch for unusual OAuth activity
5. **Regular Testing**: Test OAuth flows regularly to ensure they work

## Migration from Personal Access Tokens

To migrate from PAT-based authentication to OAuth:

1. Create OAuth app with your service provider
2. Configure OAuth settings in gateway
3. Test connection and functionality
4. Remove old PAT-based configuration
5. Update any hardcoded authentication references

## Support

For OAuth-related issues:

1. Check the troubleshooting section above
2. Review gateway logs for error messages
3. Verify OAuth provider configuration
4. Test with a simple OAuth client first
5. Check provider's OAuth documentation
