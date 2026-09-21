# Vault Plugin

The Vault plugin generates bearer tokens from vault-saved tokens based on OAuth2 configuration protecting a tool or A2A agent.
It receives a dictionary of secrets and use them to dispatch the authorization token to the server based on rules.

The plugin runs on both the **MCP tool** path (`tool_pre_invoke`) and the **A2A agent** path (`agent_pre_invoke`),
so tagging either an MCP server or an A2A agent drives the same secret-injection behavior.

## Features

- **Tag-based metadata handling**: Supports both MCP gateway tags in dict format `{"id": "...", "label": "..."}` and A2A agent tags in plain-string format (`"system:github.com"`).
   - Supported tags must be created on an MCP server or A2A agent to drive the secret handling:
        - system:<system host> where system host is the IDP provider for that MCP Server. For example system:github.com or system:mural.com
        - AUTH_HEADER:<header name> where header name is the authorization header to be used for this MCP header if a PAT token is send

- **Complex token key format**: Supports secrets send via a  header containing a JSON dictionary with keys like `github.com:USER:OAUTH2:TOKEN` or simple `github.com`
- **PAT (Personal Access Token) support**: Use `AUTH_HEADER` tag to specify a custom header to be dispatched to the backend server.
- **OAuth2 token support**: Default bearer token handling for OAuth2 tokens. If no specific rule for PAT the default behavior is to send the secret as Bearer token in Authorization header
- **Flexible configuration**: Falls back to default bearer token behavior when parts are missing

## Configuration

### Basic Configuration

```yaml
vault:
  enabled: true
  config:
    system_tag_prefix: "system"
    vault_header_name: "X-Vault-Tokens"
    vault_handling: "raw"
    system_handling: "tag"
    auth_header_tag_prefix: "AUTH_HEADER"
```

### Configuration Options

- **system_tag_prefix**: Prefix for system identification tags (default: `"system"`)
- **vault_header_name**: HTTP header name for vault tokens (default: `"X-Vault-Tokens"`)
- **vault_handling**: Token handling mode (default: `"raw"`). Future version will handle token unwrapping
- **system_handling**: System identification mode (default: `"tag"`)
- **auth_header_tag_prefix**: Prefix for auth header tags (default: `"AUTH_HEADER"`)

## Token Key Format

The plugin supports complex token keys in the format:

```
system[:scope][:token_type][:token_name]
```

Where:
- **system** (required): The system identifier (e.g., `github.com`, `gitlab.com`)
- **scope** (optional): USER or GROUP (ignored in processing)
- **token_type** (optional): PAT or OAUTH2
- **token_name** (optional): Name of the token

### Examples

1. **Simple key**: `github.com`
   - Uses default OAuth2 bearer token handling

2. **Full PAT key**: `github.com:USER:PAT:my-token`
   - System: `github.com`
   - Scope: `USER` (ignored)
   - Token type: `PAT`
   - Token name: `my-token`
   - Checks for `AUTH_HEADER` tag to determine header name

3. **OAuth2 key**: `gitlab.com:GROUP:OAUTH2:app-token`
   - System: `gitlab.com`
   - Scope: `GROUP` (ignored)
   - Token type: `OAUTH2`
   - Token name: `TOKEN` (default name)
   - Uses OAuth2 bearer token handling

## Destination Binding (`mcpServer`)

Each vault token entry (the value under a token key in the `X-Vault-Tokens` JSON) can be
either of two shapes:

1. **Legacy plain string** — the secret itself, unbound to any destination. Trusted purely
   because the caller's `system:<host>` tag matched:

   ```json
   {"github.com": "ghp_xxxxxxxxxxxx"}
   ```

2. **Object with an optional `mcpServer` binding** — carries `secretValue` (required) and an
   optional `mcpServer` URL. When `mcpServer` is present, the plugin only injects the secret if
   it matches the target's actual registered destination — `Gateway.url` for MCP tools,
   `A2AAgent.endpoint_url` for A2A agents:

   ```json
   {"github.com": {"secretValue": "ghp_xxxxxxxxxxxx", "mcpServer": "https://api.githubcopilot.com/mcp/"}}
   ```

This prevents a token that is scoped to one destination from being replayed against a
different one just because both happen to share the same `system:<host>` tag (e.g. two
gateways both tagged `system:github.com` but pointing at different URLs). If `mcpServer` does
not match, or the real destination can't be determined, the secret is withheld — the
`X-Vault-Tokens` header is still stripped, but no `Authorization`/custom header is injected,
so any pre-existing (unrelated) auth header on the request passes through untouched instead of
being overwritten with a leaked secret.

A `mcpServer` value of `null` (or the key omitted) behaves like the legacy unbound string —
no destination check is performed.

URL comparison is normalized (lowercased scheme/host, trailing slash ignored) so incidental
formatting differences don't cause false mismatches.

## Token Type Handling

### PAT (Personal Access Token)

When `token_type` is `PAT`:
1. Checks if AUTH_HEADER:header tag exists
2. If found, uses the configured custom header
3. If not found, falls back to `Authorization: Bearer <token>`

### OAUTH2

When `token_type` is `OAUTH2` or missing:
- Uses standard `Authorization: Bearer <token>` header

### Unknown Types

For any other token type:
- Logs a warning
- Falls back to `Authorization: Bearer <token>`

## Metadata Tags

The plugin normalizes the two tag shapes that MCP gateways and A2A agents use, so the same
`system:` / `AUTH_HEADER:` tags work for both.

**MCP gateway tags** — dict format (`List[Dict]`):

```json
{
  "tags": [
    {"id": "auto-generated-id", "label": "system:github.com"},
    {"id": "another-id", "label": "AUTH_HEADER:X-GitHub-Token"},
    {"id": "third-id", "label": "environment:production"}
  ]
}
```

The plugin extracts the `label` field from dict tags (the actual tag value), while `id` is autogenerated.

**A2A agent tags** — plain-string format (`List[str]`):

```json
{
  "tags": [
    "system:github.com",
    "AUTH_HEADER:X-GitHub-Token",
    "environment:production"
  ]
}
```

For A2A agents the plugin reads the tags directly as strings. Both shapes resolve to the same
`system:` and `AUTH_HEADER:` semantics described below.

### Tag Types

1. **System Tag**: `system:<system_name>`
   - Identifies which system the token is for
   - Example: `system:github.com`
   - Required for the plugin to work

2. **Auth Header Tag**: `AUTH_HEADER:<header_name>`
   - Specifies custom header for PAT tokens
   - Example: `AUTH_HEADER:X-GitHub-Token`
   - Only used when token type is PAT
   - Optional - falls back to Bearer token if not present

## Example Usage

### Request with Vault Tokens

```http
POST /api/tools/invoke
X-Vault-Tokens: {"github.com:USER:PAT:my-token": "ghp_xxxxxxxxxxxx", "gitlab.com": "glpat-yyyyyyyy"}
```

### Gateway with AUTH_HEADER Tag

If gateway has tags including `AUTH_HEADER:X-GitHub-Token`:
```json
{
  "tags": [
    {"id": "1", "label": "system:github.com"},
    {"id": "2", "label": "AUTH_HEADER:X-GitHub-Token"}
  ]
}
```

The plugin will set:
```http
X-GitHub-Token: ghp_xxxxxxxxxxxx
```

### Without AUTH_HEADER Tag

If no `AUTH_HEADER` tag is defined, the plugin will use default Bearer token:
```http
Authorization: Bearer ghp_xxxxxxxxxxxx
```

## System Identification

The plugin supports two modes for identifying the system:

### TAG Mode (Default)

Extracts system from gateway/agent tags with the configured prefix:
- Tag: `system:github.com` → System: `github.com`

Works for both MCP tools (`tool_pre_invoke`) and A2A agents (`agent_pre_invoke`).

### OAUTH2_CONFIG Mode

Extracts system from the OAuth2 configuration's `token_url`:
- Token URL: `https://github.com/login/oauth/access_token` → System: `github.com`

**Gateway-only.** This mode loads the gateway's OAuth2 config from the database, which does not
exist for A2A agents. On the A2A path (`agent_pre_invoke`), `oauth2_config` is not supported —
the system stays unresolved and the vault header is stripped without injecting a token. Use TAG
mode for A2A agents.

## Hooks

- **tool_pre_invoke**: Processes vault tokens before MCP tool invocation (all modes).
- **agent_pre_invoke**: Processes vault tokens before A2A agent invocation (TAG mode only).


## Testing

## Create a token
export MCPGATEWAY_BEARER_TOKEN = python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes

export CLIENT_ID=xxx
export CLIENT_SECRET=xxx


## Register MCP server with the gateway and add OAuth2 configuration Using UI
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name": "github_com",
           "url": "https://api.githubcopilot.com/mcp/",
           "description": "A new MCP server added with OAuth2 authentication",
           "auth_type": "oauth",
           "auth_value": {
             "client_id": "'$CLIENT_ID'",
             "client_secret": "'$CLIENT_SECRET'",
             "token_url": "https://github.com/login/oauth/access_token",
             "redirect_url": "http://localhost:4444/oauth/callback"
           },
           "tags": ["system:github.com"],
           "passthrough_headers": ["X-Vault-Tokens"]
         }' \
     http://localhost:4444/gateways

## Invocation
When the server is configured invoke the server and send a pass through header of form

    "X-Vault-Tokens": {
        "github.com": "key"
    },

## Sample of Invoking a Tool on the Added Gateway

```bash
# Invoke a tool on the added gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -H 'X-Vault-Tokens: "{\"github.com\": \"key\"}"' \
     -d '{
           "tool_name": "github-com-list-issues",
           "arguments": {
             "repo": "reponame"
           }
         }' \
     http://localhost:4444/tools/invoke
```

## E2E Throwaway Test Harness

`plugins/vault/echo_mcp.py` (SSE MCP server) and `plugins/vault/echo_a2a.py` (FastAPI A2A
agent) are throwaway servers used to exercise both hooks end-to-end without needing a real
upstream like GitHub. Both reflect the headers they receive so the injected `Authorization`
header and the stripped `X-Vault-Tokens` header can be asserted on directly.

`plugins/vault/config_vault_e2e.yaml` registers the plugin on both `tool_pre_invoke` and
`agent_pre_invoke` in one config, so a single gateway run covers both paths.

### Classic MCP server (`tool_pre_invoke`)

```bash
# Start the echo MCP server (port 8001)
nohup uv run python plugins/vault/echo_mcp.py > /tmp/echo_mcp.log 2>&1 &

# Register it as a Gateway, tagged for vault system resolution
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" -H "Content-Type: application/json" \
     -d '{
           "name": "echo_mcp",
           "url": "http://127.0.0.1:8001/sse",
           "tags": ["system:localecho"],
           "passthrough_headers": ["X-Vault-Tokens", "Authorization"]
         }' \
     http://localhost:4444/gateways

# Invoke the whoami tool, which returns the received Authorization header directly
# in its JSON-RPC response (rather than only logging it) — a assertable proof point.
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" -H "Content-Type: application/json" \
     -H 'X-Vault-Tokens: {"localecho": "legacy-plain-secret-123"}' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo-mcp-whoami","arguments":{}}}' \
     http://localhost:4444/rpc
# => structuredContent.authorization == "Bearer legacy-plain-secret-123"
```

For the `mcpServer`-bound shape, set `X-Vault-Tokens` to
`{"localecho": {"secretValue": "...", "mcpServer": "http://127.0.0.1:8001/sse"}}` (matches
`Gateway.url` → injected) or point `mcpServer` at a different URL (mismatch → withheld, no
leak). `/tmp/echo_mcp.log` also shows the same headers via `print()`, for the `echo`/`add`/`hello`
tools that don't return them in the response body.

### A2A agent (`agent_pre_invoke`)

```bash
# Start the echo A2A agent (port 8002)
nohup uv run python plugins/vault/echo_a2a.py > /tmp/echo_a2a.log 2>&1 &

# Register it as an A2A agent
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" -H "Content-Type: application/json" \
     -d '{"agent": {
           "name": "echo-agent",
           "endpoint_url": "http://127.0.0.1:8002/invoke",
           "tags": ["system:localecho"],
           "passthrough_headers": ["X-Vault-Tokens", "Authorization"]
         }}' \
     http://localhost:4444/a2a

# Invoke — echo_a2a.py reflects received_headers directly in its response body
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" -H "Content-Type: application/json" \
     -H 'X-Vault-Tokens: {"localecho": "a2a-legacy-secret-111"}' \
     -d '{"message": "hi"}' \
     http://localhost:4444/a2a/echo-agent/invoke
# => received_headers.authorization == "Bearer a2a-legacy-secret-111"
```

Same `mcpServer` match/mismatch behavior applies, bound against `A2AAgent.endpoint_url`
instead of `Gateway.url`. In all cases `x-vault-tokens` must be absent from
`received_headers`/the server logs — confirming it never reaches the downstream target.
