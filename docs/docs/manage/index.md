# Management Overview

This section provides operational guidance for running and maintaining a production instance of MCP Gateway.

Whether you're self-hosting, running in the cloud, or deploying to Kubernetes, this section helps you monitor, back up, and maintain the system.

---

!!! tip "What's new in 0.9.0"
    Version v0.9.0 includes multi‑tenancy: email authentication, teams, RBAC, and resource visibility (private/team/public).

    - See the [Migration Guide](https://github.com/IBM/mcp-context-forge/blob/main/MIGRATION-0.7.0.md) and [Changelog](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md)
    - Quick enablement (excerpt): `EMAIL_AUTH_ENABLED=true`, `PLATFORM_ADMIN_EMAIL=...`, `AUTO_CREATE_PERSONAL_TEAMS=true`
    - Learn more: [Team Management](teams.md), [RBAC](rbac.md)

---

## 🧭 What's Covered

| Page | Description |
|------|-------------|
| [Configuration](configuration.md) | **Complete configuration reference** - databases, environment variables, and deployment settings |
| [Scaling Guide](scale.md) | 📈 **Production Scaling** - Horizontal/vertical scaling, Kubernetes HPA, connection pooling, and performance tuning |
| [Performance Tuning](tuning.md) | Optimize Gunicorn workers, database connections, and container resources |
| [Dynamic Client Registration](dcr.md) | 🔐 **OAuth2 DCR** - Automatic client provisioning for streamable HTTP servers |
| [Backups](backup.md) | How to persist and restore your database, configs, and resource state |
| [Export & Import](export-import.md) | Complete configuration management with CLI, API, and Admin UI |
| [Export/Import Tutorial](export-import-tutorial.md) | Step-by-step tutorial for getting started with export/import |
| [Export/Import Reference](export-import-reference.md) | Quick reference guide for export/import commands and APIs |
| [Bulk Import](bulk-import.md) | Import multiple tools at once for migrations and team onboarding |
| [Metadata Tracking](metadata-tracking.md) | 📊 **NEW** - Comprehensive audit trails and entity metadata tracking |
| [Well-Known URIs](well-known-uris.md) | Configure robots.txt, security.txt, and custom well-known files |
| [Logging](logging.md) | Configure structured logging, log destinations, and log rotation |

---

## 🔐 Runtime Config via `.env`

Most operational settings (logging level, database pool size, auth mode) are controlled through `.env` or environment variables.

!!! info "MariaDB & MySQL Fully Supported"
    MCP Gateway now has **complete MariaDB/MySQL support** alongside SQLite and PostgreSQL:

    - **36+ database tables** work perfectly with MariaDB 10.6+ and MySQL 8.0+
    - All **VARCHAR length issues** resolved for MariaDB/MySQL compatibility
    - Connection string: `DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp`
    - See [Configuration Reference](configuration.md) for complete setup instructions

Update the file and restart the container or process to apply changes.

---

## 🧪 Health & Readiness

Expose the `/health` endpoint for use with:

- Cloud load balancer health checks
- Kubernetes probes
- CI/CD smoke tests

Sample check:

```bash
curl http://localhost:4444/health
```

Expected response:

```json
{ "status": "healthy"}
```

---

## 🔁 Service Restart Commands

Depending on your environment:

* `docker restart mcpgateway`
* `kubectl rollout restart deployment/mcpgateway`
