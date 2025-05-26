# Development

This section is for developers and contributors working on MCP Gateway itself — whether you're adding features, fixing bugs, or building custom integrations.

---

## 🧰 What You'll Find Here

| Page | Description |
|------|-------------|
| [Building Locally](building.md) | How to install dependencies, set up a virtual environment, and run the gateway |
| [Packaging](packaging.md) | How to build a release, container image, or prebuilt binary |

---

## 🛠 Developer Environment

MCP Gateway is built with:

- **Python 3.10+**
- **FastAPI**
- **Pydantic Settings**
- **SQLAlchemy (async)**
- **HTMX + Alpine.js + Tailwind (for UI)**

Development tools include:

- `ruff`, `mypy`, `black`, `isort` for linting and formatting
- `pytest` and `httpx` for tests
- `uvicorn` and `gunicorn` for serving the app

---

## 💡 Development Philosophy

This project prioritizes:

- **Strict API consistency** with the MCP protocol
- **Composable internals** (service modules, dependency injection)
- **Production-first** design (SSL, metrics, rate limits, etc.)
- **Dev-friendly tools** (Makefile, pre-commit hooks, typed config)

---

## 🚧 Contribution Guidelines

Please see [`DEVELOPING.md`](https://github.com/your-org/your-repo/blob/main/DEVELOPING.md) for coding standards, commit conventions, and review workflow.
