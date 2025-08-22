# 📦 Container Deployment

You can run MCP Gateway as a fully self-contained container. This is the recommended method for production or platform-agnostic deployments. You can use any container engine (ex: Docker or Podman).

---

## Quick Start (Pre-built Container Image)

If you just want to run the gateway using the official OCI container image from GitHub Container Registry:

```bash
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  -e DATABASE_URL=sqlite:///./mcp.db \
  --network=host \
  ghcr.io/ibm/mcp-context-forge:0.6.0

docker logs mcpgateway
```

You can now access the UI at [http://localhost:4444/admin](http://localhost:4444/admin)

## 🐳 Build the Container

### Using Podman (recommended)

```bash
make podman
```

### Using Docker (manual alternative)

```bash
docker build -t mcpgateway:latest -f Containerfile .
```

> The base image uses `python:3.11-slim` with Gunicorn and Uvicorn workers.

---

## 🏃 Run the Container

### With HTTP (no TLS)

```bash
make podman-run
```

This starts the app at `http://localhost:4444`.

---

### With Self-Signed TLS (HTTPS)

```bash
make podman-run-ssl
```

Runs the gateway using certs from `./certs/`, available at:

```
https://localhost:4444
```

---

## ⚙ Runtime Configuration

All environment variables can be passed via:

* `docker run -e KEY=value`
* A mounted `.env` file (`--env-file .env`)

---

## 🧪 Test the Running Container

```bash
curl http://localhost:4444/health
curl http://localhost:4444/tools
```

> Use `curl -k` if running with self-signed TLS

---

## 🧼 Stop & Clean Up

```bash
podman stop mcpgateway
podman rm mcpgateway
```

Or with Docker:

```bash
docker stop mcpgateway
docker rm mcpgateway
```
