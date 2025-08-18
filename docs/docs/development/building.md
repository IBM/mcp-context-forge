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

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs:

* Core app dependencies
* Dev tools (`ruff`, `black`, `mypy`, etc.)
* Test runners (`pytest`, `coverage`)

---

## 🚀 Running the App

You can run the gateway with:

```bash
make serve         # production-mode (Gunicorn) on http://localhost:4444
make dev           # hot-reload (Uvicorn) on http://localhost:8000
make run           # wrapper over uvicorn; pass --reload to enable auto-reload
./run.sh --reload  # equivalent of 'make run' with explicit flags
```

Use `make dev` during development for auto-reload on port 8000.

---

## 🔄 Live Reload Tips

Ensure `RELOAD=true` and `DEV_MODE=true` are set in your `.env` during development.

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
