# ⚙️ Fly.io Deployment Guide for MCP Gateway

This guide covers the complete deployment workflow for the **MCP Gateway** on Fly.io, including common troubleshooting steps.

---

## Overview

Fly.io is a global app platform for running containers close to your users, with built-in TLS, persistent volumes, and managed Postgres support. It offers a generous free tier and automatic HTTPS with fly.dev subdomains.

---

## 1 - Prerequisites

| Requirement | Details |
| -------------------- | ------------------------------------------------------------------ |
| Fly.io account | [Sign up](https://fly.io) |
| Fly CLI | Install via Homebrew: `brew install flyctl` or see Fly docs |
| Docker **or** Podman | For local image builds (optional) |
| Containerfile | The included Containerfile with psycopg3 (psycopg[binary]) support |

---

## 2 - Quick Start (Recommended)

### 2.1 Initialize Fly project
```bash
fly launch --name your-app-name --no-deploy
```
This creates a new Fly app without deploying immediately.

### 2.2 Create and attach Fly Postgres
```bash
# Create postgres (choose Development configuration for testing)
fly postgres create --name your-app-db --region yyz

# Note the connection details from the output, you'll need the password
```

### 2.3 Set secrets
```bash
# Set authentication secrets
fly secrets set JWT_SECRET_KEY=$(openssl rand -hex 32)
fly secrets set BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=your-secure-password

# Set database URL (CRITICAL: use postgresql+psycopg:// for psycopg3)
fly secrets set DATABASE_URL="postgresql+psycopg://postgres:YOUR_PASSWORD@your-app-db.flycast:5432/postgres"
```

**⚠️ Important:** Always use `postgresql+psycopg://` scheme for psycopg3. Do not use `postgresql://` (requires psycopg2) or `postgres://` (invalid).

### 2.4 Deploy the app
```bash
fly deploy
```

---

## 3 - Containerfile Requirements

Ensure your Containerfile explicitly installs PostgreSQL dependencies:

```dockerfile
# Create virtual environment, upgrade pip and install dependencies
RUN python3 -m venv /app/.venv && \
/app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
/app/.venv/bin/python3 -m pip install 'psycopg[binary]' && \
/app/.venv/bin/python3 -m uv pip install ".[redis]"
```

The explicit `psycopg[binary]` (psycopg3) installation is required because uv may not properly install optional dependencies.

---

## 4 - fly.toml Configuration

Your `fly.toml` should look like this:

```toml
app = "your-app-name"
primary_region = "yyz"

[build]
dockerfile = "Containerfile"

[env]
HOST = "0.0.0.0"
PORT = "4444"

[http_service]
internal_port = 4444
force_https = true
auto_stop_machines = "stop"
auto_start_machines = true
min_machines_running = 0
processes = ["app"]

[[vm]]
memory = "1gb"
cpu_kind = "shared"
cpus = 1
```

**Note:** Don't put secrets like `DATABASE_URL` in `fly.toml` - use `fly secrets set` instead.

---

## 5 - Testing Your Deployment

### 5.1 Check app status
```bash
fly status
fly logs
```

### 5.2 Test endpoints
```bash
# Health check (no auth required)
curl https://your-app-name.fly.dev/health

# Protected endpoints (require auth)
curl -u admin:your-password https://your-app-name.fly.dev/docs
curl -u admin:your-password https://your-app-name.fly.dev/tools
```

### 5.3 Expected responses
- Health: `{"status":"healthy"}`
- Protected endpoints without auth: `{"detail":"Not authenticated"}`
- Protected endpoints with auth: JSON response with data

---

## 6 - Troubleshooting

### Common Issue 1: SQLAlchemy postgres dialect error
```
sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres
```

**Solutions:**

1. Ensure `psycopg[binary]` is explicitly installed in Containerfile
2. Use `postgresql+psycopg://` (not `postgresql://` or `postgres://`) in DATABASE_URL
3. Rebuild with `fly deploy --no-cache`

### Common Issue 2: Database connection refused
**Solutions:**

1. Verify DATABASE_URL format: `postgresql+psycopg://postgres:PASSWORD@your-db.flycast:5432/postgres`
2. Check postgres app is running: `fly status -a your-app-db`
3. Verify password matches postgres creation output

### Common Issue 3: Machines not updating
**Solutions:**
```bash
# Force machine updates
fly machine list
fly machine update MACHINE_ID --image your-new-image

# Or restart all machines
fly scale count 0
fly scale count 1
```

---

## 7 - Production Considerations

### Security
- Change default `BASIC_AUTH_PASSWORD` to a strong password
- Consider using JWT tokens for API access
- Enable Fly's private networking for database connections

### Scaling
```bash
# Scale to multiple machines for HA
fly scale count 2

# Scale machine resources
fly scale memory 2gb
```

### Monitoring
```bash
# View real-time logs
fly logs -f

# Check machine metrics
fly machine status MACHINE_ID
```

---

## 8 - Clean Deployment Script

For a completely fresh deployment:

```bash
#!/bin/bash
set -e

APP_NAME="your-app-name"
DB_NAME="${APP_NAME}-db"
REGION="yyz"
PASSWORD=$(openssl rand -base64 32)

echo "🚀 Deploying MCP Gateway to Fly.io..."

# Create app
fly launch --name $APP_NAME --no-deploy --region $REGION

# Create postgres
fly postgres create --name $DB_NAME --region $REGION

# Set secrets
fly secrets set JWT_SECRET_KEY=$(openssl rand -hex 32)
fly secrets set BASIC_AUTH_USER=admin
fly secrets set BASIC_AUTH_PASSWORD=$PASSWORD

# Get postgres password and set DATABASE_URL
echo "⚠️  Set your DATABASE_URL manually with the postgres password:"
echo "fly secrets set DATABASE_URL=\"postgresql+psycopg://postgres:YOUR_PG_PASSWORD@${DB_NAME}.flycast:5432/postgres\""

# Deploy
echo "🏗️  Ready to deploy. Run: fly deploy"
```

---

## 9 - Additional Resources

- [Fly.io Documentation](https://fly.io/docs)
- [Fly Postgres Guide](https://fly.io/docs/postgres/)
- [Fly Secrets Management](https://fly.io/docs/reference/secrets/)

**Success indicators:**

- ✅ `fly status` shows machines as "started"
- ✅ `/health` endpoint returns `{"status":"healthy"}`
- ✅ Protected endpoints require authentication
- ✅ No SQLAlchemy errors in logs
