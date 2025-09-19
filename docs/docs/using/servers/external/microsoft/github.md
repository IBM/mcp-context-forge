# GitHub Copilot MCP Server

## Overview

The GitHub Copilot MCP Server provides integration with GitHub's AI-powered development tools through the Model Context Protocol. This server enables access to GitHub Copilot features including code suggestions, repository analysis, and development assistance through a standardized MCP interface.

**Endpoint:** `https://api.githubcopilot.com/mcp`

**Authentication:** OAuth 2.1

## Features

- 🚀 Code completion and suggestions
- 📝 Code explanation and documentation
- 🔍 Repository search and analysis
- 🐛 Bug detection and fixes
- 🔄 Code refactoring suggestions
- 💡 Best practices recommendations
- 🧪 Test generation
- 📊 Code review assistance

## Authentication Setup

The GitHub Copilot MCP server uses OAuth 2.1 for secure authentication. This provides enhanced security features including PKCE (Proof Key for Code Exchange) and improved token handling.

### OAuth 2.1 Configuration

#### Step 1: Register Your Application

1. Go to [GitHub Settings > Developer settings > OAuth Apps](https://github.com/settings/developers)
2. Click "New OAuth App"
3. Fill in the application details:
   ```
   Application name: Your MCP Client
   Homepage URL: https://your-app.com
   Authorization callback URL: http://localhost:8080/callback
   ```
4. Save your `Client ID` and `Client Secret`

#### Step 2: Configure OAuth 2.1 Flow

```python
import requests
import secrets
import hashlib
import base64
from urllib.parse import urlencode

class GitHubCopilotOAuth:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_endpoint = "https://github.com/login/oauth/authorize"
        self.token_endpoint = "https://github.com/login/oauth/access_token"
        self.mcp_endpoint = "https://api.githubcopilot.com/mcp"

    def generate_pkce_challenge(self):
        """Generate PKCE code verifier and challenge for OAuth 2.1"""
        # Generate code verifier (43-128 characters)
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode('utf-8').rstrip('=')

        # Generate code challenge
        challenge = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')

        return code_verifier, code_challenge

    def get_authorization_url(self, redirect_uri, state=None):
        """Generate OAuth 2.1 authorization URL with PKCE"""
        code_verifier, code_challenge = self.generate_pkce_challenge()

        # Store code_verifier for later use in token exchange
        self.code_verifier = code_verifier

        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'scope': 'copilot:read copilot:write repo user',
            'response_type': 'code',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': state or secrets.token_urlsafe(16)
        }

        return f"{self.auth_endpoint}?{urlencode(params)}"

    def exchange_code_for_token(self, code, redirect_uri):
        """Exchange authorization code for access token (OAuth 2.1)"""
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'code_verifier': self.code_verifier  # PKCE verification
        }

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(self.token_endpoint, data=data, headers=headers)
        return response.json()
```

#### Step 3: MCP Gateway Configuration

Configure the GitHub Copilot server in your MCP Gateway:

```yaml
# config.yaml
external_servers:
  github_copilot:
    name: "GitHub Copilot"
    url: "https://api.githubcopilot.com/mcp"
    transport: "http"
    auth:
      type: "oauth2.1"
      client_id: "${GITHUB_CLIENT_ID}"
      client_secret: "${GITHUB_CLIENT_SECRET}"
      auth_url: "https://github.com/login/oauth/authorize"
      token_url: "https://github.com/login/oauth/access_token"
      scopes:
        - "copilot:read"
        - "copilot:write"
        - "repo"
        - "user"
      pkce_required: true
```

### Environment Variables

```bash
# .env file
GITHUB_CLIENT_ID=your_client_id_here
GITHUB_CLIENT_SECRET=your_client_secret_here
GITHUB_REDIRECT_URI=http://localhost:8080/callback
```

## Integration with MCP Gateway

### Register with MCP Gateway

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCP_GATEWAY_TOKEN}" \
  -d '{
    "name": "github-copilot",
    "url": "https://api.githubcopilot.com/mcp",
    "transport": "http",
    "auth_config": {
      "type": "oauth2.1",
      "client_id": "'${GITHUB_CLIENT_ID}'",
      "token_endpoint": "https://github.com/login/oauth/access_token",
      "pkce_enabled": true
    },
    "description": "GitHub Copilot AI development assistant"
  }'
```

### Complete OAuth Flow

```python
# Example OAuth 2.1 flow implementation
import asyncio
from aiohttp import web
import aiohttp

class GitHubCopilotMCPClient:
    def __init__(self, gateway_url="http://localhost:4444"):
        self.gateway_url = gateway_url
        self.oauth = GitHubCopilotOAuth(
            client_id=os.getenv("GITHUB_CLIENT_ID"),
            client_secret=os.getenv("GITHUB_CLIENT_SECRET")
        )
        self.access_token = None

    async def authenticate(self):
        """Complete OAuth 2.1 authentication flow"""
        # Step 1: Get authorization URL
        auth_url = self.oauth.get_authorization_url(
            redirect_uri="http://localhost:8080/callback"
        )

        print(f"Please visit: {auth_url}")

        # Step 2: Start local server to receive callback
        app = web.Application()
        app.router.add_get('/callback', self.handle_callback)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        await site.start()

        # Wait for callback
        while not self.access_token:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def handle_callback(self, request):
        """Handle OAuth callback"""
        code = request.query.get('code')
        state = request.query.get('state')

        if code:
            # Exchange code for token
            token_response = self.oauth.exchange_code_for_token(
                code=code,
                redirect_uri="http://localhost:8080/callback"
            )

            self.access_token = token_response['access_token']

            # Register token with MCP Gateway
            await self.register_token_with_gateway()

            return web.Response(text="Authentication successful! You can close this window.")

        return web.Response(text="Authentication failed", status=400)

    async def register_token_with_gateway(self):
        """Register OAuth token with MCP Gateway"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.gateway_url}/gateways/github-copilot/auth",
                json={
                    "access_token": self.access_token,
                    "token_type": "Bearer"
                }
            ) as response:
                return await response.json()
```

## Available Tools

### Code Completion

```json
{
  "tool": "complete_code",
  "arguments": {
    "file_path": "main.py",
    "cursor_position": {"line": 10, "column": 15},
    "context_files": ["utils.py", "config.py"],
    "language": "python"
  }
}
```

### Code Explanation

```json
{
  "tool": "explain_code",
  "arguments": {
    "code": "def fibonacci(n):\n    return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)",
    "language": "python",
    "detail_level": "detailed"
  }
}
```

### Generate Tests

```json
{
  "tool": "generate_tests",
  "arguments": {
    "code": "class Calculator:\n    def add(self, a, b):\n        return a + b",
    "framework": "pytest",
    "coverage_target": 100
  }
}
```

### Code Review

```json
{
  "tool": "review_code",
  "arguments": {
    "repository": "owner/repo",
    "pull_request": 123,
    "focus_areas": ["security", "performance", "best_practices"]
  }
}
```

## Security Best Practices

### Token Storage

```python
import keyring

class SecureTokenStorage:
    SERVICE_NAME = "github_copilot_mcp"

    @staticmethod
    def store_token(username, token):
        """Securely store OAuth token"""
        keyring.set_password(
            SecureTokenStorage.SERVICE_NAME,
            username,
            token
        )

    @staticmethod
    def get_token(username):
        """Retrieve stored token"""
        return keyring.get_password(
            SecureTokenStorage.SERVICE_NAME,
            username
        )

    @staticmethod
    def delete_token(username):
        """Remove stored token"""
        keyring.delete_password(
            SecureTokenStorage.SERVICE_NAME,
            username
        )
```

### Token Refresh

```python
async def refresh_token(refresh_token):
    """Refresh expired OAuth 2.1 token"""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": os.getenv("GITHUB_CLIENT_ID"),
                "client_secret": os.getenv("GITHUB_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            },
            headers={"Accept": "application/json"}
        ) as response:
            return await response.json()
```

## Rate Limiting

GitHub Copilot API has rate limits:

- **Authenticated requests:** 5,000 requests per hour
- **Code completions:** 100 requests per minute
- **Analysis operations:** 30 requests per minute

### Handle Rate Limits

```python
class RateLimitHandler:
    def __init__(self):
        self.remaining = None
        self.reset_time = None

    async def make_request(self, session, url, **kwargs):
        """Make request with rate limit handling"""
        async with session.request(url=url, **kwargs) as response:
            # Check rate limit headers
            self.remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
            self.reset_time = int(response.headers.get('X-RateLimit-Reset', 0))

            if response.status == 429:  # Too Many Requests
                retry_after = int(response.headers.get('Retry-After', 60))
                await asyncio.sleep(retry_after)
                return await self.make_request(session, url, **kwargs)

            return await response.json()
```

## Troubleshooting

### Common Issues

**OAuth Authentication Fails:**
```bash
# Check client credentials
echo $GITHUB_CLIENT_ID
echo $GITHUB_CLIENT_SECRET

# Verify redirect URI matches exactly
# Must be exactly as registered in GitHub OAuth App
```

**Token Expired:**
```python
# Automatic token refresh
if token_is_expired():
    new_token = await refresh_token(stored_refresh_token)
    update_stored_token(new_token)
```

**PKCE Challenge Failed:**
```python
# Ensure code_verifier is stored between auth request and token exchange
# Use session storage or secure temporary storage
session['code_verifier'] = code_verifier
```

## Example Integration

```python
# Complete example of using GitHub Copilot MCP
import asyncio
from mcp_gateway_client import MCPGatewayClient

async def main():
    # Initialize client
    client = MCPGatewayClient("http://localhost:4444")

    # Authenticate with GitHub
    copilot_client = GitHubCopilotMCPClient()
    await copilot_client.authenticate()

    # Use GitHub Copilot tools via MCP
    result = await client.call_tool(
        server="github-copilot",
        tool="complete_code",
        arguments={
            "file_path": "app.py",
            "cursor_position": {"line": 25, "column": 10},
            "language": "python"
        }
    )

    print(f"Code suggestion: {result['suggestion']}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Related Resources

- [GitHub OAuth Documentation](https://docs.github.com/en/apps/oauth-apps)
- [OAuth 2.1 Specification](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-07)
- [GitHub Copilot API Reference](https://docs.github.com/en/copilot)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)