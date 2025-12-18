# Customizing the Admin UI

The Admin experience is shipped as a Jinja template (`mcpgateway/templates/admin.html`)
with supporting assets in `mcpgateway/static/`. It uses **HTMX** for
request/response swaps, **Alpine.js** for light-weight reactivity, and the
Tailwind CDN for styling. There are no environment-variable knobs for colors or
layout—the way to customise it is to edit those files (or layer overrides during
deployment).

---

## Feature Flags to Enable the UI

Ensure the Admin interface is turned on before making changes:

```bash
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
```

The only other related tuning knob is:

- `MCPGATEWAY_UI_TOOL_TEST_TIMEOUT` (milliseconds) – timeout for the "Test Tool"
  action triggered from the Tools catalog.

Every other visual/behaviour change is code-driven.

---

## Recommended Editing Workflow

1. Copy `.env.example` to `.env`, then set:
   ```bash
   DEV_MODE=true
   RELOAD=true
   ```
   This enables template + static reloads while you work.

2. Start the dev server: `make dev` (serves the UI at http://localhost:8000).
3. Edit any of the following and refresh your browser:
   - `mcpgateway/templates/admin.html`
   - `mcpgateway/static/admin.css`
   - `mcpgateway/static/admin.js`
   - Additional assets under `mcpgateway/static/`
4. Commit the customised files or prepare overrides for your deployment target
   (see [Deploying Overrides](#deploying-overrides)).

Tip: keep your changes on a dedicated branch so that rebase/merge with upstream
remains manageable.

---

## File Layout Reference

| Path | Description |
| --- | --- |
| `mcpgateway/templates/admin.html` | Single-page admin template containing header, navigation, tables, modals, metrics, etc. |
| `mcpgateway/static/admin.css` | Tailwind-friendly overrides (spinners, tooltips, table tweaks). |
| `mcpgateway/static/admin.js` | Behaviour helpers (form toggles, request utilities, validation). |
| `mcpgateway/static/images/` | Default logo, favicon, and imagery used in the UI. |

All static assets are served from `/static/` and respect `ROOT_PATH` when the
app is mounted behind a proxy.

---

## Branding Essentials

### Document Title & Header
- Update the `<title>` element and the main `<h1>` block near the top of
  `admin.html` with your organisation's name.

- The secondary copy and links (Docs, GitHub star) live in the same header
  section—edit or remove them as needed.

### Logo & Favicon
- Replace the default files in `mcpgateway/static/` (or add your own under
  `static/images/`).

- Update the `<link rel="icon">` and `<img src="...">` references in
  `admin.html` to point to your assets, e.g.
  ```html
  <link rel="icon" href="{{ root_path }}/static/images/company-favicon.ico" />
  <img src="{{ root_path }}/static/images/company-logo.svg" class="h-8" alt="Company" />
  ```

### Colors & Tailwind
- Tailwind is initialised in `admin.html` via `https://cdn.tailwindcss.com` with
  `darkMode: "class"`.

- Add a custom config block to extend colours/fonts and swap utility classes, for example:
  ```html
  <script>
    tailwind.config = {
      darkMode: "class",
      theme: {
        extend: {
          colors: { brand: "#1d4ed8", accent: "#f97316" },
          fontFamily: { display: ['"IBM Plex Sans"', 'sans-serif'] },
        },
      },
    };
  </script>
  ```
- For bespoke CSS (animations, overrides), append to `admin.css` or include a
  new stylesheet in the `<head>`:
  ```html
  <link rel="stylesheet" href="{{ root_path }}/static/css/custom.css" />
  ```

### Theme Toggle
- The dark/light toggle persists a `darkMode` value in `localStorage`. Change the
  default by altering the `x-data` initialiser in the `<html>` tag if you want to
  default to dark:
  ```html
  x-data="{ darkMode: JSON.parse(localStorage.getItem('darkMode') || 'true') }"
  ```

---

## Behaviour Customisation

- `admin.js` powers form helpers (e.g. locking the Tool URL field when MCP is
  selected) and general UX‐polish. Append your scripts there or include a new JS
  file at the end of `admin.html`.

- Use HTMX hooks (`htmx:beforeSwap`, `htmx:afterSwap`, etc.) if you need to
  intercept requests.

- Alpine components live on each panel (look for `x-data="tabs"`, etc.)—extend
  them by adding properties/methods in the `x-data` object.

- Avoid writing raw `innerHTML` with user data to preserve the UI's XSS
  protections; prefer `textContent`.

- Lazy-loaded sections (bulk import, A2A, teams, etc.) are clearly marked in the
  template—remove panels you don't need.

---

## Key Template Anchors

Search for these comments in `admin.html` when hunting for specific areas:

- `<!-- Navigation Tabs -->` – top-level tab buttons.
- `<!-- Status Cards -->` – summary cards for totals.
- `<!-- Servers Table -->`, `<!-- Tools Table -->`, `<!-- Resources Table -->`, etc. – per-resource CRUD grids.
- `<!-- Bulk Import Modal -->`, `<!-- Team Modal -->` – modal dialogs.
- `id="metadata-tracking"`, `id="a2a-agents"`, `id="team-management"` – advanced sections you can prune or reorder.

Make your edits and refresh the browser to confirm behaviour.

---

## Deploying Overrides

When packaging the gateway:

- **Bake into the image** – copy customised templates/static files during the
  container build.

- **Mount at runtime** – overlay files via volumes:
  ```bash
  docker run \
    -v $(pwd)/overrides/admin.html:/app/mcpgateway/templates/admin.html:ro \
    -v $(pwd)/overrides/static:/app/mcpgateway/static/custom:ro \
    ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1
  ```
  Then update template references to point at `static/custom/...`.

- **Fork + rebase** – maintain a thin fork that carries your branding patches.

In Kubernetes, place customised assets in a ConfigMap/Secret and mount over the
default paths (`/app/mcpgateway/templates/admin.html`, `/app/mcpgateway/static/`).
Roll the deployment after changes so the pod picks up the new files.

---

## Testing Checklist

1. `make dev` – confirm the UI renders, tabs switch, and tables load as expected.
2. Optional: `pytest tests/playwright/ -k admin` – run UI smoke tests if you
   altered interaction logic.

3. Verify in a staging/production-like environment that:
   - Static assets resolve behind your proxy (`ROOT_PATH`/`APP_DOMAIN`).
   - Authentication flows still succeed (basic + JWT).
   - Any branding assets load quickly (serve them via CDN if heavy).
4. Document your customisations internally so future upgrades know which sections
   were changed.
