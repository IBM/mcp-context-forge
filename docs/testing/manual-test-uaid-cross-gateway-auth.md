# Manual Testing Plan: UAID Cross-Gateway Authentication (PR #4342)

This document provides step-by-step manual testing procedures for validating the UAID cross-gateway authentication and fail-closed domain allowlist features introduced in PR #4342.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Test Setup](#test-setup)
  - [Gateway A Configuration](#gateway-a-configuration)
  - [Gateway B Configuration](#gateway-b-configuration)
- [Test Scenarios](#test-scenarios)
  - [Test 1: Startup Validation (Fail-Closed Warning)](#test-1-startup-validation-fail-closed-warning)
  - [Test 2: Startup Validation (Strict Mode)](#test-2-startup-validation-strict-mode-fail-fast)
  - [Test 3: Generate JWT Tokens](#test-3-generate-jwt-tokens)
  - [Test 4: Register Agent on Gateway B](#test-4-register-agent-on-gateway-b-target)
  - [Test 5: Cross-Gateway Invocation WITH Bearer Token](#test-5-cross-gateway-invocation-with-bearer-token-success)
  - [Test 6: Cross-Gateway WITHOUT Token](#test-6-cross-gateway-without-token-auth-required)
  - [Test 7: Fail-Closed Allowlist (Blocked Domain)](#test-7-fail-closed-allowlist-blocked-domain)
  - [Test 8: UAID_ALLOW_ALL_DOMAINS Bypass](#test-8-uaid_allow_all_domains-bypass-development-mode)
  - [Test 9: Subdomain Matching](#test-9-subdomain-matching)
  - [Test 10: IPv6 Domain Handling](#test-10-ipv6-domain-handling)
  - [Test 11: Invalid Domain Configuration](#test-11-invalid-domain-configuration)
  - [Test 12: Audit Trail Headers](#test-12-audit-trail-headers)
  - [Test 13: Token Expiration Handling](#test-13-token-expiration-handling)
  - [Test 14: JWT Trust Mismatch](#test-14-jwt-trust-mismatch)
  - [Test 15: UAID_FORWARD_AUTH Disabled](#test-15-uaid_forward_auth-disabled)
- [Test Summary Checklist](#test-summary-checklist)
- [Cleanup](#cleanup)
- [Expected Results Summary](#expected-results-summary)

---

## Prerequisites

```bash
# 1. Checkout the PR branch
git fetch origin pull/4342/head:pr-4342
git checkout pr-4342

# 2. Install dependencies
make install-dev

# 3. Ensure Redis is running
redis-cli ping  # Should return PONG

# 4. Set up two gateway instances for cross-gateway testing
# We'll use different ports: 4444 (Gateway A) and 4445 (Gateway B)
```

---

## Test Setup

### Gateway A Configuration

Create `.env.test-a` with the following settings:

```bash
# Copy base config
cp .env.example .env.test-a
```

Edit `.env.test-a`:

```bash
# Server
HOST=127.0.0.1
PORT=4444
DATABASE_URL=sqlite:///./mcp-test-a.db
REDIS_URL=redis://localhost:6379/1

# Auth
JWT_SECRET_KEY=shared-test-secret-12345
AUTH_REQUIRED=true
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=testpass

# A2A and UAID Security
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=["localhost:4444", "127.0.0.1:4444", "localhost:4445", "127.0.0.1:4445", "localhost:9100", "127.0.0.1:9100"]
UAID_ALLOW_ALL_DOMAINS=false
UAID_FORWARD_AUTH=true

# Enable for testing startup validation
# UAID_REQUIRE_ALLOWLIST_ON_STARTUP=false

# Features
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true

# Logging
LOG_LEVEL=INFO
```

### Gateway B Configuration

Create `.env.test-b` with the following settings:

```bash
# Copy base config
cp .env.example .env.test-b
```

Edit `.env.test-b`:

```bash
# Server
HOST=127.0.0.1
PORT=4445
DATABASE_URL=sqlite:///./mcp-test-b.db
REDIS_URL=redis://localhost:6379/2

# Auth (SAME secret as Gateway A for trust)
JWT_SECRET_KEY=shared-test-secret-12345
AUTH_REQUIRED=true
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=testpass

# A2A and UAID Security
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=["localhost:4444", "127.0.0.1:4444", "localhost:4445", "127.0.0.1:4445", "localhost:9100", "127.0.0.1:9100"]
UAID_ALLOW_ALL_DOMAINS=false
UAID_FORWARD_AUTH=true

# Features
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true

# Logging
LOG_LEVEL=INFO
```

---

## Test Scenarios

### Cross-Gateway Routing Architecture

**Important Changes in This PR:**

1. **New `/a2a/invoke` Endpoint**: Accepts `agent_id` in request body instead of URL path to support UAIDs containing forward slashes
2. **UAID nativeId Override**: New `uaid_native_id_override` field separates routing address from invocation address
3. **Protocol Stripping**: UAID generation automatically strips `http://`/`https://` from nativeId for SSRF protection
4. **Localhost HTTP**: Cross-gateway routing uses HTTP for localhost/127.0.0.1 endpoints (development), HTTPS for others

**Test Architecture:**
```
Gateway A (port 4444)
  ↓ routes to nativeId=127.0.0.1:4445
Gateway B (port 4445)
  ↓ invokes endpoint_url=localhost:9100
Echo Agent (port 9100)
```

**UAID Format:**
```
uaid:aid:{hash};uid=0;registry=context-forge;proto=a2a;nativeId=127.0.0.1:4445
```
- `nativeId`: Where Gateway A routes to (Gateway B)
- `endpoint_url` (stored in agent record): Where Gateway B invokes (Echo Agent)

---

### Test 1: Startup Validation (Fail-Closed Warning)

**Purpose:** Verify ERROR logging when allowlist is empty

**Steps:**

```bash
# Terminal 1: Create config with empty allowlist
cat > .env.test-empty <<EOF
HOST=127.0.0.1
PORT=4444
DATABASE_URL=sqlite:///./mcp-test-empty.db
JWT_SECRET_KEY=test-secret
AUTH_REQUIRED=true
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=[]
UAID_ALLOW_ALL_DOMAINS=false
EOF

# Start with empty allowlist
ENV_FILE=.env.test-empty make dev
```

**Expected Output:**

```
🚨 SECURITY: UAID cross-gateway routing is DISABLED.
Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production).
Cross-gateway UAID calls will fail until allowlist is configured.
```

**Verification Checklist:**

- [ ] ERROR log appears at startup
- [ ] Gateway still starts (non-blocking by default)
- [ ] Message includes configuration guidance

**Cleanup:**

```bash
# Stop Gateway A
# Ctrl+C
```

---

### Test 2: Startup Validation (Strict Mode - Fail Fast)

**Purpose:** Verify gateway aborts when `UAID_REQUIRE_ALLOWLIST_ON_STARTUP=true`

**Steps:**

```bash
# Add strict mode to config
cat > .env.test-strict <<EOF
HOST=127.0.0.1
PORT=4444
DATABASE_URL=sqlite:///./mcp-test-strict.db
JWT_SECRET_KEY=test-secret
AUTH_REQUIRED=true
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=[]
UAID_ALLOW_ALL_DOMAINS=false
UAID_REQUIRE_ALLOWLIST_ON_STARTUP=true
EOF

# Try to start - should FAIL
ENV_FILE=.env.test-strict make dev
```

**Expected Output:**

```
RuntimeError: 🚨 SECURITY: UAID cross-gateway routing is DISABLED...
Gateway startup aborted due to UAID_REQUIRE_ALLOWLIST_ON_STARTUP=true.
```

**Verification Checklist:**

- [ ] Gateway startup FAILS (exits with error)
- [ ] Error message mentions `UAID_REQUIRE_ALLOWLIST_ON_STARTUP`
- [ ] Provides configuration fix guidance

---

### Test 3: Generate JWT Tokens

**Purpose:** Create valid tokens for authenticated testing

**Steps:**

```bash
# Start Gateway A with proper config
ENV_FILE=.env.test-a make dev

# In another terminal, generate tokens
export JWT_SECRET=shared-test-secret-12345

# Token for admin user (valid for 120 minutes)
TOKEN_ADMIN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 120 \
  --secret $JWT_SECRET)

echo "Admin Token: Bearer $TOKEN_ADMIN"

# Token for regular user
TOKEN_USER=$(python -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --exp 120 \
  --secret $JWT_SECRET)

echo "User Token: Bearer $TOKEN_USER"

# Save for later use
export AUTH_ADMIN="Authorization: Bearer $TOKEN_ADMIN"
export AUTH_USER="Authorization: Bearer $TOKEN_USER"
```

**Verification Checklist:**

- [ ] Tokens generated successfully
- [ ] Environment variables exported
- [ ] Tokens contain correct username claims

---

### Test 4: Register Agent on Gateway B (Target)

**Purpose:** Create an agent that will be invoked via cross-gateway routing

**Prerequisites:**
- Start echo agent: `cd a2a-agents/go/a2a-echo-agent && go run main.go -port 9100`
- Echo agent will be running on port 9100

**Steps:**

```bash
# Start Gateway B in another terminal
ENV_FILE=.env.test-b make dev

# Register an A2A agent on Gateway B with cross-gateway routing support
# Uses uaid_native_id_override to separate routing address (Gateway B) from invocation address (echo agent)
curl -X POST http://localhost:4445/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "test-agent-echo",
      "description": "Echo agent with cross-gateway routing",
      "endpoint_url": "http://localhost:9100",
      "uaid_native_id_override": "http://127.0.0.1:4445",
      "capabilities": {"search": true, "query": true},
      "enabled": true,
      "generate_uaid": true,
      "uaid_registry": "context-forge"
    },
    "visibility": "public"
  }' | jq
```

**Expected Response:**

```json
{
  "id": "<uuid>",
  "name": "test-agent-echo",
  "uaid": "uaid:aid:...;nativeId=127.0.0.1:4445",
  "uaidNativeId": "http://127.0.0.1:4445",
  "endpointUrl": "http://localhost:9100",
  ...
}
```

**Save UAID for later tests:**

```bash
# Extract and export UAID
export UAID_AGENT_B=$(curl -s -H "$AUTH_ADMIN" http://localhost:4445/a2a | jq -r '.[] | select(.name == "test-agent-echo") | .uaid')
echo "UAID: $UAID_AGENT_B"
```

**Verification Checklist:**

- [ ] Echo agent running on port 9100
- [ ] Agent registered successfully on Gateway B
- [ ] UAID generated with `nativeId=127.0.0.1:4445` (Gateway B's address)
- [ ] Agent `endpointUrl=http://localhost:9100` (echo agent's address)
- [ ] UAID saved to environment variable

---

### Test 5: Cross-Gateway Invocation WITH Bearer Token (Success)

**Purpose:** Verify token forwarding and RBAC enforcement

**Steps:**

```bash
# From Gateway A, invoke agent on Gateway B using UAID
# Note: Uses /a2a/invoke endpoint with agent_id in body (not path) to support UAIDs with forward slashes
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d "{
    \"agent_id\": \"$UAID_AGENT_B\",
    \"parameters\": {
      \"query\": \"test cross-gateway auth\"
    }
  }" | jq
```

**Expected Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "artifacts": [{
      "artifactId": "task-...",
      "description": "Echo response",
      "name": "echo",
      "parts": [{"text": "test cross-gateway auth"}]
    }],
    "status": {
      "state": "TASK_STATE_COMPLETED",
      ...
    }
  }
}
```

**Expected Behavior:**

1. Gateway A extracts bearer token from `Authorization` header
2. Gateway A parses UAID and extracts `nativeId=127.0.0.1:4445`
3. Gateway A validates domain against allowlist: `127.0.0.1:4445` ✅
4. Gateway A calls `http://127.0.0.1:4445/a2a/invoke` with UAID in body and forwarded bearer token
5. Gateway B validates token (shared JWT secret)
6. Gateway B looks up agent by UAID locally
7. Gateway B invokes `http://localhost:9100` (echo agent)
8. Echo agent responds with A2A protocol response
9. Response returns through Gateway B → Gateway A

**Check Gateway A Logs:**

```
⚠️  SECURITY: First cross-gateway UAID call detected.
Cross-gateway routing forwards bearer tokens when available...
```

**Check Gateway B Logs:**

```
INFO: Authenticated user: admin@example.com
INFO: Cross-gateway invocation from Gateway A
```

**Verification Checklist:**

- [ ] Request succeeds (200 OK)
- [ ] Echo agent response received with echoed query text
- [ ] Token forwarded (check Gateway B auth logs)
- [ ] Audit headers present (`X-Contextforge-UAID-Hop`)
- [ ] RBAC enforced on Gateway B

---

### Test 6: Cross-Gateway WITHOUT Token (Auth Required)

**Purpose:** Verify remote gateway rejects unauthenticated requests

**Steps:**

```bash
# From Gateway A, invoke WITHOUT bearer token
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"$UAID_AGENT_B\",
    \"parameters\": {
      \"query\": \"unauthenticated test\"
    }
  }"
```

**Expected Response:**

```json
{
  "detail": "Cross-gateway authentication failed: remote gateway returned 401 Unauthorized. Possible causes: 1) JWT trust mismatch..."
}
```

**Check Gateway A Logs:**

```
WARNING: Cross-gateway call without bearer token. Remote gateway will receive unauthenticated request.
```

**Check Gateway B Logs:**

```
ERROR: Authentication required but no token provided
401 Unauthorized
```

**Verification Checklist:**

- [ ] Request fails with 401/403
- [ ] Error message includes troubleshooting guidance
- [ ] Gateway A logs warning about missing token
- [ ] Gateway B rejects unauthenticated request

---

### Test 7: Fail-Closed Allowlist (Blocked Domain)

**Purpose:** Verify routing blocked for domains not in allowlist

**Steps:**

```bash
# Register agent with disallowed domain on Gateway A
curl -X POST http://localhost:4444/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "blocked-agent",
      "description": "Agent with blocked domain",
      "endpoint_url": "http://evil.example.com/agent",
      "generate_uaid": true,
      "uaid_registry": "context-forge"
    },
    "visibility": "public"
  }'
```

**Expected Response:**

```json
{
  "detail": "UAID registration blocked for security: endpoint domain 'evil.example.com' not in UAID_ALLOWED_DOMAINS. Allowed domains: ['localhost:4444', '127.0.0.1:4444', 'localhost:4445', '127.0.0.1:4445']..."
}
```

**Verification Checklist:**

- [ ] Registration FAILS (400 Bad Request)
- [ ] Error message mentions domain allowlist
- [ ] Configuration guidance provided

---

### Test 8: UAID_ALLOW_ALL_DOMAINS Bypass (Development Mode)

**Purpose:** Verify bypass flag allows routing to any domain

**Steps:**

```bash
# Stop Gateway A (Ctrl+C), edit config
# In .env.test-a, set:
echo "UAID_ALLOW_ALL_DOMAINS=true" >> .env.test-a

# Restart Gateway A
ENV_FILE=.env.test-a make dev

# Now try registering agent with arbitrary domain
curl -X POST http://localhost:4444/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "bypass-test-agent",
      "description": "Agent with arbitrary domain (bypass enabled)",
      "endpoint_url": "http://test.example.com/agent",
      "generate_uaid": true,
      "uaid_registry": "context-forge"
    },
    "visibility": "public"
  }' | jq
```

**Expected Response:**

```json
{
  "id": "<uuid>",
  "name": "bypass-test-agent",
  "uaid": "uaid:aid:...",
  "uaid_native_id": "test.example.com",
  ...
}
```

**Check Gateway A Logs:**

```
WARNING: ⚠️  Configuration conflict: UAID_ALLOW_ALL_DOMAINS=true bypasses the configured UAID_ALLOWED_DOMAINS list.
```

**Verification Checklist:**

- [ ] Registration succeeds (bypass active)
- [ ] Warning logged about bypass
- [ ] Arbitrary domain accepted

**⚠️ Important:** Reset `UAID_ALLOW_ALL_DOMAINS=false` after this test!

---

### Test 9: Subdomain Matching

**Purpose:** Verify subdomain allowlist matching works correctly

**Steps:**

```bash
# Edit Gateway A config (.env.test-a):
# UAID_ALLOWED_DOMAINS=["example.com"]
# (Remove port-specific entries, keep bypass=false)

# Restart Gateway A
ENV_FILE=.env.test-a make dev

# Test 1: Exact match
curl -X POST http://localhost:4444/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "exact-match",
      "endpoint_url": "http://example.com/agent",
      "generate_uaid": true
    },
    "visibility": "public"
  }' | jq

# Should succeed ✅

# Test 2: Subdomain match
curl -X POST http://localhost:4444/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "subdomain-match",
      "endpoint_url": "http://api.example.com/agent",
      "generate_uaid": true
    },
    "visibility": "public"
  }' | jq

# Should succeed ✅

# Test 3: Suffix attack prevention
curl -X POST http://localhost:4444/a2a \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d '{
    "agent": {
      "name": "evil-suffix",
      "endpoint_url": "http://evilexample.com/agent",
      "generate_uaid": true
    },
    "visibility": "public"
  }' | jq

# Should FAIL ❌ (not a proper subdomain)
```

**Verification Checklist:**

- [ ] Exact domain matches
- [ ] Proper subdomains match (sub.example.com)
- [ ] Suffix attacks blocked (evilexample.com)

---

### Test 10: IPv6 Domain Handling

**Purpose:** Verify IPv6 bracket notation handled correctly

**Steps:**

```bash
# Edit Gateway A config (.env.test-a):
# UAID_ALLOWED_DOMAINS=["[::1]", "localhost"]

# Try starting Gateway A - should FAIL at config validation
ENV_FILE=.env.test-a make dev
```

**Expected Error:**

```
ValueError: Invalid domains in UAID_ALLOWED_DOMAINS: '[::1]' (loopback address). Use public DNS names only.
```

**Verification Checklist:**

- [ ] IPv6 loopback addresses rejected at config validation
- [ ] Error message mentions security reason (loopback address)
- [ ] Gateway fails to start (config validation failure)

---

### Test 11: Invalid Domain Configuration

**Purpose:** Verify config validators reject dangerous domains

**Steps:**

```bash
# Test 1: Localhost in allowlist
cat > .env.test-invalid <<EOF
HOST=127.0.0.1
PORT=4444
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=["localhost", "example.com"]
EOF

ENV_FILE=.env.test-invalid make dev
# Should FAIL with validation error

# Test 2: Private IP in allowlist
cat > .env.test-invalid <<EOF
HOST=127.0.0.1
PORT=4444
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=["192.168.1.100"]
EOF

ENV_FILE=.env.test-invalid make dev
# Should FAIL with validation error

# Test 3: Link-local in allowlist
cat > .env.test-invalid <<EOF
HOST=127.0.0.1
PORT=4444
MCPGATEWAY_A2A_ENABLED=true
UAID_ALLOWED_DOMAINS=["169.254.1.1"]
EOF

ENV_FILE=.env.test-invalid make dev
# Should FAIL with validation error
```

**Expected Error:**

```
ValueError: Invalid domains in UAID_ALLOWED_DOMAINS: 'localhost' (loopback address), '192.168.1.100' (private IP range). Use public DNS names only.
```

**Verification Checklist:**

- [ ] Localhost rejected
- [ ] Private IPs rejected (10.x, 192.168.x, 172.16-31.x)
- [ ] Link-local rejected (169.254.x.x)
- [ ] Error messages are clear

---

### Test 12: Audit Trail Headers

**Purpose:** Verify X-Contextforge-* headers for tracing

**Steps:**

```bash
# Reset Gateway A and B to proper configs
ENV_FILE=.env.test-a make dev  # Terminal 1
ENV_FILE=.env.test-b make dev  # Terminal 2

# On Gateway B, enable debug logging
# Edit .env.test-b: LOG_LEVEL=DEBUG
# Restart Gateway B

# From Gateway A, invoke agent on Gateway B
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d "{
    \"agent_name\": \"$UAID_AGENT_B\",
    \"parameters\": {}
  }" | jq
```

**Check Gateway B Debug Logs for Headers:**

```
Authorization: Bearer <token>
X-Contextforge-Source-Gateway: <gateway-a-id>
X-Contextforge-Source-User: admin@example.com
X-Contextforge-Correlation-ID: <correlation-id>
X-Contextforge-UAID-Hop: 1
```

**Verification Checklist:**

- [ ] Authorization header forwarded
- [ ] Source gateway ID present
- [ ] Source user email present
- [ ] Correlation ID for tracing
- [ ] Hop count tracked

---

### Test 13: Token Expiration Handling

**Purpose:** Verify expired token error messages

**Steps:**

```bash
# Generate expired token (exp=0 means already expired)
TOKEN_EXPIRED=$(python -m mcpgateway.utils.create_jwt_token \
  --username expired@example.com \
  --exp 0 \
  --secret shared-test-secret-12345)

# Try cross-gateway call with expired token
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_EXPIRED" \
  -d "{
    \"agent_name\": \"$UAID_AGENT_B\",
    \"parameters\": {}
  }"
```

**Expected Response:**

```json
{
  "detail": "Cross-gateway authentication failed: remote gateway returned 401 Unauthorized. Possible causes: ... 2) Token expired: User token expired before cross-gateway call completed..."
}
```

**Verification Checklist:**

- [ ] Request fails with 401
- [ ] Error message mentions token expiration
- [ ] Troubleshooting guidance included

---

### Test 14: JWT Trust Mismatch

**Purpose:** Verify error when gateways use different JWT secrets

**Steps:**

```bash
# Edit Gateway B config (.env.test-b):
# JWT_SECRET_KEY=different-secret-67890
# (Different from Gateway A)

# Restart Gateway B
ENV_FILE=.env.test-b make dev

# Try cross-gateway call
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d "{
    \"agent_name\": \"$UAID_AGENT_B\",
    \"parameters\": {}
  }"
```

**Expected Response:**

```json
{
  "detail": "Cross-gateway authentication failed: remote gateway returned 401 Unauthorized. Possible causes: 1) JWT trust mismatch: Gateway A and B use different JWT_SECRET_KEY..."
}
```

**Verification Checklist:**

- [ ] Request fails with 401
- [ ] Error message mentions JWT trust mismatch
- [ ] Configuration fix guidance provided

**⚠️ Important:** Reset Gateway B to shared secret after test

---

### Test 15: UAID_FORWARD_AUTH Disabled

**Purpose:** Verify token not forwarded when feature disabled

**Steps:**

```bash
# Edit Gateway A config (.env.test-a):
# UAID_FORWARD_AUTH=false

# Restart Gateway A
ENV_FILE=.env.test-a make dev

# Try cross-gateway call
curl -X POST "http://localhost:4444/a2a/invoke" \
  -H "Content-Type: application/json" \
  -H "$AUTH_ADMIN" \
  -d "{
    \"agent_name\": \"$UAID_AGENT_B\",
    \"parameters\": {}
  }"
```

**Check Gateway A Logs:**

```
INFO: UAID_FORWARD_AUTH disabled: not forwarding bearer token for cross-gateway call. Remote gateway will receive unauthenticated request.
```

**Expected Behavior:**

- Gateway B should reject (401) if AUTH_REQUIRED=true
- Or succeed if AUTH_REQUIRED=false

**Verification Checklist:**

- [ ] Token NOT forwarded (check Gateway B logs)
- [ ] Gateway A logs explain token not forwarded
- [ ] Remote gateway behavior depends on AUTH_REQUIRED

---

## Test Summary Checklist

### Startup Validation

- [ ] Empty allowlist logs ERROR (non-blocking)
- [ ] Strict mode fails startup when allowlist empty
- [ ] Warning logged when bypass enabled

### Domain Allowlist

- [ ] Fail-closed: empty allowlist blocks routing
- [ ] Populated allowlist allows matching domains
- [ ] Subdomain matching works correctly
- [ ] Suffix attack prevention (evilexample.com blocked)
- [ ] Config validator rejects localhost, private IPs, link-local

### Token Forwarding

- [ ] Bearer token forwarded in Authorization header
- [ ] Audit headers included (Source-Gateway, Source-User, Correlation-ID)
- [ ] Token validated by remote gateway
- [ ] RBAC enforced based on token claims
- [ ] Missing token logged with warning

### Error Handling

- [ ] 401 from remote gateway has actionable error message
- [ ] JWT trust mismatch detected and explained
- [ ] Token expiration guidance provided
- [ ] Domain validation errors include configuration fix

### Security Features

- [ ] UAID_ALLOW_ALL_DOMAINS=true bypasses allowlist (logs warning)
- [ ] UAID_FORWARD_AUTH=false prevents token forwarding (logs info)
- [ ] Hop count tracked in headers
- [ ] Cross-gateway calls logged for audit

---

## Cleanup

```bash
# Stop both gateways (Ctrl+C in each terminal)

# Clean up test databases
rm -f mcp-test-a.db mcp-test-b.db mcp-test-empty.db mcp-test-strict.db

# Remove test configs
rm -f .env.test-a .env.test-b .env.test-empty .env.test-strict .env.test-invalid

# Unset environment variables
unset JWT_SECRET TOKEN_ADMIN TOKEN_USER AUTH_ADMIN AUTH_USER UAID_AGENT_B TOKEN_EXPIRED
```

---

## Expected Results Summary

| Test | Expected Result | Security Impact |
|------|----------------|-----------------|
| Empty allowlist | ERROR log, routing blocked | ✅ Fail-closed prevents SSRF |
| Strict mode | Startup fails | ✅ Forces explicit config |
| Token forwarding | 200 OK, token validated | ✅ RBAC preserved |
| No token | 401/403 from remote | ✅ Auth required |
| Blocked domain | 400 Bad Request | ✅ SSRF prevention |
| Bypass flag | Accepts any domain | ⚠️ Dev-only, unsafe |
| Subdomain match | Succeeds | ✅ Proper matching |
| Suffix attack | Blocked | ✅ Security validated |
| IPv6 loopback | Blocked | ✅ Config validator |
| Expired token | 401 with guidance | ✅ Token lifecycle |
| JWT mismatch | 401 with guidance | ✅ Trust boundary |
| Forward disabled | No token sent | ℹ️ Documented behavior |

---

## Questions to Validate

1. **Does fail-closed default prevent accidental SSRF?** ✅ Yes
2. **Are error messages actionable for operators?** ✅ Yes
3. **Can tokens be traced across gateways?** ✅ Yes (audit headers)
4. **Is RBAC properly enforced on remote gateways?** ✅ Yes
5. **Are dangerous domains rejected at config time?** ✅ Yes
6. **Does bypass flag work for development?** ✅ Yes (with warnings)
7. **Are subdomain matches secure?** ✅ Yes (proper suffix check)

---

## Notes for Testers

- This test plan covers **security-critical features** - all tests should pass before merge
- Pay special attention to **deny paths** (blocked domains, expired tokens, missing auth)
- Check both **logs and HTTP responses** for proper error messages
- Verify **audit headers** are present for cross-gateway tracing
- Test with both **valid and invalid** configurations to ensure fail-safe behavior

---

**Last Updated:** 2026-04-21
**PR Reference:** #4342
**Related Documentation:** `docs/security/uaid-cross-gateway-auth.md`
