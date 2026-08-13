# AUTH_ENCRYPTION_SECRET Upgrade Guide — 1.0.7 → 1.0.8

> **Scope:** This guide is for operators who ran ContextForge 1.0.7 with a weak
> `AUTH_ENCRYPTION_SECRET` (e.g. `my-test-salt`, `changeme`, or any value shorter
> than 32 characters) and are upgrading to 1.0.8.

---

## Why this matters

1.0.8 restores an unconditional startup guardrail: `AUTH_ENCRYPTION_SECRET` must be
≥ 32 chars, high-entropy, and not a known-weak value in **every** environment. If you
upgrade without following this guide, you will hit one or both of:

| Failure | Symptom |
|---------|---------|
| **Startup failure** | `SecurityConfigurationError: auth_encryption_secret: too short` — gateway refuses to start |
| **Silent decryption failure** | All stored OAuth tokens, SSO credentials, and gateway client secrets decrypt as garbage |

> ⚠️ **Do not start the 1.0.8 gateway before completing Step 5.**
> If you start it before re-encrypting the database, every stored credential becomes
> permanently unreadable.

---

## What gets re-encrypted

The migration script touches exactly these columns — everything else is untouched:

**EncryptionService path** (`v2:{...}` format — OAuth/SSO credentials):

| Table | Column(s) | Type |
|-------|-----------|------|
| `oauth_tokens` | `access_token`, `refresh_token` | Direct AES ciphertext |
| `registered_oauth_clients` | `client_secret_encrypted`, `registration_access_token_encrypted` | Direct AES ciphertext |
| `sso_providers` | `client_secret_encrypted` | Direct AES ciphertext |
| `gateways` | `oauth_config` | JSON — sensitive keys re-encrypted recursively |
| `a2a_server_auth` | `oauth_config` | JSON — sensitive keys re-encrypted recursively |
| `a2a_agent_auth` | `oauth_config` | JSON — sensitive keys re-encrypted recursively |

**services_auth path** (`base64url(nonce+ciphertext)` format — tool/agent/LLM credentials):

| Table | Column(s) | Type |
|-------|-----------|------|
| `tools` | `auth_value` | AES-GCM blob |
| `a2a_agents` | `auth_value`, `auth_query_params` | AES-GCM blob / JSON dict of blobs |
| `a2a_agent_auth` | `auth_value`, `auth_query_params` | AES-GCM blob / JSON dict of blobs |
| `gateways` | `auth_query_params` | JSON dict of AES-GCM blobs |
| `llm_providers` | `api_key` | AES-GCM blob |

Tables that don't exist (optional features not deployed) are silently skipped. NULL
values and plaintext values are also skipped. The script is **idempotent** — running
it twice is safe; already-migrated values are detected and skipped.

---

## Prerequisites

- Python environment with `uv` available (`uv --version`)
- Access to the configuration source your deployment reads from (`.env` file, Docker
  Compose environment block, Kubernetes Secret, Helm values, or your secret manager)
- Access to the database (`DATABASE_URL` — SQLite file path or PostgreSQL connection string)
- The exact current (weak) value of `AUTH_ENCRYPTION_SECRET` — retrieve it **before** stopping

---

## Upgrade sequence

### Step 0 — Record the old weak key

You need the exact old value as `--old-key` in Step 5. Find it now while the gateway
is still running — wherever your deployment stores it:

```bash
# .env file
grep AUTH_ENCRYPTION_SECRET .env

# Docker Compose (environment block or env_file)
# Check your compose override or the running container:
docker inspect <container-name> | grep AUTH_ENCRYPTION_SECRET

# Kubernetes Secret
kubectl get secret <secret-name> -o jsonpath='{.data.AUTH_ENCRYPTION_SECRET}' | base64 -d

# Helm values / secret manager
# Retrieve from your values-override.yaml or secrets manager UI
```

Write the value down — you will need it in Step 5.

> ⚠️ Once Step 3 sets a new value, the old one is no longer in your config source.

---

### Step 1 — Stop the gateway

No writes must happen to the database between key generation and migration.
Stop the gateway using whichever method your deployment uses:

```bash
# Docker Compose
docker compose down

# Kubernetes — scale the Deployment to zero replicas
kubectl scale deployment <mcpgateway-deployment> --replicas=0

# Helm
helm upgrade <release> <chart> --set replicaCount=0

# systemd
systemctl stop mcpgateway

# bare-metal gunicorn / uvicorn
kill -TERM $(pgrep -f gunicorn)
kill -TERM $(pgrep -f uvicorn)
```

---

### Step 2 — Get the 1.0.8 code

The migration script (`migrate_enc_secret.py`) is a **new file added in 1.0.8** — it
does not exist on 1.0.7. You need the 1.0.8 codebase available locally to run it,
regardless of how you deploy:

```bash
# git-based deployments
git pull origin main
# or
git checkout v1.0.8

# Docker / Kubernetes / Helm — pull the 1.0.8 image tag, but run the migration
# script from the repository checkout on any machine that has Python + uv and
# can reach the database before the new image is deployed.
```

---

### Step 3 — Generate a new strong key

`make init-secrets` generates a fresh set of secrets and writes them to `.env.secrets`
for review. `AUTH_ENCRYPTION_SECRET` is **not** patched in-place because rotating it
requires migrating the database first — that is what Step 5 does.

```bash
make init-secrets
```

Read the generated value from `.env.secrets`:

```bash
grep AUTH_ENCRYPTION_SECRET .env.secrets
# AUTH_ENCRYPTION_SECRET=<43-char URL-safe base64 token>
```

Then set it in whichever configuration source your deployment reads from — `.env`,
a Docker secret, a Kubernetes Secret, Helm `values-override.yaml`, or your secret
manager. The value must be in place **before** you run Step 5.

```bash
# .env (bare-metal / local)
sed -i 's/^AUTH_ENCRYPTION_SECRET=.*/AUTH_ENCRYPTION_SECRET=<new-value>/' .env

# Docker Compose (if using environment: block directly)
# Update the AUTH_ENCRYPTION_SECRET line in your compose override file

# Kubernetes / Helm
# kubectl create secret generic mcpgateway-secrets \
#   --from-literal=AUTH_ENCRYPTION_SECRET=<new-value> --dry-run=client -o yaml | kubectl apply -f -
```

> 📋 Note the new value — you will pass it as `--new-key` in Step 5.

---

### Step 4 — Dry-run the migration *(recommended)*

Reads every affected row and reports what would be re-encrypted. No writes are made.

```bash
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <old-weak-key> \
    --new-key <new-strong-key> \
    --dry-run
```

Expected output:

```
============================================================
DRY RUN SUMMARY (no changes written):
  Rows scanned  : 12
  Values migrated: 8
  Values skipped : 4
  Errors         : 0
============================================================
```

> ❌ **If `Errors > 0`:** some rows are encrypted with a key that is neither
> `--old-key` nor `--new-key` (a third key from a previous rotation). Stop and
> investigate before proceeding — do not run the live migration until errors are 0.

---

### Step 5 — Run the live migration

Re-encrypts all affected rows under the new key in a single database transaction.
The transaction is rolled back automatically if any row fails — the database is
always left in its original state on failure.

```bash
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <old-weak-key> \
    --new-key <new-strong-key>
```

**Non-default database URL (PostgreSQL etc.):**

```bash
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <old-weak-key> \
    --new-key <new-strong-key> \
    --database-url postgresql+psycopg://user:pass@host/dbname
```

**Environment variable fallback (useful in CI / secret managers):**

```bash
OLD_AUTH_ENCRYPTION_SECRET=<old> \
NEW_AUTH_ENCRYPTION_SECRET=<new> \
    uv run python3 -m mcpgateway.scripts.migrate_enc_secret
```

Expected output on success:

```
============================================================
MIGRATION SUMMARY:
  Rows scanned  : 12
  Values migrated: 8
  Values skipped : 4
  Errors         : 0
============================================================

✅  Migration complete — 8 value(s) re-encrypted successfully.
```

| Exit code | Meaning |
|-----------|---------|
| `0` | All rows migrated (or nothing to migrate). Proceed to Step 6. |
| `1` | One or more rows failed. Transaction rolled back. Check stderr before retrying. |

---

### Step 6 — Start the gateway

The guardrail now passes (strong key in your config) and all database rows are
encrypted under the new key. Start the gateway using whichever method your
deployment uses:

```bash
# Docker Compose
docker compose up -d

# Kubernetes — restore replicas
kubectl scale deployment <mcpgateway-deployment> --replicas=<original-count>

# Helm
helm upgrade <release> <chart> --set replicaCount=<original-count>
# or roll out the 1.0.8 image with the new secret value:
helm upgrade <release> <chart> -f values-override.yaml

# systemd
systemctl start mcpgateway

# bare-metal development
make dev

# bare-metal production
make serve
```

**Expected result:** no `SecurityConfigurationError` in startup logs. Verify
credentials work by authenticating via the gateway and confirming SSO / OAuth flows
succeed.

---

## Full sequence at a glance

| # | Action | Code version | Gateway state |
|---|--------|-------------|---------------|
| 0 | Record old weak key | 1.0.7 | Running (read only) |
| 1 | Stop gateway | 1.0.7 | **Stopped** |
| 2 | Pull 1.0.8 code | **1.0.8** | Stopped |
| 3 | `make init-secrets` → set `AUTH_ENCRYPTION_SECRET` in your config source | 1.0.8 | Stopped |
| 4 | `migrate_enc_secret --dry-run` | 1.0.8 | Stopped |
| 5 | `migrate_enc_secret` (live run) | 1.0.8 | Stopped |
| 6 | Start gateway | 1.0.8 | **Running** |

---

## Special cases

### Never had any OAuth tokens / SSO / gateways with credentials

The dry-run will report `Rows scanned: 0, Values migrated: 0`. Still run the live
migration (Step 5) to confirm exit 0, but it is a no-op. Steps 3 and 6 are the only
ones that matter for you.

### Helm / Kubernetes deployments

`charts/mcp-stack/values.yaml` now ships with `AUTH_ENCRYPTION_SECRET: ""` (must be
set explicitly). Provide the new strong value via your `values-override.yaml` or a
Kubernetes Secret, then run the migration as a pre-upgrade Job or init container
**before** the gateway Deployment rolls over to 1.0.8.

### `MIN_SECRET_LENGTH` raised above 32

If you have `MIN_SECRET_LENGTH=64` set in your configuration, `make init-secrets` will
generate a token of ≥ 64 chars (the script respects the configured floor). Set that
full value in your config source and pass it as `--new-key`. The migration script
validates `--new-key` against the absolute 32-char minimum only — the gateway will
re-apply the higher floor at startup.

### If you already started 1.0.8 with the wrong key

> ❌ **This is a data-loss scenario.** Any row written by the 1.0.8 gateway after it
> started is encrypted under the new key. Any row still encrypted under the old key
> is now unreadable by the running gateway. You need to identify which rows each key
> owns before re-running the migration. Use `--dry-run` with both key orders to see
> the error counts, then contact the team before proceeding.

---

## Troubleshooting

| Error message | Cause | Fix |
|---------------|-------|-----|
| `SecurityConfigurationError: auth_encryption_secret: too short` | Gateway started before generating a strong key | Stop gateway. Run Step 3, then Step 5, then restart. |
| `❌ --new-key is too short` | Weak value passed as `--new-key` | Generate a strong value (see Step 3), pass it as `--new-key`. |
| `❌ --old-key and --new-key are identical` | Both arguments have the same value | Verify you are using the old key as `--old-key` and the newly generated value as `--new-key`. |
| `Errors: N` in dry-run output | Some rows encrypted with a third key | Identify previous key rotation history; re-run with the correct `--old-key` for each batch. |
| `AUTH_ENCRYPTION_SECRET: shell environment holds a weak/non-compliant value…` | `AUTH_ENCRYPTION_SECRET=changeme` exported in shell, strong value already in `.env` | Run `unset AUTH_ENCRYPTION_SECRET`, then retry. |
| OAuth flows break after upgrade | Migration ran with wrong `--old-key`; rows not actually re-encrypted | Confirm exit code was `0` and `Values migrated > 0`. Re-run migration with correct keys. |
| Tool / agent / LLM auth fails after upgrade | `services_auth` blobs not re-encrypted (separate path from OAuth) | Same fix — re-run migration with correct `--old-key`; confirm `Values migrated > 0` for those tables. |
