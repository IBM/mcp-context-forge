# Troubleshooting

This guide covers common issues and their solutions when running ContextForge.

---

## macOS: SQLite "disk I/O error"

If the gateway fails on macOS with `sqlite3.OperationalError: disk I/O error` (works on Linux/Docker), it's usually a filesystem/locking quirk rather than a schema bug.

### Quick Fixes

**Avoid iCloud-synced directories:**

- Don't clone/run the repo under `~/Documents` or `~/Desktop` if iCloud "Desktop & Documents" sync is enabled
- Use a project folder directly under your home directory:

```bash
mkdir -p "$HOME/mcp-context-forge" && cd "$HOME/mcp-context-forge"
```

**Use a safe, local APFS path for SQLite:**

Avoid iCloud/Dropbox/OneDrive/Google Drive, network shares, or external exFAT/NAS.

=== "Application Support"
    ```bash
    mkdir -p "$HOME/Library/Application Support/mcpgateway"
    export DATABASE_URL="sqlite:////Users/$USER/Library/Application Support/mcpgateway/mcp.db"
    ```

=== "Project Local"
    ```bash
    mkdir -p "$HOME/mcp-context-forge/data"
    export DATABASE_URL="sqlite:////Users/$USER/mcp-context-forge/data/mcp.db"
    ```

### Additional Steps

**Clean stale SQLite artifacts after any crash:**

```bash
pkill -f mcpgateway || true && rm -f mcp.db-wal mcp.db-shm mcp.db-journal
```

**Reduce startup concurrency:**

```bash
GUNICORN_WORKERS=1 make serve  # or use `make dev` which runs single-process
```

**Run the diagnostic helper:**

```bash
python3 scripts/test_sqlite.py --verbose
```

**Lower pool pressure while debugging:**

```bash
DB_POOL_SIZE=10 DB_MAX_OVERFLOW=0 DB_POOL_TIMEOUT=60 DB_MAX_RETRIES=10 DB_RETRY_INTERVAL_MS=5000
```

**Disable file-lock leader path (temporary):**

```bash
export CACHE_TYPE=none
```

**Update SQLite and ensure Python links against it:**

```bash
brew install sqlite3 && brew link --force sqlite3
brew install python3 && /opt/homebrew/bin/python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

---

## WSL2: Port Publishing Issues

When using rootless Podman or Docker Desktop on WSL2, you may encounter port publishing issues.

### Diagnose the Listener

```bash
# Inside your WSL distro
ss -tlnp | grep 4444        # Use ss
netstat -anp | grep 4444    # or netstat
```

!!! info "IPv6 Wildcard"
    Seeing `:::4444 LISTEN rootlessport` is normal - the IPv6 wildcard socket (`::`) also accepts IPv4 traffic when `net.ipv6.bindv6only = 0` (default on Linux).

### Why localhost Fails on Windows

WSL 2's NAT layer rewrites only the *IPv6* side of the dual-stack listener. From Windows, `http://127.0.0.1:4444` (or Docker Desktop's "localhost") therefore times out.

### Fix for Podman Rootless

```bash
# Inside the WSL distro
echo "wsl" | sudo tee /etc/containers/podman-machine
systemctl --user restart podman.socket
```

`ss` should now show `0.0.0.0:4444` instead of `:::4444`, and the service becomes reachable from Windows *and* the LAN.

### Fix for Docker Desktop (> 4.19)

Docker Desktop adds a "WSL integration" switch per-distro. Turn it **on** for your distro, restart Docker Desktop, then restart the container:

```bash
docker restart mcpgateway
```

---

## Gateway Exits Immediately

**Error:** "Failed to read DATABASE_URL" or similar startup failures.

**Solution:** Copy `.env.example` to `.env` and configure required variables:

```bash
cp .env.example .env
```

Then edit `DATABASE_URL`, `JWT_SECRET_KEY`, `BASIC_AUTH_PASSWORD`, etc. Missing or empty required vars cause a fast-fail at startup.

See the [Configuration Reference](./configuration.md) for all available options.

---

## PostgreSQL: `ModuleNotFoundError: No module named 'psycopg2'`

If the gateway fails at startup with `ModuleNotFoundError: No module named 'psycopg2'`, your `DATABASE_URL` is using the wrong SQLAlchemy driver dialect.

ContextForge ships with [psycopg 3](https://www.psycopg.org/psycopg3/) (`psycopg`), the modern PostgreSQL adapter. However, SQLAlchemy's default `postgresql://` scheme loads the **deprecated** `psycopg2` driver, which is not installed.

### Fix

Change your `DATABASE_URL` to use the `postgresql+psycopg://` scheme:

```bash
# Wrong — triggers psycopg2 import
DATABASE_URL=postgresql://user:pass@localhost:5432/mydb

# Correct — uses the installed psycopg (v3) driver
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/mydb
```

The `+psycopg` suffix tells SQLAlchemy to use the psycopg 3 dialect instead of the legacy psycopg2 dialect. See the [SQLAlchemy Engine Configuration](https://docs.sqlalchemy.org/en/20/core/engines.html) and [PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/core/engines.html#postgresql) documentation for details on database URL schemes.

!!! tip
    If you also see `postgres://` (without the `ql`), note that SQLAlchemy requires the full `postgresql` prefix. Some providers (e.g., Heroku) supply URLs starting with `postgres://` — these need to be rewritten to `postgresql+psycopg://`.

---

## Team Member Limit Exceeded

If you see an error such as `"Team has reached maximum member limit of 100"` when adding members or sending invitations, the team has hit its membership cap.

Each team has a `max_members` value. When `max_members` is `null` (the default for new teams), the global `MAX_MEMBERS_PER_TEAM` setting is used at check time (default: **100**). The limit applies to active members plus pending invitations.

### Fix

Increase the global default by setting `MAX_MEMBERS_PER_TEAM` in your environment. This takes effect immediately for all teams that do not have an explicit per-team override:

```bash
# .env
MAX_MEMBERS_PER_TEAM=500
```

Alternatively, set an explicit per-team limit via the Admin API:

```bash
curl -X PUT http://localhost:4444/teams/{team_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_members": 500}'
```

To revert a team to the global default, clear its per-team override:

```bash
curl -X PUT http://localhost:4444/teams/{team_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_members": null}'
```

See the [Configuration Reference](./configuration.md) for all team-related settings.

---

## Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: mcpgateway` | Run `make install-dev` or `pip install -e .` |
| Port already in use | Check for existing processes: `lsof -i :4444` |
| Authentication failures | Verify `JWT_SECRET_KEY` matches token generation |
| Database locked | Reduce workers: `GUNICORN_WORKERS=1` |
| SSL certificate errors | Generate certs: `make certs` |

---

## Getting Help

- **[GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)** — Report bugs or request features
- **[Discussions](https://github.com/IBM/mcp-context-forge/discussions)** — Ask questions and share ideas
- **[API Usage Guide](./api-usage.md)** — Comprehensive API examples
