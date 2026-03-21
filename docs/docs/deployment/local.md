# 🐍 Local Deployment

This guide walks you through running ContextForge on your local machine using a virtual environment or directly via Python.

---

## 🚀 One-Liner Setup

The easiest way to start the server in development mode:

```bash
make venv install-dev serve
```

This does the following:

1. Creates a `.venv/` virtual environment
2. Installs all dependencies (including dev tools)
3. Launches **Gunicorn** on `http://localhost:4444`

---

## 🧪 Development Mode with Live Reload

If you want auto-reload on code changes:

```bash
make dev        # hot-reload (Uvicorn) on :8000
# or:
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

## 🗄 Database Configuration

By default, ContextForge uses SQLite for simplicity. You can configure alternative databases via the `DATABASE_URL` environment variable:

=== "SQLite (Default)"
    ```bash
    # .env file
    DATABASE_URL=sqlite:///./mcp.db
    ```

=== "PostgreSQL"
    ```bash
    # .env file
    DATABASE_URL=postgresql+psycopg://postgres:changeme@localhost:5432/mcp
    ```

!!! tip "Database Recommendation"
    Use **SQLite** for development and testing. For production deployments, use **PostgreSQL** for better concurrency, performance, and reliability.

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

Visit [http://localhost:4444/admin](http://localhost:4444/admin) and login using your `PLATFORM_ADMIN_EMAIL` and `PLATFORM_ADMIN_PASSWORD` from `.env`.

---

## 🔁 Quick JWT Setup

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com)
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```
