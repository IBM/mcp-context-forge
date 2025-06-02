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

It provides tabbed access to:

- **Servers Catalog**: Define or edit MCP servers (real or virtual)
- **Tools**: Register REST or native tools, configure auth/rate limits, test responses
- **Resources**: Add templated or static resources, set MIME types, enable caching
- **Prompts**: Define Jinja2 prompt templates with argument schemas and preview rendering
- **Gateways**: View and manage federated peers, toggle activity status
- **Roots**: Register root URIs for agent or resource scoping
- **Metrics**: Real-time usage and performance metrics for all entities

---

## ✍️ Common Actions

| Action | How |
|--------|-----|
| Register a tool | Use the Tools tab → Add Tool form |
| View prompt output | Go to Prompts → click View |
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
