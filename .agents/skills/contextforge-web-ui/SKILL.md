---
name: contextforge-web-ui
description: Run or configure the ContextForge Web UI (`web_ui` service, `--profile ui`, `WEB_UI_*` variables in `docker-compose.yml` and `.env.example`). Not for the built-in Admin UI.
---

# ContextForge Web UI

A BFF-style frontend for the gateway API. It is separate from the built-in Admin UI (`MCPGATEWAY_UI_ENABLED`). Source and docs: https://github.com/contextforge-org/contextforge-web-ui

- Runs as `web_ui` plus a dedicated `web_ui_redis` session store in `docker-compose.yml`.
- Enabled with `--profile ui`. `--profile testing` also pulls it in.
- `web_ui` waits until `gateway` and `web_ui_redis` are healthy.

```bash
# Start the gateway plus the web UI
docker compose --profile ui up -d

# Access
open http://localhost:${WEB_UI_PORT:-3001}
```

Configuration (see the commented `WEB_UI_*` block in `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEB_UI_IMAGE` | see `docker-compose.yml` | Image to pull. Pinned to a specific released version *and* digest, never `latest`. The release checklist bumps it (`docs/docs/development/release-management.md`). Keep the value in `docker-compose.yml` only, so copies cannot drift. |
| `WEB_UI_PORT` | `3001` | Host **and** container port. The image reads `PORT` at startup, so both sides of the mapping stay in sync. |
| `WEB_UI_HOST` | `0.0.0.0` | Bind address inside the container. Keep `0.0.0.0` in Docker. |
| `WEB_UI_CONTEXTFORGE_URL` | `http://gateway:4444` | Gateway API base URL the UI talks to (internal compose network). |
| `WEB_UI_COOKIE_SECURE` | `false` | Set `true` once the UI is served over HTTPS. |
| `WEB_UI_REDIS_URL` | `redis://web_ui_redis:6379/0` | Session store, separate from the gateway's cache `redis` service. |

For feature docs, auth flow details, and upstream options beyond this compose file, see the [contextforge-web-ui repo](https://github.com/contextforge-org/contextforge-web-ui).
