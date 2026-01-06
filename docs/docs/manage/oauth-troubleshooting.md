# OAuth Troubleshooting Guide

This guide helps troubleshoot OAuth 2.0 authentication problems when registering MCP servers, particularly the "Invalid or expired state parameter" error.

---

## Understanding OAuth State Parameter

The OAuth state parameter serves two critical purposes:

- **CSRF Protection**: Prevents cross-site request forgery attacks via HMAC signature
- **Session Binding**: Links the authorization request to the callback with embedded gateway ID and user context

### How State Works in MCP Gateway

```text
┌─────────┐     1. GET /oauth/authorize/{gateway_id}     ┌─────────────┐
│  User   │ ────────────────────────────────────────────>│ MCP Gateway │
└─────────┘                                              └──────┬──────┘
                                                                │
                                                                │ 2. Generate:
                                                                │    - PKCE code_verifier/challenge
                                                                │    - State (JSON + HMAC signature)
                                                                │    - Store in Redis/DB/Memory
                                                                v
┌─────────┐     3. Redirect to provider with             ┌─────────────┐
│  User   │ <────────────────────────────────────────────│ MCP Gateway │
└────┬────┘        state + code_challenge                └─────────────┘
     │
     │ 4. User authenticates at OAuth provider
     v
┌─────────────┐
│   OAuth     │
│  Provider   │
└──────┬──────┘
       │
       │ 5. Redirect to /oauth/callback?code=xxx&state=xxx
       v
┌─────────────┐     6. Validate state:                   ┌─────────────┐
│ MCP Gateway │ ────────────────────────────────────────>│ State Store │
│             │     - Check signature (HMAC-SHA256)      │             │
│             │     - Check expiration (5 min TTL)       │             │
│             │     - Check not already used             │             │
│             │     - Retrieve code_verifier             │             │
└──────┬──────┘                                          └─────────────┘
       │
       │ 7. Exchange code + code_verifier for tokens
       v
┌─────────────┐
│   OAuth     │
│  Provider   │
└─────────────┘
```

### State Structure

The state parameter is a base64-encoded JSON payload with HMAC signature:

```python
# From mcpgateway/services/oauth_manager.py:627
state_data = {
    "gateway_id": gateway_id,
    "app_user_email": app_user_email,
    "nonce": secrets.token_urlsafe(16),
    "timestamp": datetime.now(timezone.utc).isoformat()
}
# Signed with HMAC-SHA256 using AUTH_ENCRYPTION_SECRET
```

---

## OAuth Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/oauth/authorize/{gateway_id}` | GET | Initiates OAuth flow, redirects to provider |
| `/oauth/callback` | GET | Handles OAuth callback, exchanges code for tokens |
| `/oauth/status/{gateway_id}` | GET | Returns OAuth configuration status |
| `/oauth/fetch-tools/{gateway_id}` | POST | Fetches tools from MCP server after OAuth completion |
| `/oauth/registered-clients` | GET | Lists all DCR-registered OAuth clients |
| `/oauth/registered-clients/{gateway_id}` | GET | Gets registered client for specific gateway |
| `/oauth/registered-clients/{client_id}` | DELETE | Deletes a registered OAuth client |

---

## Error Messages and Their Causes

### "Invalid or expired state parameter - possible replay attack"

**Location**: `mcpgateway/services/oauth_manager.py:544`

**Causes**:

- State not found in storage (Redis/DB/Memory)
- State already consumed (single-use protection)
- State expired (TTL exceeded)

### "Invalid state signature - possible CSRF attack"

**Location**: `mcpgateway/services/oauth_manager.py:562`

**Causes**:

- State was tampered with
- `AUTH_ENCRYPTION_SECRET` changed between authorization and callback
- Corrupted state parameter in URL

### "State parameter gateway mismatch"

**Location**: `mcpgateway/services/oauth_manager.py:572`

**Causes**:

- Callback received for different gateway than initiated
- Gateway ID changed in state parameter
- Misconfigured redirect URI

### "State has expired for gateway {gateway_id}"

**Location**: `mcpgateway/services/oauth_manager.py:746, 782, 818`

**Cause**: OAuth flow took longer than 5 minutes (STATE_TTL_SECONDS = 300)

### "State was already used for gateway {gateway_id} - possible replay attack"

**Location**: `mcpgateway/services/oauth_manager.py:751, 789, 824`

**Cause**: User refreshed callback page or callback was triggered twice

### "State not found in [Redis|database|memory] for gateway {gateway_id}"

**Location**: `mcpgateway/services/oauth_manager.py:727, 772, 809`

**Causes**:

- Server restart (in-memory storage lost)
- Different worker handled callback (multi-worker with in-memory)
- State never stored (storage failure during authorization)

---

## Common Causes and Fixes

### 1. Multi-Worker Deployment with In-Memory Storage

**Symptom**: Intermittent failures - sometimes works, sometimes doesn't.

**Cause**: In-memory storage doesn't share state across workers.

!!! note
    The default `CACHE_TYPE` is `database`, which supports multi-worker deployments.
    This issue only occurs if you explicitly set `CACHE_TYPE=memory`.

```python
# From mcpgateway/services/oauth_manager.py:35-37
_oauth_states: Dict[str, Dict[str, Any]] = {}  # Per-process only when CACHE_TYPE=memory!
```

**Diagnosis**:

```bash
# Check your cache type configuration
grep CACHE_TYPE .env
# Default is "database" - which is safe for multi-worker

# If CACHE_TYPE=memory, check worker count
ps aux | grep -E "(gunicorn|uvicorn)" | grep -v grep
# Multiple workers + CACHE_TYPE=memory = problem
```

**Fix**:

```bash
# Option A: Use default database storage (recommended - already the default)
CACHE_TYPE=database

# Option B: Use Redis for better performance
CACHE_TYPE=redis
REDIS_URL=redis://localhost:6379

# Option C: Single worker (development only, if using memory)
# gunicorn --workers 1 ...
```

### 2. State TTL Expired (5 Minutes)

**Symptom**: Always fails if user takes too long to authenticate.

**Cause**: State expires after 300 seconds.

```python
# From mcpgateway/services/oauth_manager.py:42
STATE_TTL_SECONDS = 300  # 5 minutes
```

**Diagnosis**:

- Check timestamps in debug logs
- Note time between "Stored OAuth state" and callback

**Fix**:

- Complete OAuth flow within 5 minutes
- For slow identity providers, consider increasing TTL (requires code change)

### 3. State Already Consumed (Replay Protection)

**Symptom**: First attempt works, refresh/retry fails.

**Cause**: State is single-use and deleted after validation.

```python
# From mcpgateway/services/oauth_manager.py:724-725
# Get and delete state atomically (single-use)
state_json = await redis.getdel(state_key)
```

**Diagnosis**:

```bash
# Check logs for duplicate callbacks
grep "State not found" logs/mcpgateway.log
grep "already been used" logs/mcpgateway.log
```

**Fix**:

- Don't refresh the callback page
- Start a new OAuth flow if needed (click "Authorize" again in Admin UI)

### 4. Server Restart During OAuth Flow

**Symptom**: Always fails after server restart.

**Cause**: In-memory states are lost on restart.

**Fix**:

- Use Redis or database storage for persistence
- Restart servers during low-traffic periods

### 5. Gateway ID Mismatch

**Symptom**: State validation fails with "gateway mismatch" in logs.

**Cause**: The callback returned to a different gateway than expected.

```python
# From mcpgateway/services/oauth_manager.py:572
raise OAuthError("State parameter gateway mismatch")
```

**Diagnosis**:

```bash
# Check for gateway mismatch errors
grep "gateway mismatch" logs/mcpgateway.log
```

**Fix**:

- Verify the OAuth redirect URI matches the gateway configuration
- Check that gateway IDs are consistent
- Ensure redirect_uri in OAuth provider matches `{BASE_URL}/oauth/callback`

### 6. Load Balancer Without Sticky Sessions

**Symptom**: Fails randomly in load-balanced environments.

**Cause**: Different backend handles callback than authorization.

**Fix**:

```bash
# Use distributed state storage
CACHE_TYPE=redis
REDIS_URL=redis://localhost:6379
```

Or configure sticky sessions in your load balancer (not recommended).

### 7. AUTH_ENCRYPTION_SECRET Changed

**Symptom**: "Invalid state signature" error after config change.

**Cause**: HMAC signature is validated using `AUTH_ENCRYPTION_SECRET`.

**Fix**:

- Don't change `AUTH_ENCRYPTION_SECRET` during active OAuth flows
- Clear all pending states after changing the secret
- Ensure consistent secret across all workers/instances

### 8. PKCE Code Verifier Lost

**Symptom**: Token exchange fails after successful callback.

**Cause**: PKCE `code_verifier` not found during token exchange (stored with state).

**Fix**: Same as state storage issues - ensure Redis/database storage is working.

---

## Admin UI OAuth Flow

### Starting OAuth Authorization

1. Navigate to **Admin Panel** > **Gateways**
2. Find gateway with `auth_type = oauth`
3. Click **Authorize** button (only visible for OAuth gateways)
4. Browser redirects to `/oauth/authorize/{gateway_id}`
5. User authenticates at OAuth provider
6. Callback redirects to success page
7. Click **Fetch Tools** to import MCP tools

---

## Debugging Steps

### Step 1: Enable Debug Logging

```bash
# .env
LOG_LEVEL=DEBUG
```

### Step 2: Check State Storage Type

```bash
# Verify current configuration
grep -E "^CACHE_TYPE" .env

# Valid values:
# CACHE_TYPE=database  (default - recommended, supports multi-worker)
# CACHE_TYPE=redis     (best for high-traffic production)
# CACHE_TYPE=memory    (single-worker only - NOT recommended)
# CACHE_TYPE=none      (disabled - OAuth will not work)
```

### Step 3: Monitor State Operations

Watch for these log messages:

```bash
# Successful state storage
grep "Stored OAuth state" logs/mcpgateway.log

# State validation
grep -E "(validated|not found|expired|already been used)" logs/mcpgateway.log

# Signature validation
grep -E "(Invalid state signature|CSRF)" logs/mcpgateway.log
```

**Healthy flow**:

```text
DEBUG - Stored OAuth state in Redis for gateway abc123
DEBUG - Successfully validated OAuth state from Redis for gateway abc123
INFO - Completed OAuth flow for gateway abc123, user user@example.com
```

**Problematic flow** (example: CACHE_TYPE=memory with multiple workers):

```text
DEBUG - Stored OAuth state in memory for gateway abc123
WARNING - State not found in memory for gateway abc123
ERROR - OAuth callback failed: Invalid or expired state parameter - possible replay attack
```

**Problematic flow** (example: state expired):

```text
DEBUG - Stored OAuth state in database for gateway abc123
WARNING - State has expired for gateway abc123
ERROR - OAuth callback failed: Invalid or expired state parameter - possible replay attack
```

### Step 4: Verify Redis Connectivity (if using Redis)

```bash
# Test Redis connection
redis-cli ping
# Should return: PONG

# Check OAuth states in Redis
redis-cli keys "oauth:state:*"

# Inspect a specific state (TTL and content)
redis-cli ttl "oauth:state:<gateway_id>:<state>"
redis-cli get "oauth:state:<gateway_id>:<state>"
```

### Step 5: Check Database States (if using database)

```sql
-- SQLite: Check for stored states (oauth_states table)
SELECT id, gateway_id, substr(state, 1, 50) as state_preview,
       code_verifier IS NOT NULL as has_pkce,
       expires_at, used, created_at
FROM oauth_states
ORDER BY created_at DESC
LIMIT 10;

-- SQLite: Check for expired states (should be cleaned up automatically)
SELECT COUNT(*) as expired_count
FROM oauth_states
WHERE expires_at < datetime('now');

-- Check for used states (should be deleted after use)
SELECT COUNT(*) as used_count
FROM oauth_states
WHERE used = 1;

-- View stored tokens after successful OAuth
SELECT id, gateway_id, user_id, app_user_email,
       expires_at, created_at
FROM oauth_tokens
ORDER BY created_at DESC
LIMIT 10;

-- PostgreSQL alternatives:
-- Use NOW() instead of datetime('now')
-- Use true instead of 1 for boolean
```

### Step 6: Trace a Single OAuth Flow

```bash
# Enable debug logging first
export LOG_LEVEL=DEBUG

# Start the gateway
make dev

# In another terminal, tail logs
tail -f logs/mcpgateway.log | grep -E "(OAuth|state|gateway)"

# Start OAuth flow in browser and watch the logs
```

---

## Configuration Reference

### Recommended Production Configuration

```bash
# .env

# Use Redis for distributed state storage (recommended)
CACHE_TYPE=redis
REDIS_URL=redis://localhost:6379

# Redis connection settings
REDIS_MAX_RETRIES=3
REDIS_RETRY_INTERVAL_MS=2000

# OAuth settings
OAUTH_REQUEST_TIMEOUT=30
OAUTH_MAX_RETRIES=3
OAUTH_DEFAULT_TIMEOUT=3600

# PKCE settings
OAUTH_DISCOVERY_ENABLED=true
OAUTH_PREFERRED_CODE_CHALLENGE_METHOD=S256

# Secret for signing state (CRITICAL - must be consistent across instances)
AUTH_ENCRYPTION_SECRET=your-secret-key-here

# Enable debug logging temporarily for troubleshooting
LOG_LEVEL=DEBUG
```

### Dynamic Client Registration (DCR)

If using DCR (RFC 7591) for automatic client registration:

```bash
# Enable DCR
DCR_ENABLED=true
DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true

# Default scopes for registered clients
DCR_DEFAULT_SCOPES=["mcp:read"]

# Token endpoint auth method
DCR_TOKEN_ENDPOINT_AUTH_METHOD=client_secret_basic

# Metadata cache TTL
DCR_METADATA_CACHE_TTL=3600
```

### State Storage Comparison

| Storage Type | CACHE_TYPE | Multi-Worker | Persistent | Performance | Use Case |
|--------------|------------|--------------|------------|-------------|----------|
| Database | `database` (default) | Yes | Yes | Good | Default, most deployments |
| Redis | `redis` | Yes | Optional | Best | High-traffic production |
| In-Memory | `memory` | **No** | No | Fast | Single-worker dev only |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TYPE` | `database` | `database`, `redis`, `memory`, or `none` |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string (when CACHE_TYPE=redis) |
| `DATABASE_URL` | `sqlite:///./mcp.db` | Database for state storage |
| `AUTH_ENCRYPTION_SECRET` | `my-test-salt` | Secret for HMAC signing states (change in production!) |
| `OAUTH_REQUEST_TIMEOUT` | `30` | Timeout for OAuth requests (seconds) |
| `OAUTH_MAX_RETRIES` | `3` | Max retries for token requests |
| `OAUTH_DEFAULT_TIMEOUT` | `3600` | Default token expiration (seconds) |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` for troubleshooting |

---

## Quick Fixes

### Fix 1: Verify Database Storage is Active (Default)

```bash
# Database storage is the default - verify it's set correctly
grep CACHE_TYPE .env

# If not set or set incorrectly, ensure it's using database:
# CACHE_TYPE=database

# Run migrations to ensure oauth_states table exists
alembic upgrade head

# Restart MCP Gateway
make dev
```

### Fix 2: Switch to Redis Storage (For High-Traffic Production)

```bash
# Install Redis if needed
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis

# Update .env
sed -i 's/CACHE_TYPE=.*/CACHE_TYPE=redis/' .env
# Or add if not present:
echo "CACHE_TYPE=redis" >> .env
echo "REDIS_URL=redis://localhost:6379" >> .env

# Restart MCP Gateway
make dev
```

### Fix 3: Single Worker Mode (Only if using CACHE_TYPE=memory)

```bash
# Only needed if you're using CACHE_TYPE=memory
# (Not recommended - switch to database or redis instead)
gunicorn mcpgateway.main:app --workers 1 --bind 0.0.0.0:4444

# Or using make
WORKERS=1 make serve
```

### Fix 4: Clear Stale States

```bash
# Redis - clear all OAuth states
redis-cli keys "oauth:state:*" | xargs -r redis-cli del

# Database - clear expired and stale states
sqlite3 mcp.db "DELETE FROM oauth_states WHERE expires_at < datetime('now') OR used = 1;"

# PostgreSQL
psql -c "DELETE FROM oauth_states WHERE expires_at < NOW() OR used = true;"
```

---

## Verifying the Fix

After applying fixes, verify OAuth works:

1. **Clear any stale states** (see Fix 4 above)

2. **Restart the gateway**:

    ```bash
    make dev
    ```

3. **Test OAuth flow**:

    - Go to Admin Panel > Gateways
    - Click "Authorize" on an OAuth-configured gateway
    - Complete authentication within 5 minutes
    - Verify success page shows "OAuth Authorization Successful"
    - Click "Fetch Tools" to verify token works

4. **Check logs for success**:

    ```bash
    grep "Successfully validated OAuth state" logs/mcpgateway.log
    grep "Completed OAuth flow" logs/mcpgateway.log
    ```

5. **Verify tokens stored**:

    ```sql
    SELECT * FROM oauth_tokens ORDER BY created_at DESC LIMIT 5;
    ```

---

## Troubleshooting DCR Issues

If using Dynamic Client Registration:

```bash
# Check DCR is enabled
grep DCR .env

# Look for DCR-related logs
grep -E "(DCR|Dynamic Client)" logs/mcpgateway.log

# Check registered clients
curl -s http://localhost:4444/oauth/registered-clients | jq

# Common DCR errors:
# - "DCR failed" - AS doesn't support RFC 7591
# - "No issuer configured" - Gateway missing issuer URL
# - "Metadata discovery failed" - AS metadata endpoint unreachable
```

---

## Related Documentation

- [OAuth Integration](oauth.md) - Main OAuth setup guide
- [Configuration Reference](configuration.md) - All environment variables
- [Scaling Guide](scale.md) - Multi-worker and Redis setup
- [Securing MCP Gateway](securing.md) - Security best practices
