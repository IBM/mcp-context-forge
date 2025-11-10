# Simple Token Authentication Plugin

A complete replacement for JWT authentication in MCPContextForge using simple, manageable tokens.

## Overview

This plugin provides a straightforward token-based authentication system that:

- **Replaces JWT authentication** for API access
- **Uses simple token strings** instead of encoded JWTs
- **Persists tokens to a file** for durability across restarts
- **Supports token expiration** and revocation
- **Works with existing admin UI** (uses JWT for web, tokens for API)

## Features

✅ Simple token format (easy to manage and revoke)
✅ File-based persistence (survives restarts)
✅ Token expiration support
✅ Per-user and per-token revocation
✅ Admin privilege support
✅ CLI tool for token management
✅ Works alongside existing authentication

## How It Works

### Authentication Flow

1. **Token Creation**: Admin creates tokens via CLI
2. **API Request**: Client sends token in `X-Auth-Token` header
3. **Plugin Processing**:
   - `HTTP_PRE_REQUEST` hook transforms `X-Auth-Token` → `Authorization: Bearer`
   - `HTTP_AUTH_RESOLVE_USER` hook validates token and returns user info
   - `HTTP_POST_REQUEST` hook adds auth status headers to response
4. **Access Granted**: Request proceeds with authenticated user

### Token Storage

Tokens are stored in `data/auth_tokens.json`:

```json
{
  "tokens": [
    {
      "token": "abc123...",
      "email": "user@example.com",
      "full_name": "John Doe",
      "is_admin": false,
      "created_at": "2025-01-01T00:00:00Z",
      "expires_at": "2025-02-01T00:00:00Z"
    }
  ]
}
```

## Installation

### 1. Enable the Plugin

Add to `plugins/config.yaml`:

```yaml
# plugins/config.yaml - Main plugin configuration file

# Plugin directories to scan
plugin_dirs:
  - "plugins/native"      # Built-in plugins
  - "plugins/custom"      # Custom organization plugins
  - "/etc/mcpgateway/plugins"  # System-wide plugins

# Global plugin settings
plugin_settings:
  parallel_execution_within_band: true
  plugin_timeout: 120
  fail_on_plugin_error: false
  enable_plugin_api: true
  plugin_health_check_interval: 120

plugins:
  # Argument Normalizer - stabilize inputs before anything else
  - name: "CustomAuth"
    kind: "plugins.examples.simple_token_auth.simple_token_auth.SimpleTokenAuthPlugin"
    description: "Simple authentication plugin to test authentication"
    version: "0.1.0"
    author: "Teryl Taylor"
    hooks: ["http_pre_request", "http_post_request", "http_auth_resolve_user", "http_auth_check_permission"]
    tags: ["auth", "tokens", "permissions", "rbac"]
    mode: "enforce"
    priority: 40
    conditions: []
    config:
      token_header: x-auth-token          # Header name for tokens
      storage_file: data/auth_tokens.json # Where to store tokens
      default_token_expiry_days: 30       # Default expiration (null = never)
      transform_to_bearer: true            # Transform to Authorization: Bearer
```

Or create a dedicated config file in `plugins/simple_token_auth/plugin-manifest.yaml` (already included).

### 2. Configure (Optional)

The plugin uses these default settings:

```yaml
config:
  token_header: x-auth-token          # Header name for tokens
  storage_file: data/auth_tokens.json # Where to store tokens
  default_token_expiry_days: 30       # Default expiration (null = never)
  transform_to_bearer: true            # Transform to Authorization: Bearer
```


## Usage

### Creating Tokens

Use the CLI tool to create tokens:

```bash
# Create a regular user token (expires in 30 days)
python -m plugins.simple_token_auth.token_cli create user@example.com "John Doe"

# Create an admin token that never expires
python -m plugins.simple_token_auth.token_cli create admin@example.com "Admin User" --admin --expires 0

# Create a token that expires in 7 days
python -m plugins.simple_token_auth.token_cli create temp@example.com "Temp User" --expires 7
```

Output:
```
✓ Token created successfully!

User: John Doe (user@example.com)
Admin: False
Expires: 30 days

Token: k7j3h4g5f6d7s8a9w0e1r2t3y4u5i6o7

Use this token in API requests:
  curl -H 'X-Auth-Token: k7j3h4g5f6d7s8a9w0e1r2t3y4u5i6o7' http://localhost:4444/protocol/initialize
```
### Restart MCPContextForge

```bash
make serve
```

### Using Tokens

#### cURL Example

```bash
TOKEN="your-token-here"

# Initialize MCP connection
curl -X POST http://localhost:4444/protocol/initialize \
  -H "X-Auth-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test-client", "version": "1.0.0"}
  }'

# List available tools
curl http://localhost:4444/protocol/tools/list \
  -H "X-Auth-Token: $TOKEN"
```

#### Python Example

```python
import requests

TOKEN = "your-token-here"
BASE_URL = "http://localhost:4444"

headers = {
    "X-Auth-Token": TOKEN,
    "Content-Type": "application/json"
}

# Initialize connection
response = requests.post(
    f"{BASE_URL}/protocol/initialize",
    headers=headers,
    json={
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "python-client", "version": "1.0.0"}
    }
)

print(response.json())

# List tools
tools = requests.get(f"{BASE_URL}/protocol/tools/list", headers=headers)
print(tools.json())
```

#### Claude Desktop Integration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "myserver": {
      "url": "http://localhost:4444/sse",
      "headers": {
        "X-Auth-Token": "your-token-here"
      }
    }
  }
}
```

### Managing Tokens

#### List Active Tokens

```bash
python -m plugins.simple_token_auth.token_cli list
```

Output:
```
Active tokens: 2
--------------------------------------------------------------------------------

Email: user@example.com
Name: John Doe
Token: k7j3h4g5f6d7s8a9w0e1...
Created: 2025-01-01T10:00:00Z
Expires: 2025-02-01T10:00:00Z

Email: admin@example.com [ADMIN]
Name: Admin User
Token: x9y8z7w6v5u4t3s2r1q0...
Created: 2025-01-01T11:00:00Z
Expires: Never
```

#### Revoke a Specific Token

```bash
python -m plugins.simple_token_auth.token_cli revoke k7j3h4g5f6d7s8a9w0e1r2t3y4u5i6o7
```

#### Revoke All Tokens for a User

```bash
python -m plugins.simple_token_auth.token_cli revoke-user user@example.com
```

#### Clean Up Expired Tokens

```bash
python -m plugins.simple_token_auth.token_cli cleanup
```

## Security Considerations

### Token Storage

- Tokens are stored in **plaintext** in `data/auth_tokens.json`
- Ensure this file has appropriate permissions: `chmod 600 data/auth_tokens.json`
- Keep backups of this file to prevent token loss

### Token Generation

- Tokens are generated using `secrets.token_urlsafe(32)` (cryptographically secure)
- Each token is 43 characters long and URL-safe

### Best Practices

1. **Use expiration**: Set reasonable expiration times for tokens
2. **Rotate tokens**: Periodically revoke and recreate tokens
3. **Limit admin tokens**: Only create admin tokens when necessary
4. **Secure transmission**: Always use HTTPS in production
5. **Monitor usage**: Check response headers for auth status

## Coexistence with JWT

The plugin works **alongside** JWT authentication:

- **Web UI (Admin)**: Still uses JWT cookies (set by admin login)
- **API Access**: Uses simple tokens (via `X-Auth-Token` header)
- **Priority**: Simple tokens are checked first, falls back to JWT if no token

This allows you to:
- Keep the existing admin UI login working
- Use simple tokens for programmatic API access
- Gradually migrate if needed

## Response Headers

The plugin adds these headers to responses:

- `X-Auth-Status`: `authenticated` or `failed`
- `X-Auth-Method`: `simple_token` (when using this plugin)
- `X-Auth-User`: User email (when authenticated)
- `X-Correlation-ID`: Request correlation ID (if provided)

Example:
```bash
curl -I -H "X-Auth-Token: $TOKEN" http://localhost:4444/protocol/tools/list

HTTP/1.1 200 OK
X-Auth-Status: authenticated
X-Auth-Method: simple_token
X-Auth-User: user@example.com
```

## Troubleshooting

### Token Not Working

1. **Verify token exists**:
   ```bash
   python -m plugins.simple_token_auth.token_cli list
   ```

2. **Check token hasn't expired**:
   - Look for expiration date in token list
   - Run cleanup to remove expired tokens

3. **Verify header name**:
   - Default is `X-Auth-Token`
   - Check your plugin config if customized

4. **Check logs**:
   ```bash
   tail -f mcpgateway.log | grep simple_token
   ```

### Plugin Not Loading

1. **Verify plugin is enabled** in `plugins/config.yaml`
2. **Check plugin manifest** exists at `plugins/simple_token_auth/plugin-manifest.yaml`
3. **Restart server** after enabling plugin
4. **Check startup logs** for plugin loading messages

### Permission Denied

Ensure data directory is writable:
```bash
mkdir -p data
chmod 755 data
touch data/auth_tokens.json
chmod 600 data/auth_tokens.json
```

## CLI Reference

### `create` - Create a token
```bash
python -m plugins.simple_token_auth.token_cli create EMAIL FULL_NAME [--admin] [--expires DAYS]
```

Options:
- `--admin`: Grant admin privileges
- `--expires DAYS`: Days until expiration (0 = never, default: 30)

### `list` - List active tokens
```bash
python -m plugins.simple_token_auth.token_cli list [--storage FILE]
```

### `revoke` - Revoke a token
```bash
python -m plugins.simple_token_auth.token_cli revoke TOKEN
```

### `revoke-user` - Revoke all user tokens
```bash
python -m plugins.simple_token_auth.token_cli revoke-user EMAIL
```

### `cleanup` - Remove expired tokens
```bash
python -m plugins.simple_token_auth.token_cli cleanup
```

### Global Options
- `--storage FILE`: Path to token storage file (default: `data/auth_tokens.json`)

## Architecture

### Plugin Hooks

1. **`HTTP_PRE_REQUEST`**:
   - Intercepts requests before authentication
   - Transforms `X-Auth-Token` → `Authorization: Bearer TOKEN`
   - Allows downstream auth system to see token

2. **`HTTP_AUTH_RESOLVE_USER`**:
   - Validates token against storage
   - Returns user information if valid
   - Raises `PluginViolationError` if invalid
   - Sets `continue_processing=False` to skip JWT validation

3. **`HTTP_POST_REQUEST`**:
   - Adds auth status headers
   - Propagates correlation IDs
   - Tracks auth method used

### Token Lifecycle

```
┌─────────────┐
│ CLI Create  │ → Token stored in file
└─────────────┘
       │
       ↓
┌─────────────┐
│ API Request │ → X-Auth-Token: <token>
└─────────────┘
       │
       ↓
┌─────────────┐
│ Pre-Request │ → Transform to Bearer
└─────────────┘
       │
       ↓
┌─────────────┐
│ Auth Resolve│ → Validate & return user
└─────────────┘
       │
       ↓
┌─────────────┐
│ Post-Request│ → Add status headers
└─────────────┘
       │
       ↓
┌─────────────┐
│ Response    │ → Authenticated request
└─────────────┘
```

## Development

### Running Tests

```bash
# Run plugin tests
pytest tests/unit/mcpgateway/middleware/test_http_auth_integration.py::TestCustomAuthExamplePlugin -v

# Test token storage
pytest plugins/simple_token_auth/test_token_storage.py -v
```

### Debugging

Enable debug logging in `mcpgateway/config.py`:

```python
LOG_LEVEL = "DEBUG"
```

Watch plugin execution:
```bash
tail -f mcpgateway.log | grep -E "(simple_token|SimpleToken)"
```

## License

Same as MCPContextForge main project.

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review logs: `mcpgateway.log`
3. File an issue on GitHub with logs and config
