# 🐍 Local Deployment

This guide walks you through running MCP Gateway on your local machine using a virtual environment or directly via Python.

---

## 🚀 One-Liner Setup

The easiest way to start the server in development mode:

```bash
make venv install serve
```

This does the following:

1. Creates a `.venv/` virtual environment
2. Installs all dependencies (including dev tools)
3. Launches **Gunicorn** on `http://localhost:4444`

---

## 🧪 Development Mode with Live Reload

If you want auto-reload on code changes:

```bash
make run        # or:
./run.sh --reload --log debug
```

> Ensure your `.env` file includes:
>
> ```env
> DEV_MODE=true
> RELOAD=true
> DEBUG=true
> ```

---

## 🧪 Health Test

```bash
curl http://localhost:4444/health
```

Expected output:

```json
{"status": "healthy"}
```

---

## 🔐 Admin UI

Visit [http://localhost:4444/admin](http://localhost:4444/admin) and login using your `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` from `.env`.

---

## 🔁 Quick JWT Setup

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token -u admin)
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```
