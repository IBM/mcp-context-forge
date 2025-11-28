# 🐍 Local Deployment

This guide walks you through running MCP Gateway on your local machine using a virtual environment or directly via Python.

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

By default, MCP Gateway uses SQLite for simplicity. You can configure alternative databases via the `DATABASE_URL` environment variable:

=== "SQLite (Default)"
    ```bash
    # .env file
    DATABASE_URL=sqlite:///./mcp.db
    ```

=== "MariaDB"
    ```bash
    # .env file
    DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp
    ```

    !!! info "MariaDB Setup"
        Install and configure MariaDB server:
        ```bash
        # Ubuntu/Debian
        sudo apt update && sudo apt install mariadb-server

        # Create database and user
        sudo mariadb -e "CREATE DATABASE mcp;"
        sudo mariadb -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
        sudo mariadb -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
        sudo mariadb -e "FLUSH PRIVILEGES;"
        ```

=== "MySQL"
    ```bash
    # .env file
    DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp
    ```

    !!! info "MySQL Setup"
        Install and configure MySQL server:
        ```bash
        # Ubuntu/Debian
        sudo apt update && sudo apt install mysql-server

        # Create database and user
        sudo mysql -e "CREATE DATABASE mcp;"
        sudo mysql -e "CREATE USER 'mysql'@'localhost' IDENTIFIED BY 'changeme';"
        sudo mysql -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'localhost';"
        sudo mysql -e "FLUSH PRIVILEGES;"
        ```

=== "PostgreSQL"
    ```bash
    # .env file
    DATABASE_URL=postgresql://postgres:changeme@localhost:5432/mcp
    ```

!!! tip "MariaDB & MySQL Full Compatibility"
    MariaDB and MySQL are **fully supported** with:

    - **36+ database tables** working perfectly with MariaDB 10.6+ and MySQL 8.0+
    - All **VARCHAR length issues** resolved for MariaDB/MySQL compatibility
    - Complete feature parity with SQLite and PostgreSQL

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
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com)
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```
