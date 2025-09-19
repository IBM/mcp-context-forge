# Box MCP Server

## Overview

The Box MCP Server provides seamless integration with Box's cloud content management and collaboration platform through the Model Context Protocol. This server enables AI applications to interact with Box storage, manage files and folders, collaborate on documents, and leverage Box's enterprise content management features.

**Endpoint:** `https://mcp.box.com`

**Authentication:** OAuth 2.1

## Features

- 📁 File and folder management
- 📤 Upload and download capabilities
- 🔍 Content search and metadata
- 👥 Collaboration and sharing
- 📝 Comments and annotations
- 🔐 Enterprise-grade security
- 📊 Analytics and reporting
- 🔄 Version control
- 🏷️ Tagging and classification
- 🔗 Integration with Box Skills

## Authentication Setup

Box MCP uses OAuth 2.1 for secure authentication, providing enhanced security with PKCE and improved token management.

### OAuth 2.1 Configuration

#### Step 1: Create Box Application

1. Go to [Box Developer Console](https://app.box.com/developers/console)
2. Click "Create New App"
3. Choose "Custom App"
4. Select "OAuth 2.0 with JWT" or "OAuth 2.0"
5. Name your application
6. Configure OAuth 2.0 settings:
   ```
   Redirect URI: http://localhost:8080/callback
   Application Scopes: Select required permissions
   CORS Domains: http://localhost:8080 (for development)
   ```
7. Save your `Client ID` and `Client Secret`

#### Step 2: OAuth 2.1 Implementation

```python
import requests
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode, parse_qs, urlparse

class BoxOAuth21Client:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_base_url = "https://account.box.com/api/oauth2"
        self.api_base_url = "https://api.box.com/2.0"
        self.mcp_endpoint = "https://mcp.box.com"

        # OAuth 2.1 endpoints
        self.authorize_url = f"{self.auth_base_url}/authorize"
        self.token_url = f"{self.auth_base_url}/token"
        self.revoke_url = f"{self.auth_base_url}/revoke"

    def generate_pkce_pair(self):
        """Generate PKCE code verifier and challenge for OAuth 2.1"""
        # Generate code verifier (43-128 characters, URL-safe)
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(64)
        ).decode('utf-8').rstrip('=')

        # Generate code challenge using SHA256
        challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')

        return code_verifier, code_challenge

    def get_authorization_url(self, redirect_uri, scopes=None, state=None):
        """Generate OAuth 2.1 authorization URL with PKCE"""
        self.code_verifier, code_challenge = self.generate_pkce_pair()

        # Default Box scopes for MCP operations
        if scopes is None:
            scopes = [
                "root_readonly",      # Read all files and folders
                "root_readwrite",     # Read and write all files and folders
                "manage_enterprise",  # Manage enterprise settings
                "manage_webhook",     # Manage webhooks
                "manage_data_retention",  # Manage retention policies
                "manage_data_classification"  # Manage classifications
            ]

        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'state': state or secrets.token_urlsafe(32),
            'scope': ' '.join(scopes),
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }

        return f"{self.authorize_url}?{urlencode(params)}", params['state']

    def exchange_code_for_tokens(self, code, redirect_uri):
        """Exchange authorization code for access and refresh tokens"""
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': redirect_uri,
            'code_verifier': self.code_verifier  # PKCE verification
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        response = requests.post(self.token_url, data=data, headers=headers)

        if response.status_code == 200:
            tokens = response.json()
            return {
                'access_token': tokens['access_token'],
                'refresh_token': tokens.get('refresh_token'),
                'expires_in': tokens.get('expires_in', 3600),
                'token_type': tokens.get('token_type', 'Bearer'),
                'scope': tokens.get('scope', '').split(' ')
            }
        else:
            raise Exception(f"Token exchange failed: {response.text}")

    def refresh_access_token(self, refresh_token):
        """Refresh expired access token using refresh token"""
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(self.token_url, data=data, headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Token refresh failed: {response.text}")

    def revoke_token(self, token, token_type='access_token'):
        """Revoke access or refresh token"""
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'token': token
        }

        response = requests.post(self.revoke_url, data=data)
        return response.status_code == 200
```

#### Step 3: MCP Gateway Integration

Configure Box MCP in your MCP Gateway:

```yaml
# config.yaml
external_servers:
  box:
    name: "Box Content Management"
    url: "https://mcp.box.com"
    transport: "http"
    auth:
      type: "oauth2.1"
      client_id: "${BOX_CLIENT_ID}"
      client_secret: "${BOX_CLIENT_SECRET}"
      auth_url: "https://account.box.com/api/oauth2/authorize"
      token_url: "https://account.box.com/api/oauth2/token"
      scopes:
        - "root_readonly"
        - "root_readwrite"
        - "manage_enterprise"
        - "manage_webhook"
      pkce_required: true
      token_refresh: true
```

### Environment Variables

```bash
# .env file
BOX_CLIENT_ID=your_box_client_id
BOX_CLIENT_SECRET=your_box_client_secret
BOX_REDIRECT_URI=http://localhost:8080/callback
BOX_WEBHOOK_SECRET=your_webhook_secret
```

## Integration Example

### Complete OAuth 2.1 Flow with MCP Gateway

```python
import asyncio
import aiohttp
from aiohttp import web
import os
from datetime import datetime, timedelta

class BoxMCPGatewayClient:
    def __init__(self, gateway_url="http://localhost:4444"):
        self.gateway_url = gateway_url
        self.oauth_client = BoxOAuth21Client(
            client_id=os.getenv("BOX_CLIENT_ID"),
            client_secret=os.getenv("BOX_CLIENT_SECRET")
        )
        self.tokens = None
        self.token_expiry = None

    async def authenticate_interactive(self):
        """Interactive OAuth 2.1 authentication flow"""
        redirect_uri = "http://localhost:8080/callback"

        # Step 1: Generate authorization URL
        auth_url, state = self.oauth_client.get_authorization_url(redirect_uri)

        print(f"Please visit this URL to authorize the application:")
        print(f"{auth_url}\n")

        # Step 2: Start local server to receive callback
        app = web.Application()
        app['state'] = state
        app['auth_complete'] = asyncio.Event()

        async def handle_callback(request):
            # Verify state parameter
            received_state = request.query.get('state')
            if received_state != app['state']:
                return web.Response(text="Invalid state parameter", status=400)

            # Get authorization code
            code = request.query.get('code')
            if not code:
                error = request.query.get('error')
                return web.Response(text=f"Authorization failed: {error}", status=400)

            # Exchange code for tokens
            try:
                self.tokens = self.oauth_client.exchange_code_for_tokens(code, redirect_uri)
                self.token_expiry = datetime.now() + timedelta(seconds=self.tokens['expires_in'])

                # Register with MCP Gateway
                await self.register_with_gateway()

                app['auth_complete'].set()
                return web.Response(text="Authentication successful! You can close this window.")
            except Exception as e:
                return web.Response(text=f"Token exchange failed: {str(e)}", status=500)

        app.router.add_get('/callback', handle_callback)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        await site.start()

        # Wait for authentication to complete
        await app['auth_complete'].wait()
        await runner.cleanup()

        print("Authentication completed successfully!")

    async def register_with_gateway(self):
        """Register Box MCP server with MCP Gateway"""
        async with aiohttp.ClientSession() as session:
            # Register the server
            server_data = {
                "name": "box",
                "url": "https://mcp.box.com",
                "transport": "http",
                "auth_config": {
                    "type": "oauth2.1",
                    "access_token": self.tokens['access_token'],
                    "refresh_token": self.tokens.get('refresh_token'),
                    "token_type": self.tokens['token_type'],
                    "expires_at": self.token_expiry.isoformat()
                },
                "description": "Box content management and collaboration"
            }

            async with session.post(
                f"{self.gateway_url}/gateways",
                json=server_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    self.gateway_id = result['id']
                    print(f"Registered with MCP Gateway: {self.gateway_id}")
                else:
                    raise Exception(f"Gateway registration failed: {await response.text()}")

    async def ensure_token_valid(self):
        """Ensure access token is valid, refresh if needed"""
        if self.token_expiry and datetime.now() >= self.token_expiry - timedelta(minutes=5):
            # Token expired or about to expire, refresh it
            print("Refreshing access token...")
            new_tokens = self.oauth_client.refresh_access_token(self.tokens['refresh_token'])

            self.tokens['access_token'] = new_tokens['access_token']
            if 'refresh_token' in new_tokens:
                self.tokens['refresh_token'] = new_tokens['refresh_token']

            self.token_expiry = datetime.now() + timedelta(seconds=new_tokens['expires_in'])

            # Update gateway with new token
            await self.update_gateway_token()

    async def update_gateway_token(self):
        """Update MCP Gateway with refreshed token"""
        async with aiohttp.ClientSession() as session:
            update_data = {
                "access_token": self.tokens['access_token'],
                "expires_at": self.token_expiry.isoformat()
            }

            async with session.patch(
                f"{self.gateway_url}/gateways/{self.gateway_id}/auth",
                json=update_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    print(f"Warning: Failed to update gateway token: {await response.text()}")
```

## Available MCP Tools

### File Operations

#### upload_file
```json
{
  "tool": "upload_file",
  "arguments": {
    "parent_folder_id": "0",
    "file_name": "report.pdf",
    "file_content": "base64_encoded_content",
    "description": "Q4 2024 Financial Report"
  }
}
```

#### download_file
```json
{
  "tool": "download_file",
  "arguments": {
    "file_id": "123456789",
    "version": "latest"
  }
}
```

#### search_content
```json
{
  "tool": "search_content",
  "arguments": {
    "query": "financial report 2024",
    "type": "file",
    "content_types": ["pdf", "docx"],
    "limit": 20
  }
}
```

### Folder Management

#### create_folder
```json
{
  "tool": "create_folder",
  "arguments": {
    "name": "Q4 Reports",
    "parent_id": "0",
    "description": "Quarterly reports for Q4 2024"
  }
}
```

#### list_folder_items
```json
{
  "tool": "list_folder_items",
  "arguments": {
    "folder_id": "123456",
    "fields": ["name", "size", "modified_at", "shared_link"],
    "limit": 100
  }
}
```

### Collaboration

#### share_file
```json
{
  "tool": "share_file",
  "arguments": {
    "file_id": "987654321",
    "access_level": "viewer",
    "emails": ["user@example.com"],
    "message": "Please review this document",
    "can_download": true,
    "expires_at": "2024-12-31T23:59:59Z"
  }
}
```

#### add_comment
```json
{
  "tool": "add_comment",
  "arguments": {
    "file_id": "123456789",
    "message": "Great work on this section!",
    "tagged_users": ["user@example.com"]
  }
}
```

### Metadata & Classification

#### add_metadata
```json
{
  "tool": "add_metadata",
  "arguments": {
    "file_id": "123456789",
    "template": "contract",
    "metadata": {
      "contract_type": "NDA",
      "expiry_date": "2025-12-31",
      "parties": ["Company A", "Company B"]
    }
  }
}
```

#### classify_file
```json
{
  "tool": "classify_file",
  "arguments": {
    "file_id": "123456789",
    "classification": "Confidential",
    "classification_definition_id": "abc123"
  }
}
```

## Security Features

### Secure Token Storage

```python
import keyring
from cryptography.fernet import Fernet

class SecureBoxTokenStorage:
    def __init__(self, user_id):
        self.user_id = user_id
        self.service_name = "box_mcp_tokens"

        # Generate or retrieve encryption key
        self.encryption_key = self._get_or_create_key()

    def _get_or_create_key(self):
        """Get or create encryption key for token storage"""
        key = keyring.get_password(self.service_name, f"{self.user_id}_key")
        if not key:
            key = Fernet.generate_key().decode()
            keyring.set_password(self.service_name, f"{self.user_id}_key", key)
        return key.encode()

    def store_tokens(self, tokens):
        """Securely store OAuth tokens"""
        f = Fernet(self.encryption_key)
        encrypted_tokens = f.encrypt(json.dumps(tokens).encode())
        keyring.set_password(
            self.service_name,
            f"{self.user_id}_tokens",
            encrypted_tokens.decode()
        )

    def retrieve_tokens(self):
        """Retrieve and decrypt stored tokens"""
        encrypted = keyring.get_password(self.service_name, f"{self.user_id}_tokens")
        if encrypted:
            f = Fernet(self.encryption_key)
            decrypted = f.decrypt(encrypted.encode())
            return json.loads(decrypted.decode())
        return None

    def delete_tokens(self):
        """Remove stored tokens"""
        keyring.delete_password(self.service_name, f"{self.user_id}_tokens")
        keyring.delete_password(self.service_name, f"{self.user_id}_key")
```

### Webhook Verification

```python
import hmac
import hashlib

def verify_box_webhook(request_body, signature_header, webhook_secret):
    """Verify Box webhook signature"""
    # Box uses two signatures: primary and secondary
    primary_sig = signature_header.get('BOX-SIGNATURE-PRIMARY')
    secondary_sig = signature_header.get('BOX-SIGNATURE-SECONDARY')

    # Calculate expected signature
    body_bytes = request_body.encode('utf-8') if isinstance(request_body, str) else request_body
    expected_sig = hmac.new(
        webhook_secret.encode('utf-8'),
        body_bytes,
        hashlib.sha256
    ).hexdigest()

    # Verify at least one signature matches
    return expected_sig == primary_sig or expected_sig == secondary_sig
```

## Rate Limiting

Box API has the following rate limits:

- **API Calls:** 1,000 requests per minute per user
- **Uploads:** 240 uploads per minute per user
- **Downloads:** 360 downloads per minute per user
- **Search:** 10 searches per second per user

### Rate Limit Handler

```python
import time
from collections import deque

class BoxRateLimiter:
    def __init__(self):
        self.api_calls = deque(maxlen=1000)
        self.uploads = deque(maxlen=240)
        self.downloads = deque(maxlen=360)

    async def check_rate_limit(self, operation_type='api'):
        """Check and enforce rate limits"""
        now = time.time()

        if operation_type == 'api':
            queue = self.api_calls
            limit = 1000
            window = 60  # 1 minute
        elif operation_type == 'upload':
            queue = self.uploads
            limit = 240
            window = 60
        elif operation_type == 'download':
            queue = self.downloads
            limit = 360
            window = 60
        else:
            return True

        # Remove old entries outside the window
        while queue and queue[0] < now - window:
            queue.popleft()

        # Check if we're at the limit
        if len(queue) >= limit:
            # Calculate wait time
            wait_time = queue[0] + window - now
            if wait_time > 0:
                print(f"Rate limit reached for {operation_type}, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                return await self.check_rate_limit(operation_type)

        # Add current request to queue
        queue.append(now)
        return True
```

## Example Workflows

### Document Processing Pipeline

```python
async def process_documents(client):
    """Example document processing workflow"""

    # 1. Search for documents
    search_results = await client.call_tool(
        server="box",
        tool="search_content",
        arguments={
            "query": "contract pending review",
            "type": "file",
            "content_types": ["pdf", "docx"]
        }
    )

    # 2. Process each document
    for doc in search_results['items']:
        # Download document
        content = await client.call_tool(
            server="box",
            tool="download_file",
            arguments={"file_id": doc['id']}
        )

        # Add metadata
        await client.call_tool(
            server="box",
            tool="add_metadata",
            arguments={
                "file_id": doc['id'],
                "template": "document_review",
                "metadata": {
                    "review_status": "in_progress",
                    "reviewer": "AI Assistant",
                    "review_date": datetime.now().isoformat()
                }
            }
        )

        # Share with reviewers
        await client.call_tool(
            server="box",
            tool="share_file",
            arguments={
                "file_id": doc['id'],
                "access_level": "viewer",
                "emails": ["legal@company.com"],
                "message": "AI-flagged document for review"
            }
        )
```

## Troubleshooting

### Common Issues

**OAuth Flow Interruption:**
```python
# Implement timeout and retry logic
async def authenticate_with_retry(max_attempts=3):
    for attempt in range(max_attempts):
        try:
            await authenticate_interactive()
            return True
        except asyncio.TimeoutError:
            print(f"Authentication timeout, attempt {attempt + 1}/{max_attempts}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return False
```

**Token Refresh Failure:**
```python
# Fallback to re-authentication if refresh fails
try:
    new_tokens = oauth_client.refresh_access_token(refresh_token)
except Exception as e:
    print(f"Token refresh failed: {e}, re-authenticating...")
    await authenticate_interactive()
```

**API Error Handling:**
```python
async def call_box_api_with_retry(endpoint, method='GET', **kwargs):
    """Call Box API with automatic retry on failure"""
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = await make_api_call(endpoint, method, **kwargs)

            if response.status == 429:  # Rate limited
                retry_after = int(response.headers.get('Retry-After', 60))
                await asyncio.sleep(retry_after)
                continue

            if response.status >= 500:  # Server error
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue

            return await response.json()

        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

## Related Resources

- [Box Developer Documentation](https://developer.box.com/)
- [Box OAuth 2.0 Guide](https://developer.box.com/guides/authentication/oauth2/)
- [OAuth 2.1 Specification](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-10)
- [Box API Reference](https://developer.box.com/reference/)
- [Box SDKs](https://github.com/box/box-sdk)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)