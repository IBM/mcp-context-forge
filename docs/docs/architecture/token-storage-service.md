# Per-User OAuth Token Storage in ContextForge

## Overview

[`TokenStorageService`](../../mcpgateway/services/token_storage_service.py) is ContextForge's
**per-user OAuth token vault**. It stores, retrieves, auto-refreshes, and cleans up OAuth
`access_token` + `refresh_token` pairs that are obtained through the **OAuth 2.0 Authorization
Code flow** (RFC 6749 §4.1).

It is **not** involved in the simpler `client_credentials` flow — that flow exchanges a
`client_id` + `client_secret` directly each time and never stores a user-specific token.

---

## Why Per-User Tokens?

In Authorization Code flow, each *human user* authenticates directly with the OAuth provider
(GitHub, Jira, etc.) and receives their own personal `access_token`. That token carries their
identity and permissions at the upstream MCP server.

**Sharing tokens across users is a security vulnerability.** A previous helper
(`get_any_valid_token()`) was deliberately removed from the service for exactly that reason — see
the inline comment at
[`token_storage_service.py:240`](../../mcpgateway/services/token_storage_service.py:240).

The [`OAuthToken`](../../mcpgateway/db.py:5262) database table enforces this with a unique
constraint on `(gateway_id, app_user_email)` — one row per user per gateway.

---

## Database Model

```
oauth_tokens table
──────────────────────────────────────────────────────────────────────────
 id              TEXT  PK
 gateway_id      TEXT  FK → gateways.id  ON DELETE CASCADE
 user_id         TEXT  OAuth provider's user ID (e.g. GitHub uid "1234567")
 app_user_email  TEXT  FK → email_users.email  (ContextForge user identity)
 access_token    TEXT  Encrypted at rest (EncryptedText column type)
 refresh_token   TEXT  Encrypted at rest, nullable
 token_type      TEXT  Always "Bearer"
 expires_at      DATETIME(tz)  NULL means provider did not specify a lifetime
 scopes          JSON  e.g. ["repo", "read:user"]
 created_at      DATETIME(tz)
 updated_at      DATETIME(tz)

UNIQUE (gateway_id, app_user_email)   ← one row per user per gateway
──────────────────────────────────────────────────────────────────────────
```

---

## Service API

| Method | When called | What it does |
|---|---|---|
| [`store_tokens()`](../../mcpgateway/services/token_storage_service.py:119) | OAuth callback | Encrypts & upserts access + refresh tokens for a `(gateway_id, user_email)` pair |
| [`get_user_token()`](../../mcpgateway/services/token_storage_service.py:194) | Every tool call / health check | Returns a decrypted, valid access token; auto-triggers refresh if within 5 min of expiry |
| [`_refresh_access_token()`](../../mcpgateway/services/token_storage_service.py:243) | Called internally by `get_user_token()` | Uses stored refresh token + gateway OAuth config to get a new access token from the IdP |
| [`_is_token_expired()`](../../mcpgateway/services/token_storage_service.py:429) | Called internally | Time-check with configurable lead threshold; `expires_at IS NULL` → non-expired |
| [`get_token_info()`](../../mcpgateway/services/token_storage_service.py:472) | Admin status API | Returns non-sensitive metadata (scopes, expiry, is_expired) without exposing the raw token |
| [`revoke_user_tokens()`](../../mcpgateway/services/token_storage_service.py:524) | User logout / admin revoke | Hard-deletes the row |
| [`cleanup_expired_tokens()`](../../mcpgateway/services/token_storage_service.py:566) | Scheduled maintenance | Batch-deletes stale rows older than `max_age_days` (handles both `expires_at`-set and `NULL` rows) |

---

## Where It Is Used in the Codebase

```
oauth_router.py:499   initiate_oauth_flow()       — injects TokenStorageService into OAuthManager
                                                     so the manager can write tokens after callback
oauth_router.py:627   oauth_callback()            — same injection; store_tokens() called here
                                                     after IdP returns authorization code

gateway_service.py    fetch_tools_after_oauth()   — get_user_token() to connect to MCP server
  :1931                                              and discover its tool list post-auth

gateway_service.py    health_check_gateway_loop() — get_user_token() for Bearer header during
  :4343                                              background health probes

tool_service.py       call_tool() / invoke path   — get_user_token() to inject Bearer header
  :4060, 5250                                        into every upstream MCP tool invocation
```

---

## Real-World Scenario: Multi-User, Multi-Server Virtual MCP Setup

### Setup

A company uses ContextForge to host all their MCP servers. An admin registers two upstream
servers and builds a virtual server that aggregates both:

```
Registered Gateways
───────────────────
  gw-github   → https://mcp.github.acme.com   auth: OAuth / authorization_code
  gw-jira     → https://mcp.jira.acme.com     auth: OAuth / authorization_code

Virtual Server
──────────────
  vs-engineering  includes: [ gw-github, gw-jira ]
```

Users invoke tools from `vs-engineering`. Under the hood, ContextForge routes each tool call to
the right upstream gateway, injecting the **calling user's own OAuth token** for that gateway.

---

### Step 1 — Register the GitHub Gateway (Admin, one-time)

```http
POST /gateways
Content-Type: application/json

{
  "name": "GitHub MCP",
  "url":  "https://mcp.github.acme.com/sse",
  "transport": "SSE",
  "auth_type": "oauth",
  "oauth_config": {
    "grant_type":        "authorization_code",
    "client_id":         "Ov23liABC123",
    "client_secret":     "ghp_secret_stored_encrypted",
    "authorization_url": "https://github.com/login/oauth/authorize",
    "token_url":         "https://github.com/login/oauth/access_token",
    "scopes":            ["repo", "read:user"],
    "redirect_uri":      "https://contextforge.acme.com/oauth/callback"
  }
}
```

Response → `{ "id": "gw-github", ... }`

Repeat for Jira (using its own client credentials and IdP URLs) → `gw-jira`.

---

### Step 2 — Create the Virtual Server (Admin, one-time)

```http
POST /servers
Content-Type: application/json

{
  "name":     "Engineering Assistant",
  "slug":     "engineering",
  "gateways": ["gw-github", "gw-jira"]
}
```

---

### Step 3 — User 1 (alice) Authenticates with GitHub

Alice navigates to (or is redirected to):

```
GET /oauth/authorize/gw-github
Authorization: Bearer <alice-CF-session-token>
```

**Inside ContextForge** ([`initiate_oauth_flow()`](../../mcpgateway/routers/oauth_router.py:365)):

1. Loads `gw-github` config from the DB.
2. Generates a PKCE `code_verifier` + `code_challenge` and a signed `state` token that encodes
   `{ gateway_id: "gw-github", app_user_email: "alice@acme.com" }`.
3. Saves the state to the `oauth_states` table with a 10-minute TTL.
4. Returns `302 → https://github.com/login/oauth/authorize?client_id=...&state=...&code_challenge=...`

Alice logs in to GitHub and approves the scope. GitHub redirects back:

```
GET /oauth/callback?code=abc123xyz&state=<signed-state>
```

**Inside ContextForge** ([`oauth_callback()`](../../mcpgateway/routers/oauth_router.py:515)):

1. Validates HMAC on `state`, looks up the state row → resolves `gateway_id = "gw-github"`,
   `app_user_email = "alice@acme.com"`.
2. Posts to `https://github.com/login/oauth/access_token` with the authorization `code` +
   `code_verifier`.
3. Receives `{ access_token, refresh_token, expires_in: 28800, scope: "repo read:user" }`.
4. Calls [`store_tokens()`](../../mcpgateway/services/token_storage_service.py:119):

```python
await token_storage.store_tokens(
    gateway_id      = "gw-github",
    user_id         = "github_uid_44712",     # GitHub's numeric user ID
    app_user_email  = "alice@acme.com",        # ContextForge identity
    access_token    = "gho_Aa1Bb2...",
    refresh_token   = "ghr_Rr9Ss8...",
    expires_in      = 28800,                   # 8 hours
    scopes          = ["repo", "read:user"]
)
```

**What happens in `store_tokens()`:**

```
1. Encrypts access_token  → "gAAAAABh..."  (Fernet AES-128-CBC)
2. Encrypts refresh_token → "gAAAAABh..."
3. Computes expires_at    = now + 28800s
4. UPSERTs row in oauth_tokens:

   gateway_id     = "gw-github"
   app_user_email = "alice@acme.com"
   access_token   = <encrypted>
   refresh_token  = <encrypted>
   expires_at     = 2025-06-10 18:00:00 UTC
   scopes         = ["repo", "read:user"]
```

Alice sees a success page. She clicks "Fetch Tools" which triggers
[`fetch_tools_after_oauth()`](../../mcpgateway/services/gateway_service.py:1884) — this
immediately calls `get_user_token()`, gets the decrypted token, connects to the GitHub MCP
server with `Authorization: Bearer gho_Aa1Bb2...`, and syncs the tool list into ContextForge.

---

### Step 4 — User 2 (bob) Authenticates with Jira

Bob goes to:

```
GET /oauth/authorize/gw-jira
Authorization: Bearer <bob-CF-session-token>
```

Same flow executes. After Jira's callback:

```
oauth_tokens table now contains:

 gateway_id  | app_user_email    | access_token | refresh_token | expires_at
─────────────┼───────────────────┼──────────────┼───────────────┼──────────────────────
 gw-github   | alice@acme.com    | <encrypted>  | <encrypted>   | 2025-06-10 18:00 UTC
 gw-jira     | bob@acme.com      | <encrypted>  | <encrypted>   | 2025-06-10 20:00 UTC
```

Note: Alice does **not** have a Jira token row, and Bob does **not** have a GitHub token row.
**Token isolation is enforced by the `UNIQUE (gateway_id, app_user_email)` constraint.**

---

### Step 5 — Tool Invocation via the Virtual Server

#### Alice calls `search_code` (GitHub tool)

```http
POST /servers/engineering/mcp
Content-Type: application/json
Authorization: Bearer <alice-CF-session-token>

{
  "method": "tools/call",
  "params": {
    "name":      "github__search_code",
    "arguments": { "query": "TokenStorageService" }
  }
}
```

**ContextForge internal path** ([`tool_service.py:4054`](../../mcpgateway/services/tool_service.py:4054)):

```python
# 1. Resolve tool → belongs to gateway gw-github
# 2. Check gateway auth type → "oauth", grant_type → "authorization_code"
# 3. Call TokenStorageService.get_user_token("gw-github", "alice@acme.com")

token_storage = TokenStorageService(token_db)
access_token  = await token_storage.get_user_token("gw-github", "alice@acme.com")
# → _is_token_expired(threshold=300)? No → decrypt → return "gho_Aa1Bb2..."

# 4. Build outbound request to GitHub MCP server
headers = { "Authorization": "Bearer gho_Aa1Bb2..." }
# → POST https://mcp.github.acme.com/sse  with Alice's personal GitHub token
```

**GitHub MCP server sees Alice's identity** and returns results scoped to Alice's repos.

#### Bob calls `create_issue` (Jira tool)

```http
POST /servers/engineering/mcp
Content-Type: application/json
Authorization: Bearer <bob-CF-session-token>

{
  "method": "tools/call",
  "params": {
    "name":      "jira__create_issue",
    "arguments": { "summary": "Fix login bug", "project": "ENG" }
  }
}
```

**ContextForge internal path:**

```python
token_storage = TokenStorageService(token_db)
access_token  = await token_storage.get_user_token("gw-jira", "bob@acme.com")
# → decrypt → return Bob's Jira access_token

headers = { "Authorization": "Bearer <bob-jira-token>" }
# → POST https://mcp.jira.acme.com/...  with Bob's personal Jira token
```

**Jira sees Bob's identity** and creates the issue under Bob's account.

---

### Step 6 — Transparent Token Refresh

Seven hours into Alice's session, her GitHub token (8-hour TTL) is within 5 minutes of expiry.

```
Next tool call by Alice → get_user_token("gw-github", "alice@acme.com")

_is_token_expired(threshold_seconds=300)
  now + 300s  >= expires_at  → True   (token expires in 4 minutes)

→ _refresh_access_token(token_record)
    1. Verifies gateway visibility ≠ "private" owned by someone else
    2. Decrypts refresh_token
    3. OAuthManager.refresh_token() → POST github.com/login/oauth/access_token
       body: grant_type=refresh_token&refresh_token=ghr_Rr9Ss8...&client_id=...
    4. Response: { access_token: "gho_Cc3Dd4...", expires_in: 28800 }
    5. Encrypts & updates the row in place (same gateway_id + app_user_email key)
    6. Returns new plain-text "gho_Cc3Dd4..."

Alice's tool call continues with the fresh token — she never re-authorized manually.
```

If GitHub returns a refresh response **without `expires_in`**
([`_preserve_prior_ttl()`](../../mcpgateway/services/token_storage_service.py:32) fires):
the prior TTL (8 hours) is preserved so the refresh cycle keeps running.

---

### Step 7 — Cross-User Isolation Proof

Alice tries to call a Jira tool without having authorized Jira:

```python
await token_storage.get_user_token("gw-jira", "alice@acme.com")
# → SELECT ... WHERE gateway_id='gw-jira' AND app_user_email='alice@acme.com'
# → None  (no row exists)
# → returns None
```

ContextForge raises:

```
GatewayConnectionError: No OAuth tokens found for user alice@acme.com on gateway
  Jira MCP. Please complete the OAuth authorization flow first at
  /oauth/authorize/gw-jira
```

Alice cannot use Bob's Jira token. The service never queries for *any* valid token — only the
one explicitly tied to the calling user's email.

---

### Step 8 — Token Revocation and Cleanup

Bob's token can be revoked by an admin or by Bob himself:

```http
DELETE /oauth/tokens/gw-jira?user=bob@acme.com
```

Calls [`revoke_user_tokens("gw-jira", "bob@acme.com")`](../../mcpgateway/services/token_storage_service.py:524)
→ hard-deletes only Bob's Jira row. Alice's GitHub row is untouched.

A scheduled job cleans up stale rows:

```python
await token_storage.cleanup_expired_tokens(max_age_days=30)
# Deletes:
#   - rows where expires_at < (now - 30 days)
#   - rows where expires_at IS NULL AND updated_at < (now - 30 days)
#     (handles GitHub Apps tokens that never return expires_in)
```

---

## Security Properties

| Property | How it is enforced |
|---|---|
| **Tokens encrypted at rest** | `EncryptedText` column type (Fernet AES-128-CBC); `AUTH_ENCRYPTION_SECRET` is the key |
| **User isolation** | `UNIQUE (gateway_id, app_user_email)` DB constraint; `get_user_token()` always filters by both columns |
| **No cross-user token sharing** | `get_any_valid_token()` was deliberately removed |
| **Private-gateway guard** | `_refresh_access_token()` blocks refresh if `gateway.visibility == "private"` and the token owner ≠ gateway owner |
| **PKCE** | `OAuthManager.initiate_authorization_code_flow()` generates `code_verifier` + `S256 code_challenge` automatically |
| **CSRF protection** | `state` token is HMAC-signed; validated in `oauth_callback()` before any token exchange |
| **Proactive expiry** | `threshold_seconds=300` (default) refreshes 5 minutes early, preventing mid-call expiry |
| **NULL-expiry safety** | Tokens with no `expires_at` are never incorrectly flagged as expired; aged out only by `cleanup_expired_tokens()` |

---

## Full End-to-End Sequence Diagram

```
Alice           ContextForge            GitHub IdP         GitHub MCP
  │                   │                     │                  │
  │ GET /oauth/       │                     │                  │
  │ authorize/gw-github                     │                  │
  │──────────────────>│                     │                  │
  │                   │ build state+PKCE    │                  │
  │                   │ save to oauth_states│                  │
  │ 302 → github.com  │                     │                  │
  │<──────────────────│                     │                  │
  │                   │                     │                  │
  │ (Alice logs in at GitHub and approves)  │                  │
  │                   │                     │                  │
  │ GET /oauth/callback?code=abc&state=xyz  │                  │
  │──────────────────>│                     │                  │
  │                   │ validate HMAC state │                  │
  │                   │ POST /access_token  │                  │
  │                   │────────────────────>│                  │
  │                   │ {access, refresh,   │                  │
  │                   │  expires_in: 28800} │                  │
  │                   │<────────────────────│                  │
  │                   │ store_tokens()      │                  │
  │                   │ encrypt + upsert    │                  │
  │                   │ oauth_tokens row    │                  │
  │ 200 Success page  │                     │                  │
  │<──────────────────│                     │                  │
  │                   │                     │                  │
  │ (later) tool call │                     │                  │
  │ tools/call github__search_code          │                  │
  │──────────────────>│                     │                  │
  │                   │ get_user_token()    │                  │
  │                   │ decrypt access_tok  │                  │
  │                   │ Authorization: Bearer gho_...          │
  │                   │────────────────────────────────────────>
  │                   │                     │ result           │
  │                   │<────────────────────────────────────────
  │ tool result       │                     │                  │
  │<──────────────────│                     │                  │
```

---

## Configuration Reference

| Environment variable | Default | Effect |
|---|---|---|
| `AUTH_ENCRYPTION_SECRET` | (required) | Fernet key for encrypting tokens at rest |
| `OAUTH_STATE_TTL_SECONDS` | `600` | How long the signed state token lives in `oauth_states` |
| `MCPGATEWAY_DCR_ENABLED` | `false` | Enable Dynamic Client Registration (RFC 7591) for auto-registering gateways |
| `MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS` | `false` | Auto-trigger DCR when `client_id` is absent |

Token cleanup is not driven by a cron config — call `cleanup_expired_tokens(max_age_days=30)`
from your own scheduler or the admin API.

---

## Related Files

| File | Role |
|---|---|
| [`mcpgateway/services/token_storage_service.py`](../../mcpgateway/services/token_storage_service.py) | The service itself |
| [`mcpgateway/db.py`](../../mcpgateway/db.py) (`OAuthToken`, `OAuthState`) | Database models |
| [`mcpgateway/routers/oauth_router.py`](../../mcpgateway/routers/oauth_router.py) | `/oauth/authorize` and `/oauth/callback` endpoints |
| [`mcpgateway/services/gateway_service.py`](../../mcpgateway/services/gateway_service.py) | Consumes `get_user_token()` for tool fetch and health checks |
| [`mcpgateway/services/tool_service.py`](../../mcpgateway/services/tool_service.py) | Consumes `get_user_token()` on every `tools/call` invocation |
| [`mcpgateway/services/oauth_manager.py`](../../mcpgateway/services/oauth_manager.py) | Handles the HTTP calls to the IdP; delegates storage to `TokenStorageService` |
| [`mcpgateway/services/encryption_service.py`](../../mcpgateway/services/encryption_service.py) | Provides `encrypt_secret_async()` / `decrypt_secret_async()` |
