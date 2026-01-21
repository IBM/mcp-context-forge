# Admin UI

MCP Gateway includes a built-in Admin UI for managing all entities in real time via a web browser.

---

## 🖥️ Accessing the UI

After launching the gateway (`make serve` or `make podman-run`), open your browser and go to:

[http://localhost:4444/admin](http://localhost:4444/admin) - or the corresponding URL / port / protocol (ex: https when launching with `make podman-run-ssl`)

Login using the `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` set in your `.env`.

---

## 🧭 UI Overview

The Admin UI is built with **HTMX**, **Alpine.js**, and **Tailwind CSS**, offering a dynamic, SPA-like experience without JavaScript bloat.

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Templating** | Jinja2 | Server-side HTML rendering (44 templates in `mcpgateway/templates/`) |
| **Interactivity** | HTMX 1.9.10 | AJAX without JavaScript, HTML-over-HTTP patterns |
| **Reactivity** | Alpine.js 3.x | Lightweight reactive components |
| **Styling** | Tailwind CSS | Utility-first CSS framework |
| **Code Editor** | CodeMirror 5.65.18 | Syntax-highlighted editing |
| **Charts** | Chart.js | Data visualization and metrics |
| **Markdown** | Marked.js | Markdown rendering |
| **Security** | DOMPurify | XSS sanitization |
| **Icons** | Font Awesome | Icon library |

All vendor libraries are bundled locally for **air-gapped deployments** with CDN fallbacks. See [Air-Gapped Mode](#-air-gapped-mode) below.

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

| Action | How |
|--------|-----|
| Register a tool | Use the Tools tab → Add Tool form |
| Bulk import tools | Use API endpoint `/admin/tools/import` (see [Bulk Import](../manage/bulk-import.md)) |
| View prompt output | Go to Prompts → click View |
| **View entity metadata** | Click "View" on any entity → scroll to "Metadata" section |
| Toggle server activity | Use the "Activate/Deactivate" buttons in Servers tab |
| Delete a resource | Navigate to Resources → click Delete (after confirming) |

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

For environments without internet access, the Admin UI can load all CSS/JavaScript from local files instead of CDNs.

### Enable Air-Gapped Mode

Set the environment variable:

```bash
MCPGATEWAY_UI_AIRGAPPED=true
```

### How It Works

By default, the UI loads vendor libraries from CDNs (Tailwind, HTMX, Alpine.js, etc.). When `MCPGATEWAY_UI_AIRGAPPED=true`:

- All libraries load from `mcpgateway/static/vendor/`
- No external network requests for UI assets
- Identical functionality, fully offline

### Container Builds (Recommended)

`Containerfile.lite` automatically downloads and bundles vendor assets during build:

```bash
docker build -f Containerfile.lite -t mcpgateway:airgapped .
docker run -e MCPGATEWAY_UI_AIRGAPPED=true -p 4444:4444 mcpgateway:airgapped
```

See [Container Deployment](../deployment/container.md#-airgapped-deployments) for details.

### Local Development

To test air-gapped mode locally without containers:

```bash
# Download vendor assets (one-time)
./scripts/download-cdn-assets.sh

# Run with air-gapped mode enabled
MCPGATEWAY_UI_AIRGAPPED=true make dev
```

The script downloads to `mcpgateway/static/vendor/`:

| Library | Version | Size |
|---------|---------|------|
| Tailwind CSS | CDN | ~404KB |
| HTMX | 1.9.10 | ~52KB |
| CodeMirror | 5.65.18 | ~216KB |
| Alpine.js | 3.14.1 | ~48KB |
| Chart.js | 4.4.1 | ~208KB |
| Font Awesome | 6.4.0 | ~1.2MB |

---
