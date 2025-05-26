# Management Overview

This section provides operational guidance for running and maintaining a production instance of MCP Gateway.

Whether you're self-hosting, running in the cloud, or deploying to Kubernetes, this section helps you monitor, back up, and maintain the system.

---

## 🧭 What’s Covered

| Page | Description |
|------|-------------|
| [Backups](backup.md) | How to persist and restore your database, configs, and resource state |
| [Logging](logging.md) | Configure structured logging, log destinations, and log rotation |

---

## 🔐 Runtime Config via `.env`

Most operational settings (logging level, database pool size, auth mode) are controlled through `.env` or environment variables.

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
