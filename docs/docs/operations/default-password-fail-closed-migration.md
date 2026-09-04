# Default Password Fail-Closed Migration

`BASIC_AUTH_PASSWORD`, `PLATFORM_ADMIN_PASSWORD`, and `DEFAULT_USER_PASSWORD` now
fail startup when they hold an empty, placeholder, or known-weak value (`changeme`
and similar) **and the authentication feature that consumes them is enabled**.
This document covers who is affected and how to migrate.

> ℹ️ This is the password-side counterpart to the `JWT_SECRET_KEY` /
> `AUTH_ENCRYPTION_SECRET` fail-closed enforcement. Unlike `AUTH_ENCRYPTION_SECRET`,
> no data is encrypted under these passwords — rotation is a simple config update
> and restart, no re-encryption script required. See
> [`AUTH_ENCRYPTION_SECRET` Rotation](auth-encryption-secret-rotation.md) if you
> also need to rotate that secret.

---

## Who is affected

The check is feature-gated: it only fires when the credential's consuming
authentication path is enabled.

| Credential | Fails startup when | Consuming feature |
|---|---|---|
| `BASIC_AUTH_PASSWORD` | `API_ALLOW_BASIC_AUTH=true` or `DOCS_ALLOW_BASIC_AUTH=true` | HTTP Basic Auth on the API or `/docs` |
| `PLATFORM_ADMIN_PASSWORD` | `EMAIL_AUTH_ENABLED=true` (the default) | Email/password authentication, platform-admin bootstrap |
| `DEFAULT_USER_PASSWORD` | `EMAIL_AUTH_ENABLED=true` (the default) | Email/password authentication, default password detection |

If the corresponding feature is disabled, the weak value is still accepted (with a
warning) — nothing changes for deployments that never enabled that path.

`EMAIL_AUTH_ENABLED` defaults to `true`, so most existing deployments are affected
by the `PLATFORM_ADMIN_PASSWORD` / `DEFAULT_USER_PASSWORD` checks even if they never
explicitly set that flag.

A value is rejected if it is:

- empty
- an unset placeholder (`__REPLACE_ME__...` or `ReplaceMe_...`)
- a known-weak value (`changeme`, `password`, `secret`, etc. — see `WEAK_VALUES` in
  `mcpgateway/_security_constants.py`)

---

## Migration steps

1. **Generate strong values** for every credential whose feature is enabled:

   ```bash
   # Repository checkout — patches .env in place, only touches weak/placeholder values
   make init-secrets-patch-env

   # Or generate values manually
   python3 -c "import secrets; print(secrets.token_urlsafe(18))"
   ```

2. **Set the values** in whichever configuration source your deployment reads:
   - `.env` file — patched automatically by `make init-secrets-patch-env`.
   - Docker Compose — set `BASIC_AUTH_PASSWORD`, `PLATFORM_ADMIN_PASSWORD`,
     `DEFAULT_USER_PASSWORD` in your `.env` or the compose environment block.
   - Helm / Kubernetes — update the `mcpContextForge.secret.PLATFORM_ADMIN_PASSWORD`
     / `DEFAULT_USER_PASSWORD` / `BASIC_AUTH_PASSWORD` values (or your Secret
     object) before rolling out the new image.

3. **Restart the gateway.** No database migration or re-encryption is required —
   the check runs once at startup against the configured value.

---

## Verifying the migration

Startup logs will show a `SecurityConfigurationError` naming the offending field if
a credential still needs attention, for example:

```
mcpgateway.config.SecurityConfigurationError: platform_admin_password: known-weak/default value rejected. Run 'python -m mcpgateway.scripts.init_secrets' to generate strong values, or use 'make init-secrets-patch-env' to write them directly into .env.
```

A clean startup with no `SecurityConfigurationError` for these fields confirms the
migration is complete.

---

## Rollback (not recommended)

Downgrading to a version without this check re-enables startup with a default
password if the consuming feature is on. This is a security regression — only use
it in isolated, non-production environments.

---

## Related documentation

- [Configuration Reference — Required: Change Before Use](../manage/configuration.md)
- [`AUTH_ENCRYPTION_SECRET` Rotation](auth-encryption-secret-rotation.md)
- `CHANGELOG.md` — Unreleased — Breaking Changes
