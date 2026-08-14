# AUTH_ENCRYPTION_SECRET Secrets Rotation Guide — 1.0.7 → 1.0.8

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
> If you start it before rotating the database, every stored credential becomes
> permanently unreadable.

---

## What gets re-encrypted

The rotation script touches exactly these columns — everything else is untouched:

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
it twice is safe; already-rotated values are detected and skipped.

---

## Prerequisites

- Python environment with `uv` available (`uv --version`)
- Access to the configuration source your deployment reads from (`.env` file, Docker
  Compose environment block, Kubernetes Secret, Helm values, or your secret manager)
- Access to the database (`DATABASE_URL` — SQLite file path or PostgreSQL connection string)
- The exact current (weak) value of `AUTH_ENCRYPTION_SECRET` — retrieve it **before** stopping

---

## Rotation sequence

### Step 0 — Back up the database and record the old weak key

Do both of these while the gateway is still running and the database is in a
consistent state.

#### Back up the database

> 💡 Take a backup using whatever method fits your deployment (file copy, database
> dump, snapshot, etc.) before making any changes. This is your safety net — if
> anything goes wrong during rotation you can restore and retry with the correct keys.
> Keep the backup until you have confirmed the rotated gateway starts and all
> OAuth / SSO / tool auth flows work correctly.

#### Record the old weak key

Record the current value of `AUTH_ENCRYPTION_SECRET` from wherever your deployment
stores it (`.env`, Docker/Kubernetes secret, Helm values, secret manager, etc.).
You will need it as `--old-key` in Step 5.

> ⚠️ Once Step 3 sets a new value, the old one is no longer in your config source.
> See the [Appendix](#appendix--deployment-specific-rotation-commands) for
> deployment-specific retrieval commands.

---

### Step 1 — Stop the gateway

No writes must happen to the database between key generation and rotation.
Stop the gateway using whichever method your deployment uses. See the
[Appendix](#appendix--deployment-specific-rotation-commands) for
deployment-specific commands.

---

### Step 2 — Get the 1.0.8 code

The rotation script (`migrate_enc_secret.py`) is a **new file added in 1.0.8** — it
does not exist on 1.0.7. You need the 1.0.8 codebase (or package) available to run
it, regardless of how you deploy.

For git-based deployments: `git pull origin main` or `git checkout v1.0.8`.
For Docker / Kubernetes / Helm: run the script from a local checkout or
`pip install mcp-contextforge-gateway==1.0.8` on any machine that can reach the
database, before the new image is deployed.

---

### Step 3 — Generate a new strong key

Generate a strong new `AUTH_ENCRYPTION_SECRET` (≥ 32 chars, high-entropy) and set it
in your config source. The value must be in place **before** you run Step 5 — the
script reads it as `--new-key`.

For repository-based deployments, `make init-secrets` generates a ready-to-use value
in `.env.secrets`. For package consumers or environments without `make`, generate one
with Python: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

> 📋 Note the new value — you will pass it as `--new-key` in Step 5.
> See the [Appendix](#appendix--deployment-specific-rotation-commands) for how to
> set the value in each deployment type.

---

### Step 4 — Dry-run the rotation *(recommended)*

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
> investigate before proceeding — do not run the live rotation until errors are 0.

---

### Step 5 — Run the live rotation

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
ROTATION SUMMARY:
  Rows scanned  : 12
  Values migrated: 8
  Values skipped : 4
  Errors         : 0
============================================================

✅  Rotation complete — 8 value(s) re-encrypted successfully.
```

| Exit code | Meaning |
|-----------|---------|
| `0` | All rows rotated (or nothing to rotate). Proceed to Step 6. |
| `1` | One or more rows failed. Transaction rolled back. Check stderr before retrying. |

---

### Step 6 — Start the gateway

The guardrail now passes (strong key in your config) and all database rows are
encrypted under the new key. Start the gateway using whichever method your
deployment uses. See the [Appendix](#appendix--deployment-specific-rotation-commands)
for deployment-specific commands.

**Expected result:** no `SecurityConfigurationError` in startup logs. Verify
credentials work by authenticating via the gateway and confirming SSO / OAuth flows
succeed.

---

## Full sequence at a glance

| # | Action | Code version | Gateway state |
|---|--------|-------------|---------------|
| 0 | Back up database + record old weak key | 1.0.7 | Running (read only) |
| 1 | Stop gateway | 1.0.7 | **Stopped** |
| 2 | Pull 1.0.8 code | **1.0.8** | Stopped |
| 3 | `make init-secrets` → set `AUTH_ENCRYPTION_SECRET` in your config source | 1.0.8 | Stopped |
| 4 | `migrate_enc_secret --dry-run` | 1.0.8 | Stopped |
| 5 | `migrate_enc_secret` (live rotation) | 1.0.8 | Stopped |
| 6 | Start gateway | 1.0.8 | **Running** |

---

## Using ContextForge as a Python package

If you embed ContextForge in your own application via `pip install mcp-contextforge-gateway`
rather than running the server directly, the rotation script is still available as a
module and can be driven programmatically or from a plain `python` invocation — no
`uv`, `make`, or repository checkout required.

### Why this path is different

When installed as a package:

- `uv` and `make` are not available (they are dev tools, not runtime dependencies).
- The `.env` file convention does not apply — your application owns the configuration surface.
- You generate strong secrets with Python's `secrets` module rather than `make init-secrets`.
- The rotation script is invoked either as a CLI entry-point or imported directly.

### Step-by-step for package consumers

**1. Generate a strong new key in Python:**

```python
import secrets
new_key = secrets.token_urlsafe(32)   # 43-char URL-safe base64 string
print(new_key)
```

Store the output wherever your application reads `AUTH_ENCRYPTION_SECRET` from —
an environment variable, a secrets manager (HashiCorp Vault, AWS Secrets Manager,
IBM Key Protect), or an injected config file. Keep the old key available until
Step 3 completes.

**2. Dry-run via the installed entry-point:**

```bash
# If mcp-contextforge-gateway is installed in the active environment:
python -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_AUTH_ENCRYPTION_SECRET" \
    --new-key "$NEW_AUTH_ENCRYPTION_SECRET" \
    --database-url "$DATABASE_URL" \
    --dry-run
```

**3. Run the live rotation:**

```bash
python -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_AUTH_ENCRYPTION_SECRET" \
    --new-key "$NEW_AUTH_ENCRYPTION_SECRET" \
    --database-url "$DATABASE_URL"
```

**4. Invoke programmatically from your own code:**

```python
import sys
from mcpgateway.scripts.migrate_enc_secret import main

sys.argv = [
    "migrate_enc_secret",
    "--old-key", old_key,
    "--new-key", new_key,
    "--database-url", database_url,
]
main()   # raises SystemExit(0) on success, SystemExit(1) on failure
```

Or, to capture the result without raising:

```python
import subprocess, sys

result = subprocess.run(
    [
        sys.executable, "-m", "mcpgateway.scripts.migrate_enc_secret",
        "--old-key", old_key,
        "--new-key", new_key,
        "--database-url", database_url,
    ],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    raise RuntimeError(f"Secret rotation failed:\n{result.stderr}")
```

**5. Update your application config and restart:**

After a `returncode == 0`, update `AUTH_ENCRYPTION_SECRET` to the new value in
whatever config surface your app uses, then restart the gateway process.

### Using environment variables instead of CLI flags

The script reads `OLD_AUTH_ENCRYPTION_SECRET` and `NEW_AUTH_ENCRYPTION_SECRET` from
the environment if the corresponding CLI flags are not passed — convenient when your
secrets manager injects environment variables at runtime:

```python
import os, subprocess, sys

os.environ["OLD_AUTH_ENCRYPTION_SECRET"] = old_key
os.environ["NEW_AUTH_ENCRYPTION_SECRET"] = new_key
os.environ["DATABASE_URL"] = database_url

result = subprocess.run(
    [sys.executable, "-m", "mcpgateway.scripts.migrate_enc_secret"],
    capture_output=True,
    text=True,
)
```

> ⚠️ Clear `OLD_AUTH_ENCRYPTION_SECRET` from the environment after the rotation
> completes — it is a live credential.

---

## Special cases

### Never had any OAuth tokens / SSO / gateways with credentials

The dry-run will report `Rows scanned: 0, Values migrated: 0`. Still run the live
rotation (Step 5) to confirm exit 0, but it is a no-op. Steps 3 and 6 are the only
ones that matter for you.

### Helm / Kubernetes deployments

`charts/mcp-stack/values.yaml` now ships with `AUTH_ENCRYPTION_SECRET: ""` (must be
set explicitly). Provide the new strong value via your `values-override.yaml` or a
Kubernetes Secret, then run the rotation as a pre-upgrade Job or init container
**before** the gateway Deployment rolls over to 1.0.8.

### `MIN_SECRET_LENGTH` raised above 32

If you have `MIN_SECRET_LENGTH=64` set in your configuration, `make init-secrets` will
generate a token of ≥ 64 chars (the script respects the configured floor). Set that
full value in your config source and pass it as `--new-key`. The rotation script
validates `--new-key` against the absolute 32-char minimum only — the gateway will
re-apply the higher floor at startup.

### If you already started 1.0.8 with the wrong key

> ❌ **This is a data-loss scenario.** Any row written by the 1.0.8 gateway after it
> started is encrypted under the new key. Any row still encrypted under the old key
> is now unreadable by the running gateway. You need to identify which rows each key
> owns before re-running the rotation. Use `--dry-run` with both key orders to see
> the error counts, then contact the team before proceeding.

### Rolling back to a previous (weaker) key — `--force`

> ⚠️ **Use only when you intentionally need to decrypt back to a key that does not
> meet the strength requirements** (e.g. reverting a key rotation in a test
> environment, or undoing a rotation before re-doing it with a different key).
> After a `--force` rollback the database will contain credentials encrypted under a
> weak key.  **Do not start the 1.0.8 gateway with a weak
> `AUTH_ENCRYPTION_SECRET`** — it will refuse to start.

By default the script rejects `--new-key` values that are too short, known-weak, or
low-entropy — the same guardrail the gateway enforces at startup.  Pass `--force` to
bypass all three checks:

```bash
# Roll back from a strong key to a previously-used weak key
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <current-strong-key> \
    --new-key <previous-weak-key> \
    --force

# Re-encrypt in the opposite direction again (back to strong) — --force not needed
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <previous-weak-key> \
    --new-key <current-strong-key>
```

`--force` also works when **both** keys are weak (e.g. re-keying between two legacy
short keys):

```bash
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <weak-key-a> \
    --new-key <weak-key-b> \
    --force
```

A warning is always printed to stderr when `--force` is active:

```
⚠️   --force: new-key strength validation skipped
```

`--force` can be combined with `--dry-run` to preview what would be re-encrypted
before committing:

```bash
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key <strong-key> \
    --new-key <weak-key> \
    --force \
    --dry-run
```

---

## Troubleshooting

| Error message | Cause | Fix |
|---------------|-------|-----|
| `SecurityConfigurationError: auth_encryption_secret: too short` | Gateway started before generating a strong key | Stop gateway. Run Step 3, then Step 5, then restart. |
| `❌ --new-key is too short` | Weak value passed as `--new-key` | Generate a strong value (see Step 3), pass it as `--new-key`. Or pass `--force` if a weak target key is intentional (rollback scenario). |
| `❌ --old-key and --new-key are identical` | Both arguments have the same value | Verify you are using the old key as `--old-key` and the newly generated value as `--new-key`. |
| `Errors: N` in dry-run output | Some rows encrypted with a third key | Identify previous key rotation history; re-run with the correct `--old-key` for each batch. |
| `AUTH_ENCRYPTION_SECRET: shell environment holds a weak/non-compliant value…` | `AUTH_ENCRYPTION_SECRET=changeme` exported in shell, strong value already in `.env` | Run `unset AUTH_ENCRYPTION_SECRET`, then retry. |
| OAuth flows break after upgrade | Rotation ran with wrong `--old-key`; rows not actually re-encrypted | Confirm exit code was `0` and `Values migrated > 0`. Re-run rotation with correct keys. |
| Tool / agent / LLM auth fails after upgrade | `services_auth` blobs not re-encrypted (separate path from OAuth) | Same fix — re-run rotation with correct `--old-key`; confirm `Values migrated > 0` for those tables. |

---

## Appendix — Deployment-specific rotation commands

Self-contained command sequences for each deployment type. Substitute
`<old-key>`, `<new-key>`, and `<new-strong-value>` with your actual values before
running.

---

### Docker Compose

```bash
# 0. Record the old key
OLD_KEY=$(docker inspect mcpgateway | python3 -c \
  "import sys,json; envs=json.load(sys.stdin)[0]['Config']['Env']; \
   print(next(e.split('=',1)[1] for e in envs if e.startswith('AUTH_ENCRYPTION_SECRET=')))")

# 1. Stop
docker compose down

# 2. Pull 1.0.8 code
git pull origin main

# 3. Generate a new strong key and update compose config
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# Edit docker-compose.override.yml or .env to set AUTH_ENCRYPTION_SECRET=$NEW_KEY

# 4. Dry-run
DATABASE_URL=<your-database-url> \
  docker run --rm \
    -e OLD_AUTH_ENCRYPTION_SECRET="$OLD_KEY" \
    -e NEW_AUTH_ENCRYPTION_SECRET="$NEW_KEY" \
    -e DATABASE_URL=<your-database-url> \
    --network host \
    icr.io/contextforge/mcp-context-forge:1.0.8 \
    python -m mcpgateway.scripts.migrate_enc_secret --dry-run

# 4a. (Alternative) Run from local checkout instead of image:
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" --new-key "$NEW_KEY" --dry-run

# 5. Live rotation
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY"

# 6. Start
docker compose up -d
```

---

### Kubernetes (kubectl)

```bash
# 0. Record the old key from the Secret
OLD_KEY=$(kubectl get secret mcpgateway-secrets \
  -o jsonpath='{.data.AUTH_ENCRYPTION_SECRET}' | base64 -d)

# 1. Stop — scale to zero
kubectl scale deployment mcpgateway --replicas=0
kubectl rollout status deployment/mcpgateway   # wait for scale-down

# 2. (on a machine with Python + the 1.0.8 source or package)
git pull origin main   # or: pip install "mcp-contextforge-gateway==1.0.8"

# 3. Generate a new key and patch the Secret
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
kubectl create secret generic mcpgateway-secrets \
  --from-literal=AUTH_ENCRYPTION_SECRET="$NEW_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Dry-run (connect to DB via port-forward or from a pod with DB access)
kubectl port-forward svc/postgres 5432:5432 &
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "postgresql+psycopg://user:pass@localhost:5432/mcpgateway" \
    --dry-run

# 5. Live rotation
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "postgresql+psycopg://user:pass@localhost:5432/mcpgateway"

# 6. Restore replicas
kubectl scale deployment mcpgateway --replicas=2
kubectl rollout status deployment/mcpgateway
```

---

### Helm

```bash
# 0. Record the old key
OLD_KEY=$(kubectl get secret mcpgateway-secrets \
  -o jsonpath='{.data.AUTH_ENCRYPTION_SECRET}' | base64 -d)

# 1. Scale to zero via Helm
helm upgrade mcpgateway ./charts/mcp-stack \
  --reuse-values \
  --set replicaCount=0

# 2. Pull 1.0.8 chart + app
git pull origin main

# 3. Generate a new key and write it to your values override
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# In values-override.yaml set:
#   auth:
#     encryptionSecret: "<new-key>"

# 4. Dry-run
kubectl port-forward svc/postgres 5432:5432 &
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "postgresql+psycopg://user:pass@localhost:5432/mcpgateway" \
    --dry-run

# 5. Live rotation
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "postgresql+psycopg://user:pass@localhost:5432/mcpgateway"

# 6. Roll out 1.0.8 with the new key
helm upgrade mcpgateway ./charts/mcp-stack -f values-override.yaml
```

---

### systemd (bare-metal)

```bash
# 0. Record the old key
OLD_KEY=$(grep AUTH_ENCRYPTION_SECRET /etc/mcpgateway/mcpgateway.env | cut -d= -f2-)

# 1. Stop the service
sudo systemctl stop mcpgateway

# 2. Pull 1.0.8 code
cd /opt/mcpgateway
git pull origin main

# 3. Generate a new key and update the environment file
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sudo sed -i "s|^AUTH_ENCRYPTION_SECRET=.*|AUTH_ENCRYPTION_SECRET=$NEW_KEY|" \
    /etc/mcpgateway/mcpgateway.env

# 4. Dry-run
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --dry-run

# 5. Live rotation
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY"

# 6. Start the service
sudo systemctl start mcpgateway
sudo systemctl status mcpgateway
```

---

### Python package (pip-installed)

```bash
# 0. Retrieve the old key from your secrets manager / environment
OLD_KEY="$AUTH_ENCRYPTION_SECRET"

# 1. Stop your application process (app-specific)

# 2. Install or upgrade to 1.0.8
pip install --upgrade "mcp-contextforge-gateway==1.0.8"

# 3. Generate a new strong key
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# Store NEW_KEY in your secrets manager / config before proceeding

# 4. Dry-run
python -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "$DATABASE_URL" \
    --dry-run

# 5. Live rotation
python -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "$DATABASE_URL"

# 6. Update AUTH_ENCRYPTION_SECRET to NEW_KEY in your config / secrets manager
#    and restart your application
```

**Programmatic rotation** (call from your own Python code):

```python
import secrets
import subprocess
import sys

old_key = "my-old-weak-secret"           # retrieved from your secrets manager
new_key = secrets.token_urlsafe(32)       # generate once, store immediately
database_url = "postgresql+psycopg://user:pass@host/dbname"

# Dry-run first
result = subprocess.run(
    [
        sys.executable, "-m", "mcpgateway.scripts.migrate_enc_secret",
        "--old-key", old_key,
        "--new-key", new_key,
        "--database-url", database_url,
        "--dry-run",
    ],
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.returncode != 0:
    raise RuntimeError(f"Dry-run failed:\n{result.stderr}")

# Live rotation
result = subprocess.run(
    [
        sys.executable, "-m", "mcpgateway.scripts.migrate_enc_secret",
        "--old-key", old_key,
        "--new-key", new_key,
        "--database-url", database_url,
    ],
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.returncode != 0:
    raise RuntimeError(f"Rotation failed:\n{result.stderr}")

# Update your config to use new_key, then restart the gateway
```

---

### Local development (SQLite + .env)

```bash
# 0. Record the old key
OLD_KEY=$(grep AUTH_ENCRYPTION_SECRET .env | cut -d= -f2-)

# 1. Stop the dev server (Ctrl-C or kill the process)

# 2. Pull 1.0.8 code
git pull origin main

# 3. Generate a new key and update .env
make init-secrets
NEW_KEY=$(grep AUTH_ENCRYPTION_SECRET .env.secrets | cut -d= -f2-)
sed -i "s|^AUTH_ENCRYPTION_SECRET=.*|AUTH_ENCRYPTION_SECRET=$NEW_KEY|" .env

# 4. Dry-run
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --dry-run

# 5. Live rotation
uv run python3 -m mcpgateway.scripts.migrate_enc_secret \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY"

# 6. Restart
make dev
```
