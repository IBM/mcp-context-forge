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
  -e JWT_AUDIENCE=mcpgateway-api \
  -e JWT_ISSUER=mcpgateway \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=changeme \
  -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
  -e DATABASE_URL=sqlite:///./mcp.db \
  --network=host \
  ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1

docker logs mcpgateway
```

You can now access the UI at [http://localhost:4444/admin](http://localhost:4444/admin)

### Multi-architecture containers
Note: the container build process creates container images for 'amd64', 'arm64' and 's390x' architectures. The version `ghcr.io/ibm/mcp-context-forge:VERSION`
not points to a manifest so that if all commands will pull the correct image for the architecture being used (whether that be locally or on Kubernetes or OpenShift).

If the specific image is needed for one architecture on a different architecture use the appropriate arguments for your given container execution tool:

With docker run:
```
docker run [... all your options...] --platform linux/arm64 ghcr.io/ibm/mcp-context-forge:VERSION
```

With podman run:
```
podman run [... all your options...] --platform linux/arm64 ghcr.io/ibm/mcp-context-forge:VERSION
```
Or
```
podman run [... all your options...] --arch arm64 ghcr.io/ibm/mcp-context-forge:VERSION
```


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

## 🔒 Airgapped Deployments

For environments without internet access, you can build a container with all UI assets bundled locally.

### Build Airgapped Container

Use `Containerfile.lite` which automatically downloads CDN assets during build:

```bash
docker build -f Containerfile.lite -t mcpgateway:airgapped .
```

This downloads and bundles:

- Tailwind CSS (~404KB)
- HTMX (~52KB)
- CodeMirror (~216KB)
- Alpine.js (~48KB)
- Chart.js (~208KB)

**Total: ~932KB of UI assets**

### Run in Airgapped Mode

```bash
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e MCPGATEWAY_UI_AIRGAPPED=true \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  -e DATABASE_URL=sqlite:///./mcp.db \
  mcpgateway:airgapped
```

!!! success "Fully Offline UI"
    With `MCPGATEWAY_UI_AIRGAPPED=true`, the Admin UI works completely offline with zero external dependencies. All CSS and JavaScript are served from local files bundled in the container.

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
