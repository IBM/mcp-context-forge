# Admin UI

ContextForge includes a built-in Admin UI for managing all entities in real time via a web browser.

---

## 🖥️ Accessing the UI

After launching the gateway (`make serve` or `make podman-run`), open your browser and go to:

[http://localhost:4444/admin](http://localhost:4444/admin) - or the corresponding URL / port / protocol (ex: https when launching with `make podman-run-ssl`)

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444/admin`
    - Docker Compose (nginx proxy): `http://localhost:8080/admin`

Login using your `PLATFORM_ADMIN_EMAIL` and `PLATFORM_ADMIN_PASSWORD` credentials set in your `.env`.

---

## 🧭 UI Overview

The Admin UI is built with **HTMX**, **Alpine.js**, and **Tailwind CSS**, offering a dynamic, SPA-like experience without JavaScript bloat.

### Technology Stack

| Layer             | Technology         | Purpose                                                                 |
| ----------------- | ------------------ | ----------------------------------------------------------------------- |
| **Templating**    | Jinja2             | Server-side HTML rendering (44 templates in `mcpgateway/templates/`)    |
| **Interactivity** | HTMX 2.0.3         | AJAX without JavaScript, HTML-over-HTTP patterns (bundled via npm/Vite) |
| **Reactivity**    | Alpine.js 3.x      | Lightweight reactive components                                         |
| **Styling**       | Tailwind CSS       | Utility-first CSS framework                                             |
| **Code Editor**   | CodeMirror 5.65.18 | Syntax-highlighted editing                                              |
| **Charts**        | Chart.js           | Data visualization and metrics                                          |
| **Markdown**      | Marked.js          | Markdown rendering                                                      |
| **Security**      | DOMPurify          | XSS sanitization                                                        |
| **Icons**         | Font Awesome       | Icon library                                                            |

All Admin UI JavaScript vendor libraries are installed via npm and bundled/chunked with Vite. See [Air-Gapped Mode](#air-gapped-mode) below for offline deployment details.

It provides tabbed access to:

- **Servers Catalog**: Define or edit MCP servers (real or virtual)
- **Tools**: Register REST or native tools, configure auth/rate limits, test responses
- **Resources**: Add templated or static resources, set MIME types, enable caching
- **Prompts**: Define Jinja2 prompt templates with argument schemas and preview rendering
- **Gateways**: View and manage federated peers, toggle activity status
- **Roots**: Register root URIs for agent or resource scoping
- **Metrics**: Real-time usage and performance metrics for all entities
- **📊 Metadata Tracking**: View comprehensive audit information in entity detail modals

---

## ✍️ Common Actions

| Action                   | How                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------ |
| Register a tool          | Use the Tools tab → Add Tool form                                                    |
| Bulk import tools        | Use API endpoint `/admin/tools/import` (see [Bulk Import](../manage/bulk-import.md)) |
| View prompt output       | Go to Prompts → click View                                                           |
| **View entity metadata** | Click "View" on any entity → scroll to "Metadata" section                            |
| Toggle server activity   | Use the "Activate/Deactivate" buttons in Servers tab                                 |
| Delete a resource        | Navigate to Resources → click Delete (after confirming)                              |

All actions are reflected in the live API via `/tools`, `/prompts`, etc.

---

## 🔐 Auth + JWT from UI

Upon successful login, the UI automatically sets a secure JWT token as an HTTP-only cookie (`jwt_token`).

This token is reused for all Admin API calls from within the UI.

---

## 🔄 Live Reloading (Dev Only)

If running in development mode (`DEV_MODE=true` or `make run`), changes to templates and routes reload automatically.

---

## 🔒 Air-Gapped Mode

For environments without internet access, the Admin UI serves its bundled CSS/JavaScript locally without requiring external asset fetches.

### Enable Air-Gapped Mode

Set the environment variable:

```bash
MCPGATEWAY_UI_AIRGAPPED=true
```

### How It Works

Admin UI vendor assets are installed via npm and bundled/chunked with Vite, so the UI does not depend on CDN-hosted JavaScript.

When `MCPGATEWAY_UI_AIRGAPPED=true`:

- The UI runs without external asset fetches
- No external network requests are required for Admin UI assets
- Functionality remains available offline

### Container Builds (Recommended)

All production container builds (`Containerfile`, `Containerfile.lite`, `Containerfile.scratch`) include the Vite-built Admin UI assets via the `frontend-builder` stage:

```bash
docker build -f Containerfile -t mcpgateway:airgapped .
docker run -e MCPGATEWAY_UI_AIRGAPPED=true -p 4444:4444 mcpgateway:airgapped
```

See [Container Deployment](../deployment/container.md#airgapped-deployments) for details.

### Local Development

The Admin UI bundle is built automatically via `make install-dev` or `make build-ui`. To test air-gapped mode locally:

```bash
MCPGATEWAY_UI_AIRGAPPED=true make dev
```

All vendor JavaScript is installed via npm and bundled/chunked with Vite for local serving.

---
