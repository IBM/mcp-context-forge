# Issue #5402: Manual Testing Guide - Direct Vault Access

## Overview

This guide provides step-by-step manual testing procedures for the VirtualServer UUID vault integration approach. Use this to validate the implementation works correctly before automated tests.

---

## Prerequisites

### 1. Environment Setup

**Required Services**:
- ✅ Context Forge running (staging or local)
- ✅ Vault-proxy running with UUID endpoint implemented
- ✅ Database with virtual servers configured
- ✅ Test user account with vault access

**Environment Variables**:
```bash
# Set these in your shell
export CF_BASE_URL="http://localhost:4444"
export VAULT_PROXY_URL="http://localhost:8080"
export TEST_USER_EMAIL="test@example.com"
export USER_JWT_TOKEN="<get from auth>"
export USER_VAULT_TOKEN="<get from vault login>"
```

### 2. Get User Tokens

**JWT Token**:
```bash
# Login to Context Forge
USER_JWT_TOKEN=$(curl -X POST "$CF_BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "test@example.com",
    "password": "test_password"
  }' | jq -r '.access_token')

echo "JWT Token: $USER_JWT_TOKEN"
```

**Vault Token**:
```bash
# Login to vault
USER_VAULT_TOKEN=$(vault login -method=ldap username=test -format=json | jq -r .auth.client_token)

# Or if using token auth:
USER_VAULT_TOKEN=$(vault login -format=json s.your_token_here | jq -r .auth.client_token)

echo "Vault Token: $USER_VAULT_TOKEN"
```

---

## Test Suite 1: Single-System Virtual Server

### Test 1.1: Create Virtual Server

**Objective**: Create a virtual server with single backend system

**Steps**:
```bash
# 1. Create virtual server
curl -X POST "$CF_BASE_URL/api/v1/admin/virtual-servers" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub Test MCP",
    "description": "Test virtual server for GitHub",
    "backends": [
      {
        "system": "github.com",
        "gateway_id": "gw-github-001",
        "tools": ["list-repos", "create-issue", "get-pr"]
      }
    ]
  }' | tee vs_response.json

# 2. Extract virtual server UUID
VIRTUAL_SERVER_UUID=$(jq -r '.id' vs_response.json)
echo "Virtual Server UUID: $VIRTUAL_SERVER_UUID"
```

**Expected Result**:
```json
{
  "id": "vs-github-abc123",
  "name": "GitHub Test MCP",
  "description": "Test virtual server for GitHub",
  "backends": [
    {
      "system": "github.com",
      "gateway_id": "gw-github-001",
      "tools": ["list-repos", "create-issue", "get-pr"]
    }
  ],
  "created_at": "2026-07-02T10:00:00Z"
}
```

**Validation**:
- ✅ Status code 200 or 201
- ✅ Response contains `id` field (UUID)
- ✅ `backends` array has one entry with `system: "github.com"`

---

### Test 1.2: Store Credential in Vault

**Objective**: Store self-describing credential in vault at UUID path

**Steps**:
```bash
# 1. Create credential JSON
cat > credential.json <<EOF
{
  "secretValue": "ghp_test_token_abc123def456",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}
EOF

# 2. Store in vault at UUID path
vault kv put "secret/users/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID" @credential.json

# 3. Verify credential stored
vault kv get "secret/users/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID"
```

**Expected Result**:
```
====== Data ======
Key            Value
---            -----
authType       PAT
headerName     X-GitHub-Token
secretValue    ghp_test_token_abc123def456
system         github.com
```

**Validation**:
- ✅ Vault command succeeds
- ✅ All 4 fields stored correctly
- ✅ Can retrieve credential with `kv get` command

---

### Test 1.3: Test Vault-Proxy API Directly

**Objective**: Verify vault-proxy UUID endpoint returns credential

**Steps**:
```bash
# 1. Call vault-proxy API directly
curl -X GET "$VAULT_PROXY_URL/api/secret/v1/by-uuid/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  | jq .

# 2. Save response for comparison
curl -X GET "$VAULT_PROXY_URL/api/secret/v1/by-uuid/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  > vault_proxy_response.json
```

**Expected Result**:
```json
{
  "secretValue": "ghp_test_token_abc123def456",
  "authType": "PAT",
  "headerName": "X-GitHub-Token",
  "system": "github.com"
}
```

**Validation**:
- ✅ Status code 200
- ✅ Response is JSON object (not array)
- ✅ Contains all 4 required fields
- ✅ `system` field matches backend system

---

### Test 1.4: Invoke Tool via Context Forge

**Objective**: End-to-end test of vault_direct plugin

**Steps**:
```bash
# 1. Invoke tool via CF
curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {
      "org": "test-org"
    }
  }' | tee tool_response.json
```

**Expected Result**:
```json
{
  "result": {
    "repositories": [
      {"name": "repo1", "url": "https://github.com/test-org/repo1"},
      {"name": "repo2", "url": "https://github.com/test-org/repo2"}
    ]
  },
  "status": "success"
}
```

**Validation**:
- ✅ Status code 200
- ✅ Tool execution successful
- ✅ Backend received authenticated request

---

### Test 1.5: Verify Backend Received Correct Auth Header

**Objective**: Confirm auth header injected correctly

**Steps**:
```bash
# 1. Check CF logs for vault_direct plugin activity
kubectl logs -f context-forge-pod | grep "vault_direct"

# Expected log entries:
# [INFO] vault_direct: Resolving credential for vs-github-abc123, user test@example.com
# [INFO] vault_direct: Credential resolved successfully, auth_type=PAT, system=github.com
# [DEBUG] vault_direct: Injected auth header X-GitHub-Token

# 2. Check backend MCP server logs
kubectl logs -f github-mcp-server-pod | grep "X-GitHub-Token"

# Expected: Backend received request with X-GitHub-Token header
```

**Validation**:
- ✅ CF logs show credential resolution
- ✅ CF logs show auth header injection
- ✅ Backend logs show X-GitHub-Token header received
- ✅ Header value matches credential secret (check backend logs, not CF logs)

---

## Test Suite 2: Multi-System Virtual Server

### Test 2.1: Create Multi-System Virtual Server

**Objective**: Create virtual server with multiple backend systems

**Steps**:
```bash
# 1. Create multi-system virtual server
curl -X POST "$CF_BASE_URL/api/v1/admin/virtual-servers" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Developer Tools Suite",
    "description": "Aggregated access to GitHub, Jira, and Slack",
    "backends": [
      {
        "system": "github.com",
        "gateway_id": "gw-github-001",
        "tools": ["list-repos", "create-issue"]
      },
      {
        "system": "jira.atlassian.com",
        "gateway_id": "gw-jira-001",
        "tools": ["list-issues", "create-ticket"]
      },
      {
        "system": "slack.com",
        "gateway_id": "gw-slack-001",
        "tools": ["send-message", "list-channels"]
      }
    ]
  }' | tee multi_vs_response.json

# 2. Extract UUID
MULTI_VS_UUID=$(jq -r '.id' multi_vs_response.json)
echo "Multi-System Virtual Server UUID: $MULTI_VS_UUID"
```

**Expected Result**:
```json
{
  "id": "vs-dev-tools-xyz789",
  "name": "Developer Tools Suite",
  "backends": [
    {"system": "github.com", "gateway_id": "gw-github-001", "tools": [...]},
    {"system": "jira.atlassian.com", "gateway_id": "gw-jira-001", "tools": [...]},
    {"system": "slack.com", "gateway_id": "gw-slack-001", "tools": [...]}
  ]
}
```

**Validation**:
- ✅ Status code 200 or 201
- ✅ `backends` array has 3 entries
- ✅ Each backend has unique `system` field

---

### Test 2.2: Store Multi-System Credentials in Vault

**Objective**: Store array of credentials for multi-system virtual server

**Steps**:
```bash
# 1. Create credentials array JSON
cat > multi_credentials.json <<EOF
[
  {
    "secretValue": "ghp_github_token_xyz",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  },
  {
    "secretValue": "xoxb-slack-token-abc",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
EOF

# 2. Store in vault
vault kv put "secret/users/$TEST_USER_EMAIL/$MULTI_VS_UUID" @multi_credentials.json

# 3. Verify stored as array
vault kv get -format=json "secret/users/$TEST_USER_EMAIL/$MULTI_VS_UUID" | jq .
```

**Expected Result**:
```json
{
  "data": [
    {
      "secretValue": "ghp_github_token_xyz",
      "authType": "PAT",
      "headerName": "X-GitHub-Token",
      "system": "github.com"
    },
    {
      "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
      "authType": "BASIC",
      "headerName": "Authorization",
      "system": "jira.atlassian.com"
    },
    {
      "secretValue": "xoxb-slack-token-abc",
      "authType": "OAUTH2",
      "headerName": "Authorization",
      "system": "slack.com"
    }
  ]
}
```

**Validation**:
- ✅ Vault stores array (not single object)
- ✅ Array has 3 elements
- ✅ Each element has all 4 required fields

---

### Test 2.3: Test Vault-Proxy Returns Array

**Objective**: Verify vault-proxy returns array for multi-system credentials

**Steps**:
```bash
# 1. Call vault-proxy API
curl -X GET "$VAULT_PROXY_URL/api/secret/v1/by-uuid/$TEST_USER_EMAIL/$MULTI_VS_UUID" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  | jq . | tee vault_proxy_multi_response.json

# 2. Verify it's an array
jq 'type' vault_proxy_multi_response.json
# Should output: "array"

# 3. Count elements
jq 'length' vault_proxy_multi_response.json
# Should output: 3
```

**Expected Result**:
```json
[
  {
    "secretValue": "ghp_github_token_xyz",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  },
  {
    "secretValue": "xoxb-slack-token-abc",
    "authType": "OAUTH2",
    "headerName": "Authorization",
    "system": "slack.com"
  }
]
```

**Validation**:
- ✅ Status code 200
- ✅ Response type is array
- ✅ Array length is 3
- ✅ Each element has unique `system` field

---

### Test 2.4: Invoke GitHub Tool

**Objective**: Verify correct credential selected for GitHub tool

**Steps**:
```bash
# 1. Invoke GitHub tool
curl -X POST "$CF_BASE_URL/servers/$MULTI_VS_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {
      "org": "test-org"
    }
  }' | jq .

# 2. Check CF logs
kubectl logs -f context-forge-pod | grep "vault_direct" | grep "github.com"

# Expected:
# [INFO] vault_direct: Determined tool "list-repos" → backend.system = "github.com"
# [INFO] vault_direct: Selected credential for system "github.com"
# [DEBUG] vault_direct: Injected auth header X-GitHub-Token
```

**Validation**:
- ✅ Tool executed successfully
- ✅ CF logs show system determination: "github.com"
- ✅ CF logs show credential selection for github.com
- ✅ CF logs show X-GitHub-Token injection (not Authorization)

---

### Test 2.5: Invoke Jira Tool

**Objective**: Verify correct credential selected for Jira tool

**Steps**:
```bash
# 1. Invoke Jira tool
curl -X POST "$CF_BASE_URL/servers/$MULTI_VS_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-issues",
    "arguments": {
      "project": "TEST"
    }
  }' | jq .

# 2. Check CF logs
kubectl logs -f context-forge-pod | grep "vault_direct" | grep "jira"

# Expected:
# [INFO] vault_direct: Determined tool "list-issues" → backend.system = "jira.atlassian.com"
# [INFO] vault_direct: Selected credential for system "jira.atlassian.com"
# [DEBUG] vault_direct: Injected auth header Authorization with scheme Basic
```

**Validation**:
- ✅ Tool executed successfully
- ✅ CF logs show system determination: "jira.atlassian.com"
- ✅ CF logs show credential selection for jira.atlassian.com
- ✅ CF logs show Authorization: Basic injection (not X-GitHub-Token)

---

### Test 2.6: Invoke Slack Tool

**Objective**: Verify correct credential selected for Slack tool

**Steps**:
```bash
# 1. Invoke Slack tool
curl -X POST "$CF_BASE_URL/servers/$MULTI_VS_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "send-message",
    "arguments": {
      "channel": "#test",
      "message": "Test message"
    }
  }' | jq .

# 2. Check CF logs
kubectl logs -f context-forge-pod | grep "vault_direct" | grep "slack"

# Expected:
# [INFO] vault_direct: Determined tool "send-message" → backend.system = "slack.com"
# [INFO] vault_direct: Selected credential for system "slack.com"
# [DEBUG] vault_direct: Injected auth header Authorization with scheme Bearer
```

**Validation**:
- ✅ Tool executed successfully
- ✅ CF logs show system determination: "slack.com"
- ✅ CF logs show credential selection for slack.com
- ✅ CF logs show Authorization: Bearer injection (OAuth2)

---

## Test Suite 3: Error Handling

### Test 3.1: Missing Credential

**Objective**: Verify graceful error when credential not found

**Steps**:
```bash
# 1. Create virtual server WITHOUT storing credential
curl -X POST "$CF_BASE_URL/api/v1/admin/virtual-servers" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "No Credential Test",
    "backends": [
      {"system": "gitlab.com", "gateway_id": "gw-gitlab-001", "tools": ["list-projects"]}
    ]
  }' | tee no_cred_vs_response.json

NO_CRED_VS_UUID=$(jq -r '.id' no_cred_vs_response.json)

# 2. Try to invoke tool without credential
curl -X POST "$CF_BASE_URL/servers/$NO_CRED_VS_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-projects",
    "arguments": {}
  }' | jq .
```

**Expected Result**:
```json
{
  "error": "Credentials not configured",
  "code": "VAULT_CREDENTIALS_NOT_FOUND",
  "message": "No credentials found for virtual server 'No Credential Test'. Please configure credentials in vault-proxy.",
  "virtual_server_uuid": "vs-gitlab-xyz123",
  "status": 404
}
```

**Validation**:
- ✅ Status code 404
- ✅ Error message is generic (doesn't reveal system)
- ✅ Includes virtual server name for user clarity
- ✅ CF logs show detailed error (user, UUID, system) internally

---

### Test 3.2: Invalid Vault Token

**Objective**: Verify error when vault token is invalid

**Steps**:
```bash
# 1. Try with invalid vault token
curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: invalid_token_12345" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {"org": "test-org"}
  }' | jq .
```

**Expected Result**:
```json
{
  "error": "Vault authentication required",
  "code": "VAULT_AUTH_REQUIRED",
  "message": "Invalid vault token. Please re-authenticate.",
  "status": 401
}
```

**Validation**:
- ✅ Status code 401
- ✅ Error message indicates auth issue
- ✅ Doesn't reveal whether credential exists

---

### Test 3.3: Missing X-Vault-Token Header

**Objective**: Verify error when header missing

**Steps**:
```bash
# 1. Try without X-Vault-Token header
curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {"org": "test-org"}
  }' | jq .
```

**Expected Result**:
```json
{
  "error": "Vault authentication required",
  "code": "VAULT_AUTH_REQUIRED",
  "message": "Ensure X-Vault-Token header and valid JWT are present.",
  "status": 401
}
```

**Validation**:
- ✅ Status code 401
- ✅ Clear error message about missing header

---

### Test 3.4: Missing Credential for System (Multi-System)

**Objective**: Verify error when multi-system virtual server missing credential for one system

**Steps**:
```bash
# 1. Create multi-system credentials with only 2 systems (missing Slack)
cat > incomplete_credentials.json <<EOF
[
  {
    "secretValue": "ghp_github_token_xyz",
    "authType": "PAT",
    "headerName": "X-GitHub-Token",
    "system": "github.com"
  },
  {
    "secretValue": "dXNlcjpqaXJhX3Rva2VuCg==",
    "authType": "BASIC",
    "headerName": "Authorization",
    "system": "jira.atlassian.com"
  }
]
EOF

vault kv put "secret/users/$TEST_USER_EMAIL/$MULTI_VS_UUID" @incomplete_credentials.json

# 2. Try to invoke Slack tool (missing credential)
curl -X POST "$CF_BASE_URL/servers/$MULTI_VS_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "send-message",
    "arguments": {
      "channel": "#test",
      "message": "Test"
    }
  }' | jq .
```

**Expected Result**:
```json
{
  "error": "Missing system credential",
  "code": "VAULT_SYSTEM_CREDENTIAL_NOT_FOUND",
  "message": "No credential found for system 'slack.com' in virtual server 'Developer Tools Suite'",
  "virtual_server_uuid": "vs-dev-tools-xyz789",
  "required_system": "slack.com",
  "available_systems": ["github.com", "jira.atlassian.com"],
  "status": 404
}
```

**Validation**:
- ✅ Status code 404
- ✅ Error clearly states missing system
- ✅ Shows available systems (helps user know what to create)
- ✅ Includes virtual server UUID for reference

---

### Test 3.5: Rate Limiting

**Objective**: Verify rate limiting kicks in after threshold

**Steps**:
```bash
# 1. Make 21 requests quickly (rate limit is 20/min)
for i in {1..21}; do
  echo "Request $i"
  curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
    -H "Authorization: Bearer $USER_JWT_TOKEN" \
    -H "X-Vault-Token: $USER_VAULT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "tool_name": "list-repos",
      "arguments": {"org": "test-org"}
    }' \
    -w "\nStatus: %{http_code}\n" \
    -o /dev/null \
    -s &
done
wait

# 2. Check for 429 response
# Last request should get 429 Too Many Requests
```

**Expected Result** (on 21st request):
```json
{
  "error": "Rate limit exceeded",
  "code": "RATE_LIMIT_EXCEEDED",
  "message": "Too many credential requests. Please try again later.",
  "retry_after": 45,
  "status": 429
}
```

**Validation**:
- ✅ First 20 requests succeed (200)
- ✅ 21st request returns 429
- ✅ Response includes `retry_after` header
- ✅ CF logs show rate limit violation

---

## Test Suite 4: Auth Type Variations

### Test 4.1: PAT (Personal Access Token)

**Already tested in Test 1.4** ✅

**Verify**:
- Header: `X-GitHub-Token: ghp_token_value` (no prefix)

---

### Test 4.2: OAUTH2

**Steps**:
```bash
# 1. Store OAuth2 credential
cat > oauth2_credential.json <<EOF
{
  "secretValue": "ya29.oauth2_access_token",
  "authType": "OAUTH2",
  "headerName": "Authorization",
  "system": "google.com"
}
EOF

vault kv put "secret/users/$TEST_USER_EMAIL/vs-google-test-001" @oauth2_credential.json

# 2. Invoke tool
# (assuming you have a Google virtual server)
curl -X POST "$CF_BASE_URL/servers/vs-google-test-001/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-files",
    "arguments": {}
  }'

# 3. Check backend logs for auth header
# Expected: Authorization: Bearer ya29.oauth2_access_token
```

**Validation**:
- ✅ Header: `Authorization: Bearer ya29.oauth2_access_token`

---

### Test 4.3: JWT

**Steps**:
```bash
# 1. Store JWT credential
cat > jwt_credential.json <<EOF
{
  "secretValue": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
  "authType": "JWT",
  "headerName": "Authorization",
  "system": "api.example.com"
}
EOF

vault kv put "secret/users/$TEST_USER_EMAIL/vs-jwt-test-001" @jwt_credential.json

# 2. Invoke tool
curl -X POST "$CF_BASE_URL/servers/vs-jwt-test-001/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "test-endpoint",
    "arguments": {}
  }'

# 3. Check backend logs
# Expected: Authorization: Bearer eyJhbGc...
```

**Validation**:
- ✅ Header: `Authorization: Bearer eyJhbGc...`

---

### Test 4.4: BASIC

**Already tested in Test 2.5** (Jira credential) ✅

**Verify**:
- Header: `Authorization: Basic dXNlcjpqaXJhX3Rva2VuCg==`

---

### Test 4.5: APIKEY

**Steps**:
```bash
# 1. Store API Key credential
cat > apikey_credential.json <<EOF
{
  "secretValue": "sk-api-key-xyz789",
  "authType": "APIKEY",
  "headerName": "X-API-Key",
  "system": "openai.com"
}
EOF

vault kv put "secret/users/$TEST_USER_EMAIL/vs-openai-test-001" @apikey_credential.json

# 2. Invoke tool
curl -X POST "$CF_BASE_URL/servers/vs-openai-test-001/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "chat-completion",
    "arguments": {
      "prompt": "Hello"
    }
  }'

# 3. Check backend logs
# Expected: X-API-Key: sk-api-key-xyz789
```

**Validation**:
- ✅ Header: `X-API-Key: sk-api-key-xyz789` (no prefix)

---

### Test 4.6: CUSTOM

**Steps**:
```bash
# 1. Store custom credential with metadata
cat > custom_credential.json <<EOF
{
  "secretValue": "custom_token_value",
  "authType": "CUSTOM",
  "headerName": "X-Custom-Auth",
  "system": "custom-api.com",
  "metadata": {
    "tokenType": "Token"
  }
}
EOF

vault kv put "secret/users/$TEST_USER_EMAIL/vs-custom-test-001" @custom_credential.json

# 2. Invoke tool
curl -X POST "$CF_BASE_URL/servers/vs-custom-test-001/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "custom-endpoint",
    "arguments": {}
  }'

# 3. Check backend logs
# Expected: X-Custom-Auth: Token custom_token_value
```

**Validation**:
- ✅ Header: `X-Custom-Auth: Token custom_token_value`
- ✅ Custom token type from metadata used

---

## Test Suite 5: Security & Audit

### Test 5.1: Verify Secrets Not in Logs

**Objective**: Ensure secret values never appear in CF logs

**Steps**:
```bash
# 1. Invoke tool with known secret
curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {"org": "test-org"}
  }'

# 2. Search CF logs for secret value
kubectl logs context-forge-pod | grep "ghp_test_token_abc123def456"
# Should return NOTHING

# 3. Search for vault token
kubectl logs context-forge-pod | grep "$USER_VAULT_TOKEN"
# Should return NOTHING (X-Vault-Token header should be masked)
```

**Validation**:
- ✅ Secret values NOT in logs
- ✅ Vault tokens NOT in logs
- ✅ Only metadata logged (auth_type, system, header_name)

---

### Test 5.2: Verify Audit Trail

**Objective**: Confirm all credential access is logged

**Steps**:
```bash
# 1. Invoke tool
curl -X POST "$CF_BASE_URL/servers/$VIRTUAL_SERVER_UUID/mcp" \
  -H "Authorization: Bearer $USER_JWT_TOKEN" \
  -H "X-Vault-Token: $USER_VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "list-repos",
    "arguments": {"org": "test-org"}
  }'

# 2. Check audit logs
kubectl logs context-forge-pod | grep "vault_direct" | grep "resolution attempt"

# Expected log entry:
# [INFO] vault_direct: Vault credential resolution attempt
#   user: test@example.com
#   virtual_server_uuid: vs-github-abc123
#   virtual_server_name: GitHub Test MCP
#   tool_name: list-repos
#   timestamp: 2026-07-02T10:15:00.123Z

# 3. Check success log
kubectl logs context-forge-pod | grep "vault_direct" | grep "resolved successfully"

# Expected:
# [INFO] vault_direct: Vault credentials resolved successfully
#   user: test@example.com
#   virtual_server_uuid: vs-github-abc123
#   credential_count: 1
#   systems: ["github.com"]
```

**Validation**:
- ✅ Attempt logged before vault call
- ✅ Success/failure logged after vault call
- ✅ Log includes: user, UUID, tool name, timestamp
- ✅ Log includes metadata (count, systems) but NOT secret values

---

## Test Results Summary

### Manual Test Checklist

```
Test Suite 1: Single-System Virtual Server
[ ] 1.1: Create virtual server
[ ] 1.2: Store credential in vault
[ ] 1.3: Test vault-proxy API directly
[ ] 1.4: Invoke tool via Context Forge
[ ] 1.5: Verify backend received correct auth header

Test Suite 2: Multi-System Virtual Server
[ ] 2.1: Create multi-system virtual server
[ ] 2.2: Store multi-system credentials in vault
[ ] 2.3: Test vault-proxy returns array
[ ] 2.4: Invoke GitHub tool (system selection)
[ ] 2.5: Invoke Jira tool (system selection)
[ ] 2.6: Invoke Slack tool (system selection)

Test Suite 3: Error Handling
[ ] 3.1: Missing credential
[ ] 3.2: Invalid vault token
[ ] 3.3: Missing X-Vault-Token header
[ ] 3.4: Missing credential for system (multi-system)
[ ] 3.5: Rate limiting

Test Suite 4: Auth Type Variations
[ ] 4.1: PAT
[ ] 4.2: OAUTH2
[ ] 4.3: JWT
[ ] 4.4: BASIC
[ ] 4.5: APIKEY
[ ] 4.6: CUSTOM

Test Suite 5: Security & Audit
[ ] 5.1: Verify secrets not in logs
[ ] 5.2: Verify audit trail
```

---

## Troubleshooting

### Issue: "Credentials not found"

**Possible causes**:
1. Credential not stored at correct path
2. User email mismatch
3. Virtual server UUID mismatch

**Debug**:
```bash
# 1. Check vault path
vault kv list "secret/users/$TEST_USER_EMAIL/"

# 2. Verify credential exists
vault kv get "secret/users/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID"

# 3. Check user email in JWT
echo "$USER_JWT_TOKEN" | jwt decode -

# 4. Check virtual server UUID
curl "$CF_BASE_URL/api/v1/admin/virtual-servers/$VIRTUAL_SERVER_UUID" \
  -H "Authorization: Bearer $USER_JWT_TOKEN"
```

### Issue: "Invalid vault token"

**Possible causes**:
1. Vault token expired
2. Vault token revoked
3. Wrong vault token format

**Debug**:
```bash
# 1. Validate vault token
vault token lookup $USER_VAULT_TOKEN

# 2. Check expiration
vault token lookup -format=json $USER_VAULT_TOKEN | jq '.data.expire_time'

# 3. Get new token
USER_VAULT_TOKEN=$(vault login -method=ldap username=test -format=json | jq -r .auth.client_token)
```

### Issue: Backend not receiving auth header

**Possible causes**:
1. Plugin not invoked (check routing)
2. Wrong system field in credential
3. Backend gateway misconfigured

**Debug**:
```bash
# 1. Check plugin routing
kubectl logs context-forge-pod | grep "plugin_router"
# Should show "vault_direct" selected

# 2. Check credential system field
vault kv get -format=json "secret/users/$TEST_USER_EMAIL/$VIRTUAL_SERVER_UUID" | jq '.data.system'

# 3. Check backend gateway configuration
curl "$CF_BASE_URL/api/v1/admin/gateways/$GATEWAY_ID" \
  -H "Authorization: Bearer $USER_JWT_TOKEN"
```

---

## Next Steps

After manual testing passes:

1. **Automated Tests**: Implement unit and integration tests
2. **Performance Testing**: Load test with k6 or similar
3. **Security Review**: Complete security review checklist
4. **Documentation**: Update user-facing docs
5. **Staging Deployment**: Deploy to staging environment
6. **Production Rollout**: Follow migration guide for gradual rollout

---

## Related Documents

- **ISSUE_5402_FINAL_DESIGN_V2.md** - Complete technical design
- **ISSUE_5402_IMPLEMENTATION_GUIDE.md** - Files to create/update
- **ISSUE_5402_MIGRATION_GUIDE.md** - Production migration steps
- **ISSUE_5402_SUMMARY_V2.md** - Executive summary

---

**Last Updated**: 2026-07-02  
**Status**: Ready for manual testing  
**Tested By**: _____________  
**Date**: _____________
