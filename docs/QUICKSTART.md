# 5-Minute Setup & First Steps

Get **ContextForge** up and running in under 5 minutes.

## 1. Quick Start with uvx

Use `uvx` to run the gateway instantly without manual installation.

### Bash / Zsh

```bash
BASIC_AUTH_PASSWORD=pass \
JWT_SECRET_KEY=my-test-key \
MCPGATEWAY_UI_ENABLED=true \
MCPGATEWAY_ADMIN_API_ENABLED=true \
PLATFORM_ADMIN_EMAIL=admin@example.com \
PLATFORM_ADMIN_PASSWORD=changeme \
PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
```

### Windows (PowerShell)

```powershell
$Env:BASIC_AUTH_PASSWORD="pass"
$Env:JWT_SECRET_KEY="my-test-key"
$Env:MCPGATEWAY_UI_ENABLED="true"
$Env:MCPGATEWAY_ADMIN_API_ENABLED="true"
$Env:PLATFORM_ADMIN_EMAIL="admin@example.com"
$Env:PLATFORM_ADMIN_PASSWORD="changeme"
$Env:PLATFORM_ADMIN_FULL_NAME="Platform Administrator"

uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
```

---

## 2. Your First API Call

Generate a token and query the version endpoint.

### API Call - Bash / Zsh

```bash
# Generate token
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

# Query endpoint
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/version | jq
```

### API Call - Windows (PowerShell)

```powershell
# Generate token (must match JWT_SECRET_KEY used by the gateway)
$token = python -m mcpgateway.utils.create_jwt_token `
  --username "admin@example.com" `
  --exp 10080 `
  --secret "my-test-key"

$headers = @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Uri "http://127.0.0.1:4444/version" -Headers $headers | ConvertTo-Json
```

---

## 3. Local Development

> **Note:** There is no root-level `requirements.txt`. This project uses `pyproject.toml`, `uv`, and `Makefile`.

To set up your local development environment:

```bash
# Install dependencies with uv
uv sync

# Or using Make
make install
```
