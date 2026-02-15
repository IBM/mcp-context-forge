# Password Management & Recovery

This guide covers all supported password reset and account recovery paths for MCP Gateway administrators.

## Overview

MCP Gateway supports:

- Self-service password reset (`Forgot Password` flow)
- Admin-initiated password resets and account unlocks
- API-based password reset/unlock automation
- Emergency database-level recovery for full lockout scenarios

Password hashes use Argon2id.

## Self-Service Reset (Forgot Password)

### User flow

1. User opens login page: `/admin/login`
2. Selects **Forgot password?**
3. Submits email at `/admin/forgot-password`
4. Receives one-time reset link by email
5. Sets a new password at `/admin/reset-password/{token}`

### API endpoints

- `POST /auth/email/forgot-password`
- `GET /auth/email/reset-password/{token}`
- `POST /auth/email/reset-password/{token}`

Behavior:

- Reset tokens are one-time-use and hashed in DB
- Default token expiry: 60 minutes (`PASSWORD_RESET_TOKEN_EXPIRY_MINUTES`)
- Default rate limit: 5 requests / 15 minutes per email
- Forgot-password responses are generic to reduce account enumeration

### If SMTP/email is not configured

When `SMTP_ENABLED=false` (default), forgot-password requests are still accepted and
reset tokens are still generated, but no email is delivered.

In this mode, recovery options are:

1. Use **Admin -> Users** to set a new password directly.
2. Use admin API `PUT /auth/email/admin/users/{email}` to set a new password.
3. For break-glass scenarios, use the database recovery steps below.

## Admin UI Reset & Unlock

Navigate to `Admin -> Users` (`/admin/#users`):

- **Edit** user and set a new password
- View lockout state (`failed attempts`, `locked until`)
- Click **Unlock** to clear lockout immediately

## API-Based Admin Reset & Unlock

### Reset user password

```bash
curl -X PUT "http://localhost:4444/auth/email/admin/users/user%40example.com" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "password": "NewUserPassword123!",
    "password_change_required": false
  }'
```

### Unlock user account

```bash
curl -X POST "http://localhost:4444/auth/email/admin/users/user%40example.com/unlock" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Kubernetes / Helm Recovery

### Method 1: Helm bootstrap password update

```yaml
# values.yaml
mcpContextForge:
  secret:
    PLATFORM_ADMIN_PASSWORD: "NewSecurePassword123!"
```

```bash
helm upgrade mcp-stack . -f values.yaml -n mcp-private
kubectl rollout status deployment/mcp-context-forge -n mcp-private
```

### Method 2: Direct DB update

Generate hash inside gateway pod:

```bash
kubectl exec -n mcp-private -it deploy/mcp-context-forge -- \
  python -m mcpgateway.utils.hash_password
```

Apply hash in DB:

```sql
UPDATE email_users
SET password_hash = 'PASTE_HASH_HERE',
    password_change_required = false,
    failed_login_attempts = 0,
    locked_until = NULL,
    password_changed_at = CURRENT_TIMESTAMP
WHERE email = 'admin@example.com';
```

## Emergency Full Lockout Procedure

1. Access database with platform credentials.
2. Identify admin users:

```sql
SELECT email, is_admin, failed_login_attempts, locked_until
FROM email_users
WHERE is_admin = true;
```

3. Reset password hash + unlock fields (query above).
4. Validate login via `/admin/login`.
5. Document incident and rotate temporary credentials.

## Configuration

### Password reset controls

- `PASSWORD_RESET_ENABLED`
- `PASSWORD_RESET_TOKEN_EXPIRY_MINUTES`
- `PASSWORD_RESET_RATE_LIMIT`
- `PASSWORD_RESET_RATE_WINDOW_MINUTES`
- `PASSWORD_RESET_INVALIDATE_SESSIONS`
- `PASSWORD_RESET_MIN_RESPONSE_MS`

### SMTP notification controls

- `SMTP_ENABLED`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_FROM_NAME`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`
- `SMTP_TIMEOUT_SECONDS`

### Lockout controls

- `MAX_FAILED_LOGIN_ATTEMPTS`
- `ACCOUNT_LOCKOUT_DURATION_MINUTES`
- `ACCOUNT_LOCKOUT_NOTIFICATION_ENABLED`
