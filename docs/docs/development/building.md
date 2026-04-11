# Building Locally

Follow these instructions to set up your development environment, build the gateway from source, and run it interactively.

---

## 🧩 Prerequisites

- Python **≥ 3.11**
- `make`
- (Optional) Docker or Podman for container builds

---

## 🔧 One-Liner Setup (Recommended)

```bash
make venv install-dev serve
```

This will:

1. Create a virtual environment in `.venv/`
2. Install Python dependencies (including dev extras)
3. Run the gateway using Gunicorn

---

## 🐍 Manual Python Setup

If you need to bypass the Makefile, use `uv` directly — the project's dev
dependency group is defined via PEP 735 (`[dependency-groups]`), so the
traditional `pip install -e ".[dev]"` form does not apply:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install --group dev '.[plugins]'
```

This installs:

* Core app dependencies
* Dev dependencies (`pytest`, `coverage`, `mypy`, `bandit`, etc.)
* Plugin framework extras

Formatters and linters (`ruff`, `black`, `isort`, `pylint`, `vulture`,
`interrogate`, `radon`, `yamllint`, `tomlcheck`) are **not** installed into the
venv — they are invoked on demand through the Makefile targets (`make ruff`,
`make black`, `make isort`, `make pylint`, `make vulture`, `make interrogate`,
`make radon`, `make yamllint`, `make tomllint`), which fetch pinned versions
via `uv tool run`.

---

## 🚀 Running the App

You can run the gateway with:

```bash
make serve         # production-mode (Gunicorn) on http://localhost:4444
make dev           # hot-reload (Uvicorn) on http://localhost:8000
make run           # executes ./run.sh with your current .env settings
RELOAD=true make run   # enable auto-reload via run.sh (same as ./run.sh --reload)
./run.sh --help    # view all supported flags
```

Use `make dev` during development for auto-reload on port 8000.

---

## 🔄 Live Reload Tips

When relying on `run.sh`, set `RELOAD=true` (or pass `--reload`) and `DEV_MODE=true` in your `.env` so settings match.

Also set:

```env
DEBUG=true
LOG_LEVEL=debug
```

---

## 🧪 Test It

```bash
curl http://localhost:4444/health
curl http://localhost:4444/tools
```

You should see `[]` or registered tools (once added).

---

## 🎨 Frontend Tooling

The Admin UI uses plain JavaScript (not TypeScript). Frontend tooling requires Node.js:

```bash
npm install        # install frontend dev dependencies
```

### Linting & Formatting

```bash
make eslint        # lint JavaScript with ESLint
make lint-web      # ESLint + HTMLHint + Stylelint
make format-web    # format with Prettier
```

### Frontend Stack

| Tool | Purpose |
|------|---------|
| ESLint | JavaScript linting (neostandard + prettier) |
| Prettier | Code formatting |
| Stylelint | CSS linting |
| HTMLHint | HTML linting |
| Biome | Fast JS/TS formatter/linter |
| Retire.js | Dependency vulnerability scanning |

### UI Testing

```bash
# Playwright (UI automation)
playwright install              # one-time browser setup
pytest tests/playwright/        # run UI tests

# Locust (load testing)
locust -f tests/loadtest/locustfile.py --host=http://localhost:4444
```

Note: JavaScript unit tests are not yet implemented. Testing efforts focus on the Python backend (pytest) and UI automation (Playwright).

### Air-Gapped Mode (Local Development)

To test the Admin UI without CDN dependencies:

```bash
# Download vendor libraries to mcpgateway/static/vendor/
./scripts/download-cdn-assets.sh

# Run with air-gapped mode
MCPGATEWAY_UI_AIRGAPPED=true make dev
```

This downloads HTMX, Alpine.js, Tailwind, CodeMirror, Chart.js, and Font Awesome for fully offline UI operation. See [Admin UI - Air-Gapped Mode](../overview/ui.md#air-gapped-mode) for details.
