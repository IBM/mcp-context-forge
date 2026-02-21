# Backups

ContextForge stores its runtime state in a SQL database and optionally in Redis (for sessions and caching). This guide explains how to persist and restore that state safely.

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
curl -s -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
curl -s -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/prompts
```

You should see previously registered tools and templates.


---

## 🧬 Understanding the Database Schema

ContextForge uses a relational database (e.g. SQLite or PostgreSQL) to persist all registered entities and track tool/server usage. When session storage is configured as `CACHE_TYPE=database`, it also persists active user sessions and streamed message content.

---

### Key Tables

| Table | Purpose |
|-------|---------|
| `tools` | Stores registered tools, including schemas and auth configs |
| `tool_metrics` | Tracks execution stats per tool (latency, success/fail) |
| `resources` | Stores static or dynamic URI-based resources |
| `resource_metrics` | Logs usage of resources (access count, latency, etc.) |
| `resource_subscriptions` | Tracks SSE client subscriptions to resources |
| `prompts` | Jinja2 prompt templates with input arguments |
| `prompt_metrics` | Usage metrics for each prompt |
| `servers` | Virtual servers that group tools/resources under an SSE stream |
| `server_metrics` | Invocation stats per server |
| `gateways` | External federated MCP servers added by the admin |
| `mcp_sessions` | Persistent session registry when using `CACHE_TYPE=database` |
| `mcp_messages` | Persisted streamed content (text/image/etc.) tied to sessions |
| `*_association` tables | Many-to-many mapping between tools/resources/prompts and their servers/gateways |

---

### Session and Message Tables

These only appear when session/messaging backend is set to `database`:

- **`mcp_sessions`**: Each record is an open session ID (used for SSE streams and client context).
- **`mcp_messages`**: Stores streamed messages (text, image, resource) linked to a session-useful for debugging or offline playback.

You can query active sessions:

```sql
SELECT session_id, created_at FROM mcp_sessions ORDER BY created_at DESC;
```

Or inspect message content (JSON-encoded):

```sql
SELECT content FROM mcp_messages WHERE session_id = 'abc123';
```

---

These tables are cleaned automatically when session TTLs expire, but can also be purged manually if needed.
