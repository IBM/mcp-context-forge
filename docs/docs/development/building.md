# Building Locally

Follow these instructions to set up your development environment, build the gateway from source, and run it interactively.

---

## 🧩 Prerequisites

- Python **≥ 3.10**
- `make`
- (Optional) Docker or Podman for container builds

---

## 🔧 One-Liner Setup (Recommended)

```bash
make venv install serve
```

This will:

1. Create a virtual environment in `.venv/`
2. Install Python dependencies including dev extras
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
make serve         # production-mode Gunicorn (http://localhost:4444)
make run           # dev-mode Uvicorn (reloads on change)
./run.sh --reload  # same as above, with CLI flags
```

Use `make run` or `./run.sh` during development for auto-reload.

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
