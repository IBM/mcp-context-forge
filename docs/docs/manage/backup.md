# Backups

MCP Gateway stores its runtime state in a SQL database and optionally in Redis (for sessions and caching). This guide explains how to persist and restore that state safely.

---

## 📦 What Needs to Be Backed Up

| Component | What It Contains |
|----------|------------------|
| Database (`mcp.db` or PostgreSQL) | All tools, prompts, resources, servers, metrics |
| `.env` file | Environment variables and secrets (e.g. JWT secret, DB URL) |
| Volume-mounted uploads (if any) | User-uploaded data or TLS certs |
| Redis (optional) | Session tokens, cached resources (only if using `CACHE_TYPE=redis`) |

---

## 💾 Backup Strategies

### For SQLite (default)

```bash
cp mcp.db backups/mcp-$(date +%F).db
```

### For PostgreSQL

```bash
pg_dump -U youruser -h yourhost -F c -f backups/mcp-$(date +%F).pgdump
```

You can also automate this via `cron` or a container sidecar.

---

## 🔁 Restore Instructions

### SQLite

```bash
cp backups/mcp-2024-05-10.db mcp.db
```

Restart the gateway afterward.

### PostgreSQL

```bash
pg_restore -U youruser -d mcp -h yourhost backups/mcp-2024-05-10.pgdump
```

---

## 🗃 Storing Secrets

Use a secrets manager (e.g., AWS Secrets Manager, Azure Key Vault, or Kubernetes Secrets) to manage `.env` contents securely in production.

---

## 🧪 Verify Your Backup

Run smoke tests:

```bash
curl http://localhost:4444/tools
curl http://localhost:4444/prompts
```

You should see previously registered tools and templates.
