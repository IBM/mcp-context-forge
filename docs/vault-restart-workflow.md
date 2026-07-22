# Vault Restart Workflow

## Quick Reference

After restarting Vault, you need to set up your shell environment to use the new token.

### 1. Restart Vault

```bash
./scripts/restart-vault.sh
```

This script will:
- Stop any running Vault processes
- Backup existing OAuth tokens
- Recreate the Vault storage table
- Start Vault server
- Initialize and unseal Vault
- Create a fresh ContextForge token
- Update your `.env` file with the new token

### 2. Configure Your Current Shell

**Option A: Using the alias (recommended)**

If you have the `vault-auth` alias in your `~/.zshrc`:

```bash
vault-auth
```

**Option B: Manual setup**

```bash
source ~/.vault-config/vault-env.sh
```

### 3. Verify Vault Access

```bash
vault status
vault kv list secret
```

You should no longer see "permission denied" errors.

## Setting Up the Alias (One-time)

Add this to your `~/.zshrc` or `~/.bashrc`:

```bash
alias vault-auth='source ~/.vault-config/keys.txt && export VAULT_ADDR=http://127.0.0.1:8200 && export VAULT_TOKEN=$VAULT_CF_TOKEN'
alias vault-auth-root='source ~/.vault-config/keys.txt && export VAULT_ADDR=http://127.0.0.1:8200 && export VAULT_TOKEN=$VAULT_ROOT_TOKEN'
```

Then reload your shell config:

```bash
source ~/.zshrc  # or source ~/.bashrc
```

## Troubleshooting

### "Permission denied" errors

If you still get permission denied after running `vault-auth`, verify:

1. Your token is set correctly:
   ```bash
   echo $VAULT_TOKEN
   ```

2. The contextforge policy has the right permissions:
   ```bash
   vault-auth-root
   vault policy read contextforge
   ```

### Token not found in keys file

If the script fails to find your keys file, check:

```bash
ls -la ~/.vault-config/keys.txt
cat ~/.vault-config/keys.txt
```

The file should contain:
- `VAULT_UNSEAL_KEY`
- `VAULT_ROOT_TOKEN`
- `VAULT_CF_TOKEN`

## ContextForge Policy

The restart script creates a policy with these permissions:

```hcl
# Allow listing the root secret/ path
path "secret/metadata" {
  capabilities = ["list"]
}

# Allow listing contextforge/ and oauth/ directories
path "secret/metadata/contextforge" {
  capabilities = ["list"]
}

path "secret/metadata/contextforge/oauth" {
  capabilities = ["list"]
}

# Full access to OAuth tokens
path "secret/data/contextforge/oauth/*" {
  capabilities = ["create", "update", "read", "delete", "list"]
}

path "secret/metadata/contextforge/oauth/*" {
  capabilities = ["create", "update", "read", "delete", "list"]
}
```

## Important Files

| File | Purpose |
|------|---------|
| `~/.vault-config/keys.txt` | Contains Vault tokens (unseal, root, contextforge) |
| `~/.vault-config/vault-env.sh` | Source-able environment setup script |
| `~/.vault-config/config.hcl` | Vault server configuration |
| `/tmp/vault-server.log` | Vault server logs |
| `.env` | Project environment variables (auto-updated by restart script) |

## Recovery from Lost Tokens

If you lose your tokens but Vault is still running:

1. Check if you have a backup keys file:
   ```bash
   ls -lah ~/.vault-config/*.txt*
   ```

2. If Vault is sealed, you'll need to restart:
   ```bash
   ./scripts/restart-vault.sh
   ```

   **Warning:** This recreates the storage table, so any OAuth tokens will be lost and need re-authorization.
