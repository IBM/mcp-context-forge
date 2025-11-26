# MCP Gateway

> Model Context Protocol gateway & proxy - unify REST, MCP, and A2A with federation, virtual servers, retries, security, and an optional admin UI.

![](docs/docs/images/contextforge-banner.png)

<!-- === CI / Security / Build Badges === -->
[![Build Python Package](https://github.com/IBM/mcp-context-forge/actions/workflows/python-package.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/python-package.yml)&nbsp;
[![CodeQL](https://github.com/IBM/mcp-context-forge/actions/workflows/codeql.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/codeql.yml)&nbsp;
[![Bandit Security](https://github.com/IBM/mcp-context-forge/actions/workflows/bandit.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/bandit.yml)&nbsp;
[![Dependency Review](https://github.com/IBM/mcp-context-forge/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/dependency-review.yml)&nbsp;
[![Tests & Coverage](https://github.com/IBM/mcp-context-forge/actions/workflows/pytest.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/pytest.yml)&nbsp;
[![Lint & Static Analysis](https://github.com/IBM/mcp-context-forge/actions/workflows/lint.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/lint.yml)

<!-- === Container Build & Deploy === -->
[![Secure Docker Build](https://github.com/IBM/mcp-context-forge/actions/workflows/docker-image.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/docker-image.yml)&nbsp;
[![Deploy to IBM Code Engine](https://github.com/IBM/mcp-context-forge/actions/workflows/ibm-cloud-code-engine.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/ibm-cloud-code-engine.yml)

<!-- === Package / Container === -->
[![Async](https://img.shields.io/badge/async-await-green.svg)](https://docs.python.org/3/library/asyncio.html)
[![License](https://img.shields.io/github/license/ibm/mcp-context-forge)](LICENSE)&nbsp;
[![PyPI](https://img.shields.io/pypi/v/mcp-contextforge-gateway)](https://pypi.org/project/mcp-contextforge-gateway/)&nbsp;
[![Docker Image](https://img.shields.io/badge/docker-ghcr.io%2Fibm%2Fmcp--context--forge-blue)](https://github.com/ibm/mcp-context-forge/pkgs/container/mcp-context-forge)&nbsp;


ContextForge MCP Gateway is a feature-rich gateway, proxy and MCP Registry that federates MCP and REST services - unifying discovery, auth, rate-limiting, observability, virtual servers, multi-transport protocols, and an optional Admin UI into one clean endpoint for your AI clients. It runs as a fully compliant MCP server, deployable via PyPI or Docker, and scales to multi-cluster environments on Kubernetes with Redis-backed federation and caching.

![MCP Gateway](https://ibm.github.io/mcp-context-forge/images/mcpgateway.gif)
---

<!-- vscode-markdown-toc -->
## Table of Contents

* 1. [Table of Contents](#table-of-contents)
* 2. [🚀 Overview & Goals](#-overview--goals)
* 3. [Quick Start - PyPI](#quick-start---pypi)
    * 3.1. [1 - Install & run (copy-paste friendly)](#1---install--run-copy-paste-friendly)
* 4. [Quick Start - Containers](#quick-start---containers)
    * 4.1. [🐳 Docker](#-docker)
        * 4.1.1. [1 - Minimum viable run](#1---minimum-viable-run)
        * 4.1.2. [2 - Persist the SQLite database](#2---persist-the-sqlite-database)
        * 4.1.3. [3 - Local tool discovery (host network)](#3---local-tool-discovery-host-network)
    * 4.2. [🦭 Podman (rootless-friendly)](#-podman-rootless-friendly)
        * 4.2.1. [1 - Basic run](#1---basic-run)
        * 4.2.2. [2 - Persist SQLite](#2---persist-sqlite)
        * 4.2.3. [3 - Host networking (rootless)](#3---host-networking-rootless)
* 5. [Testing `mcpgateway.wrapper` by hand](#testing-mcpgatewaywrapper-by-hand)
    * 5.1. [🧩 Running from an MCP Client (`mcpgateway.wrapper`)](#-running-from-an-mcp-client-mcpgatewaywrapper)
        * 5.1.1. [1 - Install `uv` (`uvx` is an alias it provides)](#1---install-uv-uvx-is-an-alias-it-provides)
        * 5.1.2. [2 - Create an on-the-spot venv & run the wrapper](#2---create-an-on-the-spot-venv--run-the-wrapper)
        * 5.1.3. [Claude Desktop JSON (runs through **uvx**)](#claude-desktop-json-runs-through-uvx)
    * 5.2. [🚀 Using with Claude Desktop (or any GUI MCP client)](#-using-with-claude-desktop-or-any-gui-mcp-client)
* 6. [🚀 Quick Start: VS Code Dev Container](#-quick-start-vs-code-dev-container)
    * 6.1. [1 - Clone & Open](#1---clone--open)
    * 6.2. [2 - First-Time Build (Automatic)](#2---first-time-build-automatic)
* 7. [Quick Start (manual install)](#quick-start-manual-install)
    * 7.1. [Prerequisites](#prerequisites)
    * 7.2. [One-liner (dev)](#one-liner-dev)
    * 7.3. [Containerized (self-signed TLS)](#containerized-self-signed-tls)
    * 7.4. [Smoke-test the API](#smoke-test-the-api)
* 8. [Installation](#installation)
    * 8.1. [Via Make](#via-make)
    * 8.2. [UV (alternative)](#uv-alternative)
    * 8.3. [pip (alternative)](#pip-alternative)
    * 8.4. [Optional (PostgreSQL adapter)](#optional-postgresql-adapter)
        * 8.4.1. [Quick Postgres container](#quick-postgres-container)
* 9. [🔄 Upgrading to v0.7.0](#-upgrading-to-v070)
* 10. [Configuration (`.env` or env vars)](#configuration-env-or-env-vars)
    * 10.1. [Basic](#basic)
    * 10.2. [Authentication](#authentication)
    * 10.3. [A2A (Agent-to-Agent) Features](#a2a-agent-to-agent-features)
    * 10.4. [Email-Based Authentication & User Management](#email-based-authentication--user-management)
    * 10.5. [MCP Client Authentication](#mcp-client-authentication)
    * 10.6. [SSO (Single Sign-On) Configuration](#sso-single-sign-on-configuration)
    * 10.7. [Dynamic Client Registration & Virtual MCP Server Authentication](#dynamic-client-registration--virtual-mcp-server-authentication)
    * 10.8. [UI Features](#ui-features)
    * 10.9. [Security](#security)
    * 10.10. [Logging](#logging)
    * 10.11. [Transport](#transport)
    * 10.12. [Federation](#federation)
    * 10.13. [Resources](#resources)
    * 10.14. [Tools](#tools)
    * 10.15. [Prompts](#prompts)
    * 10.16. [Health Checks](#health-checks)
    * 10.17. [Database](#database)
    * 10.18. [Cache Backend](#cache-backend)
    * 10.19. [Plugin Configuration](#plugin-configuration)
    * 10.20. [Development](#development)
* 11. [Running](#running)
    * 11.1. [Makefile](#makefile)
    * 11.2. [Script helper](#script-helper)
    * 11.3. [Manual (Uvicorn)](#manual-uvicorn)
* 12. [Authentication examples](#authentication-examples)
* 13. [☁️ AWS / Azure / OpenShift](#️-aws--azure--openshift)
* 14. [☁️ IBM Cloud Code Engine Deployment](#️-ibm-cloud-code-engine-deployment)
    * 14.1. [🔧 Prerequisites](#-prerequisites-1)
    * 14.2. [📦 Environment Variables](#-environment-variables)
    * 14.3. [🚀 Make Targets](#-make-targets)
    * 14.4. [📝 Example Workflow](#-example-workflow)
* 15. [API Endpoints](#api-endpoints)
* 16. [Testing](#testing)
* 17. [Project Structure](#project-structure)
* 18. [API Documentation](#api-documentation)
* 19. [Makefile targets](#makefile-targets)
* 20. [🔍 Troubleshooting](#-troubleshooting)
    * 20.1. [Diagnose the listener](#diagnose-the-listener)
    * 20.2. [Why localhost fails on Windows](#why-localhost-fails-on-windows)
        * 20.2.1. [Fix (Podman rootless)](#fix-podman-rootless)
        * 20.2.2. [Fix (Docker Desktop > 4.19)](#fix-docker-desktop--419)
* 21. [Contributing](#contributing)
* 22. [Changelog](#changelog)
* 23. [License](#license)
* 24. [Core Authors and Maintainers](#core-authors-and-maintainers)
* 25. [Star History and Project Activity](#star-history-and-project-activity)

<!-- vscode-markdown-toc-config
    numbering=true
    autoSave=true
    /vscode-markdown-toc-config -->
<!-- /vscode-markdown-toc -->



## 🚀 Overview & Goals

**ContextForge** is a gateway, registry, and proxy that sits in front of any [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server, A2A server or REST API-exposing a unified endpoint for all your AI clients. See the [project roadmap](https://ibm.github.io/mcp-context-forge/architecture/roadmap/) for more details.

It currently supports:

* Federation across multiple MCP and REST services
* **A2A (Agent-to-Agent) integration** for external AI agents (OpenAI, Anthropic, custom)
* **gRPC-to-MCP translation** via automatic reflection-based service discovery
* Virtualization of legacy APIs as MCP-compliant tools and servers
* Transport over HTTP, JSON-RPC, WebSocket, SSE (with configurable keepalive), stdio and streamable-HTTP
* An Admin UI for real-time management, configuration, and log monitoring (with airgapped deployment support)
* Built-in auth, retries, and rate-limiting with user-scoped OAuth tokens and unconditional X-Upstream-Authorization header support
* **OpenTelemetry observability** with Phoenix, Jaeger, Zipkin, and other OTLP backends
* Scalable deployments via Docker or PyPI, Redis-backed caching, and multi-cluster federation

![MCP Gateway Architecture](https://ibm.github.io/mcp-context-forge/images/mcpgateway.svg)

For a list of upcoming features, check out the [ContextForge Roadmap](https://ibm.github.io/mcp-context-forge/architecture/roadmap/)

> Note on Multi‑Tenancy (v0.7.0): A comprehensive multi‑tenant architecture with email authentication, teams, RBAC, and resource visibility is available since v0.7.0. If upgrading from an older version, see the [Migration Guide](https://github.com/IBM/mcp-context-forge/blob/main/MIGRATION-0.7.0.md) and [Changelog](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md) for details.

**⚠️ Important**: See [SECURITY.md](./SECURITY.md) for more details.

---

<details>
<summary><strong>🔌 Gateway Layer with Protocol Flexibility</strong></summary>

* Sits in front of any MCP server or REST API
* Lets you choose your MCP protocol version (e.g., `2025-03-26`)
* Exposes a single, unified interface for diverse backends

</details>

<details>
<summary><strong>🌐 Federation of Peer Gateways (MCP Registry)</strong></summary>

* Auto-discovers or configures peer gateways (via mDNS or manual)
* Performs health checks and merges remote registries transparently
* Supports Redis-backed syncing and fail-over

</details>

<details>
<summary><strong>🧩 Virtualization of REST/gRPC Services</strong></summary>

* Wraps non-MCP services as virtual MCP servers
* Registers tools, prompts, and resources with minimal configuration
* **gRPC-to-MCP translation** via server reflection protocol
* Automatic service discovery and method introspection

</details>

<details>
<summary><strong>🔁 REST-to-MCP Tool Adapter</strong></summary>

* Adapts REST APIs into tools with:

  * Automatic JSON Schema extraction
  * Support for headers, tokens, and custom auth
  * Retry, timeout, and rate-limit policies

</details>

<details>
<summary><strong>🧠 Unified Registries</strong></summary>

* **Prompts**: Jinja2 templates, multimodal support, rollback/versioning
* **Resources**: URI-based access, MIME detection, caching, SSE updates
* **Tools**: Native or adapted, with input validation and concurrency controls

</details>

<details>
<summary><strong>📈 Admin UI, Observability & Dev Experience</strong></summary>

* Admin UI built with HTMX + Alpine.js
* Real-time log viewer with filtering, search, and export capabilities
* Auth: Basic, JWT, or custom schemes
* Structured logs, health endpoints, metrics
* 400+ tests, Makefile targets, live reload, pre-commit hooks

</details>

<details>
<summary><strong>🔍 OpenTelemetry Observability</strong></summary>

* **Vendor-agnostic tracing** with OpenTelemetry (OTLP) protocol support
* **Multiple backend support**: Phoenix (LLM-focused), Jaeger, Zipkin, Tempo, DataDog, New Relic
* **Distributed tracing** across federated gateways and services
* **Automatic instrumentation** of tools, prompts, resources, and gateway operations
* **LLM-specific metrics**: Token usage, costs, model performance
* **Zero-overhead when disabled** with graceful degradation
* **Easy configuration** via environment variables

Quick start with Phoenix (LLM observability):
```bash
# Start Phoenix
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

# Configure gateway
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Run gateway - traces automatically sent to Phoenix
mcpgateway
```

See [Observability Documentation](https://ibm.github.io/mcp-context-forge/manage/observability/) for detailed setup with other backends.

</details>

---

## Quick Start - PyPI

ContextForge is published on [PyPI](https://pypi.org/project/mcp-contextforge-gateway/) as `mcp-contextforge-gateway`.

---

**TLDR;**:
(single command using [uv](https://docs.astral.sh/uv/))

```bash
# Quick start with environment variables
BASIC_AUTH_PASSWORD=pass \
MCPGATEWAY_UI_ENABLED=true \
MCPGATEWAY_ADMIN_API_ENABLED=true \
PLATFORM_ADMIN_EMAIL=admin@example.com \
PLATFORM_ADMIN_PASSWORD=changeme \
PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444

# Or better: use the provided .env.example
cp .env.example .env
# Edit .env to customize your settings
uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
```

<details>
<summary><strong>📋 Prerequisites</strong></summary>

* **Python ≥ 3.10** (3.11 recommended)
* **curl + jq** - only for the last smoke-test step

</details>

### 1 - Install & run (copy-paste friendly)

```bash
# 1️⃣  Isolated env + install from pypi
mkdir mcpgateway && cd mcpgateway
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install mcp-contextforge-gateway

# 2️⃣  Copy and customize the configuration
# Download the example environment file
curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
cp .env.example .env
# Edit .env to customize your settings (especially passwords!)

# Or set environment variables directly:
export MCPGATEWAY_UI_ENABLED=true
export MCPGATEWAY_ADMIN_API_ENABLED=true
export PLATFORM_ADMIN_EMAIL=admin@example.com
export PLATFORM_ADMIN_PASSWORD=changeme
export PLATFORM_ADMIN_FULL_NAME="Platform Administrator"

BASIC_AUTH_PASSWORD=pass JWT_SECRET_KEY=my-test-key \
  mcpgateway --host 0.0.0.0 --port 4444 &   # admin/pass

# 3️⃣  Generate a bearer token & smoke-test the API
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/version | jq
```

<details>
<summary><strong>Windows (PowerShell) quick-start</strong></summary>

```powershell
# 1️⃣  Isolated env + install from PyPI
mkdir mcpgateway ; cd mcpgateway
python3 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install mcp-contextforge-gateway

# 2️⃣  Copy and customize the configuration
# Download the example environment file
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example" -OutFile ".env.example"
Copy-Item .env.example .env
# Edit .env to customize your settings

# Or set environment variables (session-only)
$Env:MCPGATEWAY_UI_ENABLED        = "true"
$Env:MCPGATEWAY_ADMIN_API_ENABLED = "true"
$Env:BASIC_AUTH_PASSWORD          = "changeme"      # admin/changeme
$Env:JWT_SECRET_KEY               = "my-test-key"
$Env:PLATFORM_ADMIN_EMAIL         = "admin@example.com"
$Env:PLATFORM_ADMIN_PASSWORD      = "changeme"
$Env:PLATFORM_ADMIN_FULL_NAME     = "Platform Administrator"

# 3️⃣  Launch the gateway
mcpgateway.exe --host 0.0.0.0 --port 4444

#   Optional: background it
# Start-Process -FilePath "mcpgateway.exe" -ArgumentList "--host 0.0.0.0 --port 4444"

# 4️⃣  Bearer token and smoke-test
$Env:MCPGATEWAY_BEARER_TOKEN = python3 -m mcpgateway.utils.create_jwt_token `
    --username admin@example.com --exp 10080 --secret my-test-key

curl -s -H "Authorization: Bearer $Env:MCPGATEWAY_BEARER_TOKEN" `
     http://127.0.0.1:4444/version | jq
```

</details>

<details>
<summary><strong>More configuration</strong></summary>

Copy [.env.example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example) to `.env` and tweak any of the settings (or use them as env variables).

</details>

<details>
<summary><strong>🚀 End-to-end demo (register a local MCP server)</strong></summary>

```bash
# 1️⃣  Spin up the sample GO MCP time server using mcpgateway.translate & docker
python3 -m mcpgateway.translate \
     --stdio "docker run --rm -i ghcr.io/ibm/fast-time-server:latest -transport=stdio" \
     --expose-sse \
     --port 8003

# Or using the official mcp-server-git using uvx:
pip install uv # to install uvx, if not already installed
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9000

# Alternative: running the local binary
# cd mcp-servers/go/fast-time-server; make build
# python3 -m mcpgateway.translate --stdio "./dist/fast-time-server -transport=stdio" --expose-sse --port 8002

# NEW: Expose via multiple protocols simultaneously!
python3 -m mcpgateway.translate \
     --stdio "uvx mcp-server-git" \
     --expose-sse \
     --expose-streamable-http \
     --port 9000
# Now accessible via both /sse (SSE) and /mcp (streamable HTTP) endpoints

# 2️⃣  Register it with the gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time","url":"http://localhost:8003/sse"}' \
     http://localhost:4444/gateways

# 3️⃣  Verify tool catalog
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools | jq

# 4️⃣  Create a *virtual server* bundling those tools. Use the ID of tools from the tool catalog (Step #3) and pass them in the associatedTools list.
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"time_server","description":"Fast time tools","associatedTools":[<ID_OF_TOOLS>]}' \
     http://localhost:4444/servers | jq

# Example curl
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
     -H "Content-Type: application/json"
     -d '{"name":"time_server","description":"Fast time tools","associatedTools":["6018ca46d32a4ac6b4c054c13a1726a2"]}' \
     http://localhost:4444/servers | jq

# 5️⃣  List servers (should now include the UUID of the newly created virtual server)
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers | jq

# 6️⃣  Client SSE endpoint. Inspect it interactively with the MCP Inspector CLI (or use any MCP client)
npx -y @modelcontextprotocol/inspector
# Transport Type: SSE, URL: http://localhost:4444/servers/UUID_OF_SERVER_1/sse,  Header Name: "Authorization", Bearer Token
```

</details>

<details>
<summary><strong>🖧 Using the stdio wrapper (mcpgateway-wrapper)</strong></summary>

```bash
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1/mcp
python3 -m mcpgateway.wrapper  # Ctrl-C to exit
```

You can also run it with `uv` or inside Docker/Podman - see the *Containers* section above.

In MCP Inspector, define `MCP_AUTH` and `MCP_SERVER_URL` env variables, and select `python3` as the Command, and `-m mcpgateway.wrapper` as Arguments.

```bash
echo $PWD/.venv/bin/python3 # Using the Python3 full path ensures you have a working venv
export MCP_SERVER_URL='http://localhost:4444/servers/UUID_OF_SERVER_1/mcp'
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
npx -y @modelcontextprotocol/inspector
```

or

Pass the url and auth as arguments (no need to set environment variables)
```bash
npx -y @modelcontextprotocol/inspector
command as `python`
Arguments as `-m mcpgateway.wrapper --url "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp" --auth "Bearer <your token>"`
```


When using a MCP Client such as Claude with stdio:

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH": "Bearer your-token-here",
        "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

</details>

---

## Quick Start - Containers

Use the official OCI image from GHCR with **Docker** *or* **Podman**.
Please note: Currently, arm64 is not supported. If you are e.g. running on MacOS, install via PyPi.

---

### 🐳 Docker

#### 1 - Minimum viable run

```bash
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=changeme \
  -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
  -e DATABASE_URL=sqlite:///./mcp.db \
  -e SECURE_COOKIES=false \
  ghcr.io/ibm/mcp-context-forge:0.9.0

# Note: when not running over SSL, use SECURE_COOKIES=false to prevent the browser denying access.

# Tail logs (Ctrl+C to quit)
docker logs -f mcpgateway

# Generating an API key
docker run --rm -it ghcr.io/ibm/mcp-context-forge:0.9.0 \
  python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key
```

Browse to **[http://localhost:4444/admin](http://localhost:4444/admin)** (user `admin` / pass `changeme`).

#### 2 - Persist the SQLite database

```bash
mkdir -p $(pwd)/data

touch $(pwd)/data/mcp.db

sudo chown -R :docker $(pwd)/data

chmod 777 $(pwd)/data

docker run -d --name mcpgateway \
  --restart unless-stopped \
  -p 4444:4444 \
  -v $(pwd)/data:/data \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=changeme \
  -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
  ghcr.io/ibm/mcp-context-forge:0.9.0
```

SQLite now lives on the host at `./data/mcp.db`.

#### 3 - Local tool discovery (host network)

```bash
mkdir -p $(pwd)/data

touch $(pwd)/data/mcp.db

sudo chown -R :docker $(pwd)/data

chmod 777 $(pwd)/data

docker run -d --name mcpgateway \
  --network=host \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e PORT=4444 \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=changeme \
  -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
  -v $(pwd)/data:/data \
  ghcr.io/ibm/mcp-context-forge:0.9.0
```

Using `--network=host` allows Docker to access the local network, allowing you to add MCP servers running on your host. See [Docker Host network driver documentation](https://docs.docker.com/engine/network/drivers/host/) for more details.

#### 4 - Airgapped deployment (no internet access)

For environments without internet access, build a container with bundled UI assets:

```bash
# Build airgapped container (downloads CDN assets during build)
docker build -f Containerfile.lite -t mcpgateway:airgapped .

# Run in airgapped mode
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

The Admin UI will work completely offline with all CSS/JS assets (~932KB) served locally.

---

### 🦭 Podman (rootless-friendly)

#### 1 - Basic run

```bash
podman run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e DATABASE_URL=sqlite:///./mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.9.0
```

#### 2 - Persist SQLite

```bash
mkdir -p $(pwd)/data

touch $(pwd)/data/mcp.db

sudo chown -R :docker $(pwd)/data

chmod 777 $(pwd)/data

podman run -d --name mcpgateway \
  --restart=on-failure \
  -p 4444:4444 \
  -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.9.0
```

#### 3 - Host networking (rootless)

```bash
mkdir -p $(pwd)/data

touch $(pwd)/data/mcp.db

sudo chown -R :docker $(pwd)/data

chmod 777 $(pwd)/data

podman run -d --name mcpgateway \
  --network=host \
  -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.9.0
```

---

<details>
<summary><strong>✏️ Docker/Podman tips</strong></summary>

* **.env files** - Put all the `-e FOO=` lines into a file and replace them with `--env-file .env`. See the provided [.env.example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example) for reference.
* **Pinned tags** - Use an explicit version (e.g. `v0.9.0`) instead of `latest` for reproducible builds.
* **JWT tokens** - Generate one in the running container:

  ```bash
  docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key
  ```
* **Upgrades** - Stop, remove, and rerun with the same `-v $(pwd)/data:/data` mount; your DB and config stay intact.

</details>

---

<details>
<summary><strong>🚑 Smoke-test the running container</strong></summary>

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/health | jq
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/tools | jq
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/version | jq
```

</details>

---

<details>
<summary><strong>🖧 Running the MCP Gateway stdio wrapper</strong></summary>

The `mcpgateway.wrapper` lets you connect to the gateway over **stdio** while keeping JWT authentication. You should run this from the MCP Client. The example below is just for testing.

```bash
# Set environment variables
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key)
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL='http://localhost:4444/servers/UUID_OF_SERVER_1/mcp'
export MCP_TOOL_CALL_TIMEOUT=120
export MCP_WRAPPER_LOG_LEVEL=DEBUG  # or OFF to disable logging

docker run --rm -i \
  -e MCP_AUTH=$MCP_AUTH \
  -e MCP_SERVER_URL=http://host.docker.internal:4444/servers/UUID_OF_SERVER_1/mcp \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  -e MCP_WRAPPER_LOG_LEVEL=DEBUG \
  ghcr.io/ibm/mcp-context-forge:0.9.0 \
  python3 -m mcpgateway.wrapper
```

</details>

---

## Testing `mcpgateway.wrapper` by hand:

Because the wrapper speaks JSON-RPC over stdin/stdout, you can interact with it using nothing more than a terminal or pipes.

```bash
# Start the MCP Gateway Wrapper
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL=http://localhost:4444/servers/YOUR_SERVER_UUID
python3 -m mcpgateway.wrapper
```

<details>
<summary><strong>Initialize the protocol</strong></summary>

```json
# Initialize the protocol
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"0.0.1"}}}

# Then after the reply:
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}

# Get prompts
{"jsonrpc":"2.0","id":4,"method":"prompts/list"}
{"jsonrpc":"2.0","id":5,"method":"prompts/get","params":{"name":"greeting","arguments":{"user":"Bob"}}}

# Get resources
{"jsonrpc":"2.0","id":6,"method":"resources/list"}
{"jsonrpc":"2.0","id":7,"method":"resources/read","params":{"uri":"https://example.com/some.txt"}}

# Get / call tools
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"Europe/Dublin"}}}
```

</details>

<details>
<summary><strong>Expected responses from mcpgateway.wrapper</strong></summary>

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false}},"serverInfo":{"name":"mcpgateway-wrapper","version":"0.9.0"}}}

# When there's no tools
{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}

# After you add some tools and create a virtual server
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"annotations":{"readOnlyHint":false,"destructiveHint":true,"idempotentHint":false,"openWorldHint":true},"description":"Convert time between different timezones","inputSchema":{"properties":{"source_timezone":{"description":"Source IANA timezone name","type":"string"},"target_timezone":{"description":"Target IANA timezone name","type":"string"},"time":{"description":"Time to convert in RFC3339 format or common formats like '2006-01-02 15:04:05'","type":"string"}},"required":["time","source_timezone","target_timezone"],"type":"object"},"name":"convert_time"},{"annotations":{"readOnlyHint":false,"destructiveHint":true,"idempotentHint":false,"openWorldHint":true},"description":"Get current system time in specified timezone","inputSchema":{"properties":{"timezone":{"description":"IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Defaults to UTC","type":"string"}},"type":"object"},"name":"get_system_time"}]}}

# Running the time tool:
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"2025-07-09T00:09:45+01:00"}]}}
```

</details>

### 🧩 Running from an MCP Client (`mcpgateway.wrapper`)

The `mcpgateway.wrapper` exposes everything your Gateway knows about over **stdio**, so any MCP client that *can't* (or *shouldn't*) open an authenticated SSE stream still gets full tool-calling power.

> **Remember** to substitute your real Gateway URL (and server ID) for `http://localhost:4444/servers/UUID_OF_SERVER_1/mcp`.
> When inside Docker/Podman, that often becomes `http://host.docker.internal:4444/servers/UUID_OF_SERVER_1/mcp` (macOS/Windows) or the gateway container's hostname (Linux).

---

<details>
<summary><strong>🐳 Docker / Podman</strong></summary>

```bash
export MCP_AUTH="Bearer $MCPGATEWAY_BEARER_TOKEN"

docker run -i --rm \
  --network=host \
  -e MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1/mcp \
  -e MCP_AUTH=${MCP_AUTH} \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  ghcr.io/ibm/mcp-context-forge:0.9.0 \
  python3 -m mcpgateway.wrapper
```

</details>

---

<details>
<summary><strong>📦 pipx (one-liner install &amp; run)</strong></summary>

```bash
# Install gateway package in its own isolated venv
pipx install --include-deps mcp-contextforge-gateway

# Run the stdio wrapper
MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1/mcp \
python3 -m mcpgateway.wrapper
# Alternatively with uv
uv run --directory . -m mcpgateway.wrapper
```

**Claude Desktop JSON** (uses the host Python that pipx injected):

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python3",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH": "Bearer <your-token>",
        "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

</details>

---

<details>
<summary><strong>⚡ uv / uvx (light-speed venvs)</strong></summary>

#### 1 - Install <code>uv</code>  (<code>uvx</code> is an alias it provides)

```bash
# (a) official one-liner
curl -Ls https://astral.sh/uv/install.sh | sh

# (b) or via pipx
pipx install uv
```

#### 2 - Create an on-the-spot venv & run the wrapper

```bash
# Create venv in ~/.venv/mcpgateway (or current dir if you prefer)
uv venv ~/.venv/mcpgateway
source ~/.venv/mcpgateway/bin/activate

# Install the gateway package using uv
uv pip install mcp-contextforge-gateway

# Launch wrapper
MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1/mcp \
uv run --directory . -m mcpgateway.wrapper # Use this just for testing, as the Client will run the uv command
```

#### Claude Desktop JSON (runs through **uvx**)

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "uvx",
      "args": [
        "run",
        "--",
        "python",
        "-m",
        "mcpgateway.wrapper"
      ],
      "env": {
        "MCP_AUTH": "Bearer <your-token>",
        "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
    }
  }
}
```

</details>

---

### 🚀 Using with Claude Desktop (or any GUI MCP client)

1. **Edit Config** → `File ▸ Settings ▸ Developer ▸ Edit Config`
2. Paste one of the JSON blocks above (Docker / pipx / uvx).
3. Restart the app so the new stdio server is spawned.
4. Open logs in the same menu to verify `mcpgateway-wrapper` started and listed your tools.

Need help? See:

* **MCP Debugging Guide** - [https://modelcontextprotocol.io/docs/tools/debugging](https://modelcontextprotocol.io/docs/tools/debugging)

---

## 🚀 Quick Start: VS Code Dev Container

Spin up a fully-loaded dev environment (Python 3.11, Docker/Podman CLI, all project dependencies) in just two clicks.

---

<details>
<summary><strong>📋 Prerequisites</strong></summary>

* **VS Code** with the [Dev Containers extension](https://code.visualstudio.com/docs/devcontainers/containers)
* **Docker** or **Podman** installed and running locally

</details>

<details>
<summary><strong>🧰 Setup Instructions</strong></summary>

### 1 - Clone & Open

```bash
git clone https://github.com/ibm/mcp-context-forge.git
cd mcp-context-forge
code .
```

VS Code will detect the `.devcontainer` and prompt:
**"Reopen in Container"**
*or* manually run: <kbd>Ctrl/Cmd ⇧ P</kbd> → **Dev Containers: Reopen in Container**

---

### 2 - First-Time Build (Automatic)

The container build will:

* Install system packages & Python 3.11
* Run `make install-dev` to pull all dependencies
* Execute tests to verify the toolchain

You'll land in `/workspace` ready to develop.

</details>

<details>
<summary><strong>🛠️ Daily Developer Workflow</strong></summary>

Common tasks inside the container:

```bash
# Start dev server (hot reload)
make dev            # http://localhost:4444

# Run tests & linters
make test
make lint
```

Optional:

* `make bash` - drop into an interactive shell
* `make clean` - clear build artefacts & caches
* Port forwarding is automatic (customize via `.devcontainer/devcontainer.json`)

</details>

<details>
<summary><strong>☁️ GitHub Codespaces: 1-Click Cloud IDE</strong></summary>

No local Docker? Use Codespaces:

1. Go to the repo → **Code ▸ Codespaces ▸ Create codespace on main**
2. Wait for the container image to build in the cloud
3. Develop using the same workflow above

</details>

---

## Quick Start (manual install)

### Prerequisites

* **Python ≥ 3.10**
* **GNU Make** (optional, but all common workflows are available as Make targets)
* Optional: **Docker / Podman** for containerized runs

### One-liner (dev)

```bash
make venv install serve
```

What it does:

1. Creates / activates a `.venv` in your home folder `~/.venv/mcpgateway`
2. Installs the gateway and necessary dependencies
3. Launches **Gunicorn** (Uvicorn workers) on [http://localhost:4444](http://localhost:4444)

For development, you can use:

```bash
make install-dev # Install development dependencies, ex: linters and test harness
make lint          # optional: run style checks (ruff, mypy, etc.)
```

### Containerized (self-signed TLS)

## Container Runtime Support

This project supports both Docker and Podman. The Makefile automatically detects
which runtime is available and handles image naming differences.

### Auto-detection
```bash
make container-build  # Uses podman if available, otherwise docker

> You can use docker or podman, ex:

```bash
make podman            # build production image
make podman-run-ssl    # run at https://localhost:4444
# or listen on port 4444 on your host directly, adds --network=host to podman
make podman-run-ssl-host
```

### Smoke-test the API

```bash
curl -k -sX GET \
     -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://localhost:4444/tools | jq
```

You should receive `[]` until you register a tool.

---

## Installation

### Via Make

```bash
make venv install          # create .venv + install deps
make serve                 # gunicorn on :4444
```

### UV (alternative)

```bash
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]' # IMPORTANT: in zsh, quote to disable glob expansion!
```

### pip (alternative)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Optional (PostgreSQL adapter)

You can configure the gateway with SQLite, PostgreSQL (or any other compatible database) in .env.

When using PostgreSQL, you need to install `psycopg2` driver.

```bash
uv pip install psycopg2-binary   # dev convenience
# or
uv pip install psycopg2          # production build
```

#### Quick Postgres container

```bash
docker run --name mcp-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -e POSTGRES_DB=mcp \
  -p 5432:5432 -d postgres
```

A `make compose-up` target is provided along with a [docker-compose.yml](docker-compose.yml) file to make this process simpler.

---

## 🔄 Upgrading to v0.7.0

> **⚠️ CRITICAL**: Version 0.7.0 introduces comprehensive multi-tenancy and requires database migration.

### Backup Your Data First
Before upgrading to v0.7.0, **always** backup your database, environment configuration, and export your settings:

```bash
# Backup database (SQLite example)
cp mcp.db mcp.db.backup.$(date +%Y%m%d_%H%M%S)

# Backup existing .env file
cp .env .env.bak

# Export configuration via Admin UI or API
curl -u admin:changeme "http://localhost:4444/admin/export/configuration" \
     -o config_backup_$(date +%Y%m%d_%H%M%S).json
```

### Migration Process
1. **Update `.env`** - Copy new settings: `cp .env.example .env` then configure `PLATFORM_ADMIN_EMAIL` and other required multi-tenancy settings
2. **Run migration** - Database schema updates automatically: `python3 -m mcpgateway.bootstrap_db`
3. **Verify migration** - Use verification script: `python3 scripts/verify_multitenancy_0_7_0_migration.py`

### If Migration Fails
If the database migration fails or you encounter issues:
1. **Restore database backup**: `cp mcp.db.backup.YYYYMMDD_HHMMSS mcp.db`
2. **Restore .env backup**: `cp .env.bak .env`
3. **Delete corrupted database**: `rm mcp.db` (if migration partially completed)
4. **Restore configuration**: Import your exported configuration via Admin UI

### Complete Migration Guide
For detailed upgrade instructions, troubleshooting, and rollback procedures, see:
- **📖 [MIGRATION-0.7.0.md](MIGRATION-0.7.0.md)** - Complete step-by-step upgrade guide
- **🏗️ [Multi-tenancy Architecture](https://ibm.github.io/mcp-context-forge/architecture/multitenancy/)** - Understanding the new system

---

## Configuration (`.env` or env vars)

> ⚠️ If any required `.env` variable is missing or invalid, the gateway will fail fast at startup with a validation error via Pydantic.

You can get started by copying the provided [.env.example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example) to `.env` and making the necessary edits to fit your environment.

<details>
<summary><strong>🔧 Environment Configuration Variables</strong></summary>

### Basic

| Setting            | Description                              | Default                | Options                |
|--------------------|------------------------------------------|------------------------|------------------------|
| `APP_NAME`         | Gateway / OpenAPI title                  | `MCP Gateway`          | string                 |
| `HOST`             | Bind address for the app                 | `127.0.0.1`            | IPv4/IPv6              |
| `PORT`             | Port the server listens on               | `4444`                 | 1-65535                |
| `DATABASE_URL`     | SQLAlchemy connection URL                | `sqlite:///./mcp.db`   | any SQLAlchemy dialect |
| `APP_ROOT_PATH`    | Subpath prefix for app (e.g. `/gateway`) | (empty)                | string                 |
| `TEMPLATES_DIR`    | Path to Jinja2 templates                 | `mcpgateway/templates` | path                   |
| `STATIC_DIR`       | Path to static files                     | `mcpgateway/static`    | path                   |
| `PROTOCOL_VERSION` | MCP protocol version supported           | `2025-03-26`           | string                 |
| `FORGE_CONTENT_TYPE` | Content-Type for outgoing requests to Forge | `application/json`  | `application/json`, `application/x-www-form-urlencoded` |

> 💡 Use `APP_ROOT_PATH=/foo` if reverse-proxying under a subpath like `https://host.com/foo/`.
> 🔄 Use `FORGE_CONTENT_TYPE=application/x-www-form-urlencoded` to send URL-encoded form data instead of JSON.

### Authentication

| Setting                     | Description                                                                  | Default             | Options     |
|-----------------------------|------------------------------------------------------------------------------|---------------------|-------------|
| `BASIC_AUTH_USER`           | Username for Admin UI login and HTTP Basic authentication                    | `admin`             | string      |
| `BASIC_AUTH_PASSWORD`       | Password for Admin UI login and HTTP Basic authentication                    | `changeme`          | string      |
| `PLATFORM_ADMIN_EMAIL`      | Email for bootstrap platform admin user (auto-created with admin privileges) | `admin@example.com` | string      |
| `AUTH_REQUIRED`             | Require authentication for all API routes                                    | `true`              | bool        |
| `JWT_ALGORITHM`             | Algorithm used to sign the JWTs (`HS256` is default, HMAC-based)             | `HS256`             | PyJWT algs  |
| `JWT_SECRET_KEY`            | Secret key used to **sign JWT tokens** for API access                        | `my-test-key`       | string      |
| `JWT_PUBLIC_KEY_PATH`       | If an asymmetric algorithm is used, a public key is required                 | (empty)             | path to pem |
| `JWT_PRIVATE_KEY_PATH`      | If an asymmetric algorithm is used, a private key is required                | (empty)             | path to pem |
| `JWT_AUDIENCE`              | JWT audience claim for token validation                                      | `mcpgateway-api`    | string      |
| `JWT_AUDIENCE_VERIFICATION` | Disables jwt audience verification (useful for DCR)                          | `true`              | boolean     |
| `JWT_ISSUER`                | JWT issuer claim for token validation                                        | `mcpgateway`        | string      |
| `TOKEN_EXPIRY`              | Expiry of generated JWTs in minutes                                          | `10080`             | int > 0     |
| `REQUIRE_TOKEN_EXPIRATION`  | Require all JWT tokens to have expiration claims                             | `false`             | bool        |
| `AUTH_ENCRYPTION_SECRET`    | Passphrase used to derive AES key for encrypting tool auth headers           | `my-test-salt`      | string      |
| `OAUTH_REQUEST_TIMEOUT`     | OAuth request timeout in seconds                                             | `30`                | int > 0     |
| `OAUTH_MAX_RETRIES`         | Maximum retries for OAuth token requests                                     | `3`                 | int > 0     |
| `OAUTH_DEFAULT_TIMEOUT`         | Default OAuth token timeout in seconds                                     | `3600`                 | int > 0     |

> 🔐 `BASIC_AUTH_USER`/`PASSWORD` are used for:
>
> * Logging into the web-based Admin UI
> * Accessing APIs via Basic Auth (`curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"`)
>
> 🔑 `JWT_SECRET_KEY` is used to:
>
> * Sign JSON Web Tokens (`Authorization: Bearer <token>`)
> * Generate tokens via:
>
>   ```bash
>   export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key)
>   echo $MCPGATEWAY_BEARER_TOKEN
>   ```
> * Tokens allow non-interactive API clients to authenticate securely.
>
> 🧪 Set `AUTH_REQUIRED=false` during development if you want to disable all authentication (e.g. for local testing or open APIs) or clients that don't support SSE authentication.
> In production, you should use the SSE to stdio `mcpgateway-wrapper` for such tools that don't support authenticated SSE, while still ensuring the gateway uses authentication.
>
> 🔐 `AUTH_ENCRYPTION_SECRET` is used to encrypt and decrypt tool authentication credentials (`auth_value`).
> You must set the same value across environments to decode previously stored encrypted auth values.
> Recommended: use a long, random string.

### UI Features

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `MCPGATEWAY_UI_ENABLED`        | Enable the interactive Admin dashboard | `false` | bool    |
| `MCPGATEWAY_ADMIN_API_ENABLED` | Enable API endpoints for admin ops     | `false` | bool    |
| `MCPGATEWAY_BULK_IMPORT_ENABLED` | Enable bulk import endpoint for tools | `true`  | bool    |
| `MCPGATEWAY_BULK_IMPORT_MAX_TOOLS` | Maximum number of tools per bulk import request | `200` | int |
| `MCPGATEWAY_BULK_IMPORT_RATE_LIMIT` | Rate limit for bulk import endpoint (requests per minute) | `10` | int |
| `MCPGATEWAY_UI_TOOL_TEST_TIMEOUT` | Tool test timeout in milliseconds for the admin UI | `60000` | int |
| `MCPCONTEXT_UI_ENABLED`        | Enable ContextForge UI features        | `true`  | bool    |

> 🖥️ Set both UI and Admin API to `false` to disable management UI and APIs in production.
> 📥 The bulk import endpoint allows importing up to 200 tools in a single request via `/admin/tools/import`.
> ⏱️ Increase `MCPGATEWAY_UI_TOOL_TEST_TIMEOUT` if your tools make multiple API calls or operate in high-latency environments.

### A2A (Agent-to-Agent) Features

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `MCPGATEWAY_A2A_ENABLED`       | Enable A2A agent features             | `true`  | bool    |
| `MCPGATEWAY_A2A_MAX_AGENTS`    | Maximum number of A2A agents allowed  | `100`   | int     |
| `MCPGATEWAY_A2A_DEFAULT_TIMEOUT` | Default timeout for A2A HTTP requests (seconds) | `30` | int |
| `MCPGATEWAY_A2A_MAX_RETRIES`   | Maximum retry attempts for A2A calls  | `3`     | int     |
| `MCPGATEWAY_A2A_METRICS_ENABLED` | Enable A2A agent metrics collection | `true`  | bool    |

> 🤖 **A2A Integration**: Register external AI agents (OpenAI, Anthropic, custom) and expose them as MCP tools
> 📊 **Metrics**: Track agent performance, success rates, and response times
> 🔒 **Security**: Encrypted credential storage and configurable authentication
> 🎛️ **Admin UI**: Dedicated tab for agent management with test functionality

**A2A Configuration Effects:**
- `MCPGATEWAY_A2A_ENABLED=false`: Completely disables A2A features (API endpoints return 404, admin tab hidden)
- `MCPGATEWAY_A2A_METRICS_ENABLED=false`: Disables metrics collection while keeping functionality

### LLM Chat MCP Client

The LLM Chat MCP Client allows you to interact with MCP servers using conversational AI from multiple LLM providers. This feature enables natural language interaction with tools, resources, and prompts exposed by MCP servers.

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `LLMCHAT_ENABLED`             | Enable LLM Chat functionality          | `false` | bool    |
| `LLM_PROVIDER`                | LLM provider selection                 | `azure_openai` | `azure_openai`, `openai`, `anthropic`, `aws_bedrock`, `ollama` |

**Azure OpenAI Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `AZURE_OPENAI_ENDPOINT`       | Azure OpenAI endpoint URL              | (none)  | string  |
| `AZURE_OPENAI_API_KEY`        | Azure OpenAI API key                   | (none)  | string  |
| `AZURE_OPENAI_DEPLOYMENT`     | Azure OpenAI deployment name           | (none)  | string  |
| `AZURE_OPENAI_API_VERSION`    | Azure OpenAI API version               | `2024-02-15-preview` | string |
| `AZURE_OPENAI_TEMPERATURE`    | Sampling temperature                   | `0.7`   | float (0.0-2.0) |
| `AZURE_OPENAI_MAX_TOKENS`     | Maximum tokens to generate             | (none)  | int     |

**OpenAI Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `OPENAI_API_KEY`              | OpenAI API key                         | (none)  | string  |
| `OPENAI_MODEL`                | OpenAI model name                      | `gpt-4o-mini` | string |
| `OPENAI_BASE_URL`             | Base URL for OpenAI-compatible endpoints | (none) | string  |
| `OPENAI_TEMPERATURE`          | Sampling temperature                   | `0.7`   | float (0.0-2.0) |
| `OPENAI_MAX_RETRIES`          | Maximum number of retries              | `2`     | int     |

**Anthropic Claude Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `ANTHROPIC_API_KEY`           | Anthropic API key                      | (none)  | string  |
| `ANTHROPIC_MODEL`             | Claude model name                      | `claude-3-5-sonnet-20241022` | string |
| `ANTHROPIC_TEMPERATURE`       | Sampling temperature                   | `0.7`   | float (0.0-1.0) |
| `ANTHROPIC_MAX_TOKENS`        | Maximum tokens to generate             | `4096`  | int     |
| `ANTHROPIC_MAX_RETRIES`       | Maximum number of retries              | `2`     | int     |

**AWS Bedrock Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `AWS_BEDROCK_MODEL_ID`        | Bedrock model ID                       | (none)  | string  |
| `AWS_BEDROCK_REGION`          | AWS region name                        | `us-east-1` | string |
| `AWS_BEDROCK_TEMPERATURE`     | Sampling temperature                   | `0.7`   | float (0.0-1.0) |
| `AWS_BEDROCK_MAX_TOKENS`      | Maximum tokens to generate             | `4096`  | int     |
| `AWS_ACCESS_KEY_ID`           | AWS access key ID (optional)           | (none)  | string  |
| `AWS_SECRET_ACCESS_KEY`       | AWS secret access key (optional)       | (none)  | string  |
| `AWS_SESSION_TOKEN`           | AWS session token (optional)           | (none)  | string  |


**IBM WatsonX AI**
| Setting                 | Description                     | Default                        | Options         |
| ----------------------- | --------------------------------| ------------------------------ | ----------------|
| `WATSONX_URL`           | watsonx url                     | (none)                         | string          |
| `WATSONX_APIKEY`        | API key                         | (none)                         | string          |
| `WATSONX_PROJECT_ID`    | Project Id for WatsonX          | (none)                         | string          |
| `WATSONX_MODEL_ID`      | Watsonx model id                | `ibm/granite-13b-chat-v2`      | string          |
| `WATSONX_TEMPERATURE`   | temperature (optional)          | `0.7`                          | float (0.0-1.0) |


**Ollama Configuration:**

| Setting                        | Description                            | Default | Options |
| ------------------------------ | -------------------------------------- | ------- | ------- |
| `OLLAMA_BASE_URL`             | Ollama base URL                        | `http://localhost:11434` | string |
| `OLLAMA_MODEL`                | Ollama model name                      | `llama3.2` | string |
| `OLLAMA_TEMPERATURE`          | Sampling temperature                   | `0.7`   | float (0.0-2.0) |

> 🤖 **LLM Chat Integration**: Chat with MCP servers using natural language powered by Azure OpenAI, OpenAI, Anthropic Claude, AWS Bedrock, or Ollama
> 🔧 **Flexible Providers**: Switch between different LLM providers without changing your MCP integration
> 🔒 **Security**: API keys and credentials are securely stored and never exposed in responses
> 🎛️ **Admin UI**: Dedicated LLM Chat tab in the admin interface for interactive conversations

**LLM Chat Configuration Effects:**
- `LLMCHAT_ENABLED=false` (default): Completely disables LLM Chat features (API endpoints return 404, admin tab hidden)
- `LLMCHAT_ENABLED=true`: Enables LLM Chat functionality with the selected provider

**Provider Requirements:**
- **Azure OpenAI**: Requires `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_DEPLOYMENT`
- **OpenAI**: Requires `OPENAI_API_KEY`
- **Anthropic**: Requires `ANTHROPIC_API_KEY` and `pip install langchain-anthropic`
- **AWS Bedrock**: Requires `AWS_BEDROCK_MODEL_ID` and `pip install langchain-aws boto3`. Uses AWS credential chain if explicit credentials not provided.
**IBM WatsonX AI**: Requires `WATSONX_URL`, `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_MODEL_ID` and `pip install langchain-ibm `.
- **Ollama**: Requires local Ollama instance running (default: `http://localhost:11434`)

**Redis Configurations:** For maintaining Chat Sessions in multi-worker environment

| Setting                              | Description                                | Default | Options |
| -------------------------------------| -------------------------------------------| ------- | ------- |
| `LLMCHAT_SESSION_TTL`                | Seconds for active_session key TTL         | `300`   | int     |
| `LLMCHAT_SESSION_LOCK_TTL`           | Seconds for lock expiry                    | `30`    | int     |
| `LLMCHAT_SESSION_LOCK_RETRIES`       | How many times to poll while waiting       | `10`    | int     |
| `LLMCHAT_SESSION_LOCK_WAIT`          | Seconds between polls                      | `0.2`   | float   |
| `LLMCHAT_CHAT_HISTORY_TTL`           | Seconds for chat history expiry            | `3600`  | int     |
| `LLMCHAT_CHAT_HISTORY_MAX_MESSAGES`  | Maximum message history to store per user  | `50`    | int     |

**Documentation:**
- [LLM Chat Guide](https://ibm.github.io/mcp-context-forge/using/clients/llm-chat) - Complete LLM Chat setup and provider configuration

### Email-Based Authentication & User Management

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `EMAIL_AUTH_ENABLED`          | Enable email-based authentication system         | `true`                | bool    |
| `PLATFORM_ADMIN_EMAIL`        | Email for bootstrap platform admin user          | `admin@example.com`   | string  |
| `PLATFORM_ADMIN_PASSWORD`     | Password for bootstrap platform admin user       | `changeme`            | string  |
| `PLATFORM_ADMIN_FULL_NAME`    | Full name for bootstrap platform admin user      | `Platform Administrator` | string |
| `ARGON2ID_TIME_COST`          | Argon2id time cost (iterations)                  | `3`                   | int > 0 |
| `ARGON2ID_MEMORY_COST`        | Argon2id memory cost in KiB                      | `65536`               | int > 0 |
| `ARGON2ID_PARALLELISM`        | Argon2id parallelism (threads)                   | `1`                   | int > 0 |
| `PASSWORD_MIN_LENGTH`         | Minimum password length                           | `8`                   | int > 0 |
| `PASSWORD_REQUIRE_UPPERCASE`  | Require uppercase letters in passwords           | `false`               | bool    |
| `PASSWORD_REQUIRE_LOWERCASE`  | Require lowercase letters in passwords           | `false`               | bool    |
| `PASSWORD_REQUIRE_NUMBERS`    | Require numbers in passwords                     | `false`               | bool    |
| `PASSWORD_REQUIRE_SPECIAL`    | Require special characters in passwords          | `false`               | bool    |
| `MAX_FAILED_LOGIN_ATTEMPTS`   | Maximum failed login attempts before lockout     | `5`                   | int > 0 |
| `ACCOUNT_LOCKOUT_DURATION_MINUTES` | Account lockout duration in minutes        | `30`                  | int > 0 |

### MCP Client Authentication

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `MCP_CLIENT_AUTH_ENABLED`     | Enable JWT authentication for MCP client operations | `true`            | bool    |
| `TRUST_PROXY_AUTH`            | Trust proxy authentication headers               | `false`               | bool    |
| `PROXY_USER_HEADER`           | Header containing authenticated username from proxy | `X-Authenticated-User` | string |

> 🔐 **MCP Client Auth**: When `MCP_CLIENT_AUTH_ENABLED=false`, you must set `TRUST_PROXY_AUTH=true` if using a trusted authentication proxy. This is a security-sensitive setting.

### SSO (Single Sign-On) Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_ENABLED`                 | Master switch for Single Sign-On authentication  | `false`               | bool    |
| `SSO_AUTO_CREATE_USERS`       | Automatically create users from SSO providers    | `true`                | bool    |
| `SSO_TRUSTED_DOMAINS`         | Trusted email domains (JSON array)               | `[]`                  | JSON array |
| `SSO_PRESERVE_ADMIN_AUTH`     | Preserve local admin authentication when SSO enabled | `true`            | bool    |
| `SSO_REQUIRE_ADMIN_APPROVAL`  | Require admin approval for new SSO registrations | `false`               | bool    |
| `SSO_ISSUERS`                 | Optional JSON array of issuer URLs for SSO providers | (none)            | JSON array |

**GitHub OAuth:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_GITHUB_ENABLED`          | Enable GitHub OAuth authentication               | `false`               | bool    |
| `SSO_GITHUB_CLIENT_ID`        | GitHub OAuth client ID                           | (none)                | string  |
| `SSO_GITHUB_CLIENT_SECRET`    | GitHub OAuth client secret                       | (none)                | string  |
| `SSO_GITHUB_ADMIN_ORGS`       | GitHub orgs granting admin privileges (JSON)     | `[]`                  | JSON array |

**Google OAuth:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_GOOGLE_ENABLED`          | Enable Google OAuth authentication               | `false`               | bool    |
| `SSO_GOOGLE_CLIENT_ID`        | Google OAuth client ID                           | (none)                | string  |
| `SSO_GOOGLE_CLIENT_SECRET`    | Google OAuth client secret                       | (none)                | string  |
| `SSO_GOOGLE_ADMIN_DOMAINS`    | Google admin domains (JSON)                      | `[]`                  | JSON array |

**IBM Security Verify OIDC:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_IBM_VERIFY_ENABLED`      | Enable IBM Security Verify OIDC authentication   | `false`               | bool    |
| `SSO_IBM_VERIFY_CLIENT_ID`    | IBM Security Verify client ID                    | (none)                | string  |
| `SSO_IBM_VERIFY_CLIENT_SECRET` | IBM Security Verify client secret               | (none)                | string  |
| `SSO_IBM_VERIFY_ISSUER`       | IBM Security Verify OIDC issuer URL             | (none)                | string  |

**Keycloak OIDC:**
| Setting                              | Description                                      | Default                    | Options |
| ------------------------------------ | ------------------------------------------------ | -------------------------- | ------- |
| `SSO_KEYCLOAK_ENABLED`              | Enable Keycloak OIDC authentication              | `false`                    | bool    |
| `SSO_KEYCLOAK_BASE_URL`             | Keycloak base URL                                | (none)                     | string  |
| `SSO_KEYCLOAK_REALM`                | Keycloak realm name                              | `master`                   | string  |
| `SSO_KEYCLOAK_CLIENT_ID`            | Keycloak client ID                               | (none)                     | string  |
| `SSO_KEYCLOAK_CLIENT_SECRET`        | Keycloak client secret                           | (none)                     | string  |
| `SSO_KEYCLOAK_MAP_REALM_ROLES`      | Map Keycloak realm roles to gateway teams        | `true`                     | bool    |
| `SSO_KEYCLOAK_MAP_CLIENT_ROLES`     | Map Keycloak client roles to gateway RBAC        | `false`                    | bool    |
| `SSO_KEYCLOAK_USERNAME_CLAIM`       | JWT claim for username                           | `preferred_username`       | string  |
| `SSO_KEYCLOAK_EMAIL_CLAIM`          | JWT claim for email                              | `email`                    | string  |
| `SSO_KEYCLOAK_GROUPS_CLAIM`         | JWT claim for groups/roles                       | `groups`                   | string  |

**Microsoft Entra ID OIDC:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_ENTRA_ENABLED`           | Enable Microsoft Entra ID OIDC authentication    | `false`               | bool    |
| `SSO_ENTRA_CLIENT_ID`         | Microsoft Entra ID client ID                     | (none)                | string  |
| `SSO_ENTRA_CLIENT_SECRET`     | Microsoft Entra ID client secret                 | (none)                | string  |
| `SSO_ENTRA_TENANT_ID`         | Microsoft Entra ID tenant ID                     | (none)                | string  |

**Generic OIDC Provider (Auth0, Authentik, etc.):**
| Setting                              | Description                                      | Default                    | Options |
| ------------------------------------ | ------------------------------------------------ | -------------------------- | ------- |
| `SSO_GENERIC_ENABLED`               | Enable generic OIDC provider authentication      | `false`                    | bool    |
| `SSO_GENERIC_PROVIDER_ID`           | Provider ID (e.g., keycloak, auth0, authentik)   | (none)                     | string  |
| `SSO_GENERIC_DISPLAY_NAME`          | Display name shown on login page                 | (none)                     | string  |
| `SSO_GENERIC_CLIENT_ID`             | Generic OIDC client ID                           | (none)                     | string  |
| `SSO_GENERIC_CLIENT_SECRET`         | Generic OIDC client secret                       | (none)                     | string  |
| `SSO_GENERIC_AUTHORIZATION_URL`     | Authorization endpoint URL                       | (none)                     | string  |
| `SSO_GENERIC_TOKEN_URL`             | Token endpoint URL                               | (none)                     | string  |
| `SSO_GENERIC_USERINFO_URL`          | Userinfo endpoint URL                            | (none)                     | string  |
| `SSO_GENERIC_ISSUER`                | OIDC issuer URL                                  | (none)                     | string  |
| `SSO_GENERIC_SCOPE`                 | OAuth scopes (space-separated)                   | `openid profile email`     | string  |

**Okta OIDC:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_OKTA_ENABLED`            | Enable Okta OIDC authentication                  | `false`               | bool    |
| `SSO_OKTA_CLIENT_ID`          | Okta client ID                                   | (none)                | string  |
| `SSO_OKTA_CLIENT_SECRET`      | Okta client secret                               | (none)                | string  |
| `SSO_OKTA_ISSUER`             | Okta issuer URL                                  | (none)                | string  |

**SSO Admin Assignment:**
| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `SSO_AUTO_ADMIN_DOMAINS`      | Email domains that automatically get admin privileges | `[]`             | JSON array |

### OAuth 2.0 Dynamic Client Registration (DCR) & PKCE

ContextForge implements **OAuth 2.0 Dynamic Client Registration (RFC 7591)** and **PKCE (RFC 7636)** for seamless integration with OAuth-protected MCP servers and upstream API gateways like HyperMCP.

**Key Features:**
- ✅ Automatic client registration with Authorization Servers (no manual credential configuration)
- ✅ Authorization Server metadata discovery (RFC 8414)
- ✅ PKCE (Proof Key for Code Exchange) enabled for all Authorization Code flows
- ✅ Support for public clients (PKCE-only, no client secret)
- ✅ Encrypted credential storage with Fernet encryption
- ✅ Configurable issuer allowlist for security

| Setting                                     | Description                                                    | Default                        | Options       |
|--------------------------------------------|----------------------------------------------------------------|--------------------------------|---------------|
| `DCR_ENABLED`                              | Enable Dynamic Client Registration (RFC 7591)                  | `true`                         | bool          |
| `DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS` | Auto-register when gateway has issuer but no client_id         | `true`                         | bool          |
| `DCR_DEFAULT_SCOPES`                       | Default OAuth scopes to request during DCR                     | `["mcp:read"]`                 | JSON array    |
| `DCR_ALLOWED_ISSUERS`                      | Allowlist of trusted issuer URLs (empty = allow any)           | `[]`                           | JSON array    |
| `DCR_TOKEN_ENDPOINT_AUTH_METHOD`           | Token endpoint auth method                                     | `client_secret_basic`          | `client_secret_basic`, `client_secret_post`, `none` |
| `DCR_METADATA_CACHE_TTL`                   | AS metadata cache TTL in seconds                               | `3600`                         | int           |
| `DCR_CLIENT_NAME_TEMPLATE`                 | Template for client_name in DCR requests                       | `MCP Gateway ({gateway_name})` | string        |
| `OAUTH_DISCOVERY_ENABLED`                  | Enable AS metadata discovery (RFC 8414)                        | `true`                         | bool          |
| `OAUTH_PREFERRED_CODE_CHALLENGE_METHOD`    | PKCE code challenge method                                     | `S256`                         | `S256`, `plain` |
| `JWT_AUDIENCE_VERIFICATION`                | JWT audience verification (disable for DCR)                    | `true`                         | bool          |

**Documentation:**
- [DCR Configuration Guide](https://ibm.github.io/mcp-context-forge/manage/dcr/) - Complete DCR setup and troubleshooting
- [OAuth 2.0 Integration](https://ibm.github.io/mcp-context-forge/manage/oauth/) - OAuth configuration and PKCE details
- [HyperMCP Tutorial](https://ibm.github.io/mcp-context-forge/tutorials/dcr-hyprmcp/) - End-to-end DCR setup with HyperMCP gateway

### Personal Teams Configuration

| Setting                                  | Description                                      | Default    | Options |
| ---------------------------------------- | ------------------------------------------------ | ---------- | ------- |
| `AUTO_CREATE_PERSONAL_TEAMS`             | Enable automatic personal team creation for new users | `true`   | bool    |
| `PERSONAL_TEAM_PREFIX`                   | Personal team naming prefix                      | `personal` | string  |
| `MAX_TEAMS_PER_USER`                     | Maximum number of teams a user can belong to    | `50`       | int > 0 |
| `MAX_MEMBERS_PER_TEAM`                   | Maximum number of members per team               | `100`      | int > 0 |
| `INVITATION_EXPIRY_DAYS`                 | Number of days before team invitations expire   | `7`        | int > 0 |
| `REQUIRE_EMAIL_VERIFICATION_FOR_INVITES` | Require email verification for team invitations | `true`     | bool    |

### MCP Server Catalog

> 🆕 **New in v0.7.0**: The MCP Server Catalog allows you to define a catalog of pre-configured MCP servers in a YAML file for easy discovery and management via the Admin UI.

| Setting                              | Description                                      | Default            | Options |
| ------------------------------------ | ------------------------------------------------ | ------------------ | ------- |
| `MCPGATEWAY_CATALOG_ENABLED`        | Enable MCP server catalog feature                | `true`             | bool    |
| `MCPGATEWAY_CATALOG_FILE`           | Path to catalog configuration file               | `mcp-catalog.yml`  | string  |
| `MCPGATEWAY_CATALOG_AUTO_HEALTH_CHECK` | Automatically health check catalog servers    | `true`             | bool    |
| `MCPGATEWAY_CATALOG_CACHE_TTL`      | Catalog cache TTL in seconds                     | `3600`             | int > 0 |
| `MCPGATEWAY_CATALOG_PAGE_SIZE`      | Number of catalog servers per page               | `12`               | int > 0 |

**Key Features:**
- 🔄 Refresh Button - Manually refresh catalog without page reload
- 🔍 Debounced Search - Optimized search with 300ms debounce
- 📝 Custom Server Names - Specify custom names when registering
- 🔌 Transport Detection - Auto-detect SSE, WebSocket, or HTTP transports
- 🔐 OAuth Support - Register OAuth servers and configure later
- ⚡ Better Error Messages - User-friendly errors for common issues

**Documentation:**
- [MCP Server Catalog Guide](https://ibm.github.io/mcp-context-forge/manage/catalog/) - Complete catalog setup and configuration

### Security

| Setting                   | Description                    | Default                                        | Options    |
| ------------------------- | ------------------------------ | ---------------------------------------------- | ---------- |
| `SKIP_SSL_VERIFY`         | Skip upstream TLS verification | `false`                                        | bool       |
| `ENVIRONMENT`             | Deployment environment (affects security defaults) | `development`                              | `development`/`production` |
| `APP_DOMAIN`              | Domain for production CORS origins | `localhost`                                 | string     |
| `ALLOWED_ORIGINS`         | CORS allow-list                | Auto-configured by environment                 | JSON array |
| `CORS_ENABLED`            | Enable CORS                    | `true`                                         | bool       |
| `CORS_ALLOW_CREDENTIALS`  | Allow credentials in CORS      | `true`                                         | bool       |
| `SECURE_COOKIES`          | Force secure cookie flags     | `true`                                         | bool       |
| `COOKIE_SAMESITE`         | Cookie SameSite attribute      | `lax`                                          | `strict`/`lax`/`none` |
| `SECURITY_HEADERS_ENABLED` | Enable security headers middleware | `true`                                     | bool       |
| `X_FRAME_OPTIONS`         | X-Frame-Options header value   | `DENY`                                         | `DENY`/`SAMEORIGIN` |
| `X_CONTENT_TYPE_OPTIONS_ENABLED` | Enable X-Content-Type-Options: nosniff header | `true`                           | bool       |
| `X_XSS_PROTECTION_ENABLED` | Enable X-XSS-Protection header | `true`                                         | bool       |
| `X_DOWNLOAD_OPTIONS_ENABLED` | Enable X-Download-Options: noopen header | `true`                              | bool       |
| `HSTS_ENABLED`            | Enable HSTS header             | `true`                                         | bool       |
| `HSTS_MAX_AGE`            | HSTS max age in seconds        | `31536000`                                     | int        |
| `HSTS_INCLUDE_SUBDOMAINS` | Include subdomains in HSTS header | `true`                                      | bool       |
| `REMOVE_SERVER_HEADERS`   | Remove server identification   | `true`                                         | bool       |
| `DOCS_ALLOW_BASIC_AUTH`   | Allow Basic Auth for docs (in addition to JWT)         | `false`                                        | bool       |
| `MIN_SECRET_LENGTH`       | Minimum length for secret keys (JWT, encryption) | `32`                                | int        |
| `MIN_PASSWORD_LENGTH`     | Minimum length for passwords   | `12`                                           | int        |
| `REQUIRE_STRONG_SECRETS`  | Enforce strong secrets (fail startup on weak secrets) | `false`                        | bool       |

> **CORS Configuration**: When `ENVIRONMENT=development`, CORS origins are automatically configured for common development ports (3000, 8080, gateway port). In production, origins are constructed from `APP_DOMAIN` (e.g., `https://yourdomain.com`, `https://app.yourdomain.com`). You can override this by explicitly setting `ALLOWED_ORIGINS`.
>
> **Security Headers**: The gateway automatically adds configurable security headers to all responses including CSP, X-Frame-Options, X-Content-Type-Options, X-Download-Options, and HSTS (on HTTPS). All headers can be individually enabled/disabled. Sensitive server headers are removed.
>
> **Security Validation**: Set `REQUIRE_STRONG_SECRETS=true` to enforce minimum lengths for JWT secrets and passwords at startup. This helps prevent weak credentials in production. Default is `false` for backward compatibility.
>
> **iframe Embedding**: By default, `X-Frame-Options: DENY` prevents iframe embedding for security. To allow embedding, set `X_FRAME_OPTIONS=SAMEORIGIN` (same domain) or disable with `X_FRAME_OPTIONS=""`. Also update CSP `frame-ancestors` directive if needed.
>
> **Cookie Security**: Authentication cookies are automatically configured with HttpOnly, Secure (in production), and SameSite attributes for CSRF protection.
>
> Note: do not quote the ALLOWED_ORIGINS values, this needs to be valid JSON, such as:
> ALLOWED_ORIGINS=["http://localhost", "http://localhost:4444"]
>
> Documentation endpoints (`/docs`, `/redoc`, `/openapi.json`) are always protected by authentication.
> By default, they require Bearer token authentication. Setting `DOCS_ALLOW_BASIC_AUTH=true` enables HTTP Basic Authentication as an additional method using the same credentials as `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`.

### Ed25519 Certificate Signing

MCP Gateway supports **Ed25519 digital signatures** for certificate validation and integrity verification. This cryptographic signing mechanism ensures that CA certificates used by the gateway are authentic and haven't been tampered with.

| Setting                     | Description                                      | Default | Options |
| --------------------------- | ------------------------------------------------ | ------- | ------- |
| `ENABLE_ED25519_SIGNING`    | Enable Ed25519 signing for certificates          | `false` | bool    |
| `ED25519_PRIVATE_KEY`       | Ed25519 private key for signing (PEM format)     | (none)  | string  |
| `PREV_ED25519_PRIVATE_KEY`  | Previous Ed25519 private key for key rotation    | (none)  | string  |

**How It Works:**

1. **Certificate Signing** - When `ENABLE_ED25519_SIGNING=true`, the gateway signs the CA certificate of each MCP server/gateway using the Ed25519 private key.

2. **Certificate Validation** - Before using a CA certificate for subsequent calls, the gateway validates its signature to ensure authenticity and integrity.

3. **Disabled Mode** - When `ENABLE_ED25519_SIGNING=false`, certificates are neither signed nor validated (default behavior).

**Key Generation:**

```bash
# Generate a new Ed25519 key pair
python mcpgateway/utils/generate_keys.py

# Output will show:
# - Private key (set this to ED25519_PRIVATE_KEY)
```

**Key Rotation:**

To rotate keys without invalidating existing signed certificates:

1. Move the current `ED25519_PRIVATE_KEY` value to `PREV_ED25519_PRIVATE_KEY`
2. Generate a new key pair using the command above
3. Set the new private key to `ED25519_PRIVATE_KEY`
4. The gateway will automatically re-sign valid certificates at the point of key change

**Example Configuration:**

```bash
# Enable Ed25519 signing
ENABLE_ED25519_SIGNING=true

# Current signing key (PEM format)
ED25519_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIJ5pW... (your key here)
-----END PRIVATE KEY-----"

# Previous key for rotation (optional)
PREV_ED25519_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIOld... (old key here)
-----END PRIVATE KEY-----"
```

> 🔐 **Security Best Practices:**
> - Store private keys securely (use secrets management tools like Vault, AWS Secrets Manager, etc.)
> - Rotate keys periodically (recommended: every 90-180 days)
> - Never commit private keys to version control
> - Use environment variables or encrypted config files
>
> 🔑 **Public Key Derivation:**
> - Public keys are automatically derived from private keys
> - No need to configure public keys separately
> - Both `ED25519_PUBLIC_KEY` and `PREV_ED25519_PUBLIC_KEY` are computed at startup
>
> ⚡ **Performance:**
> - Ed25519 signing is extremely fast (~64 microseconds per signature)
> - Minimal impact on gateway performance
> - Recommended for production deployments requiring certificate integrity

### Response Compression

MCP Gateway includes automatic response compression middleware that reduces bandwidth usage by 30-70% for text-based responses (JSON, HTML, CSS, JS). Compression is negotiated automatically based on client `Accept-Encoding` headers with algorithm priority: **Brotli** (best compression) > **Zstd** (fastest) > **GZip** (universal fallback).

| Setting                       | Description                                       | Default | Options              |
| ----------------------------- | ------------------------------------------------- | ------- | -------------------- |
| `COMPRESSION_ENABLED`         | Enable response compression                       | `true`  | bool                 |
| `COMPRESSION_MINIMUM_SIZE`    | Minimum response size in bytes to compress        | `500`   | int (0=compress all) |
| `COMPRESSION_GZIP_LEVEL`      | GZip compression level (1=fast, 9=best)          | `6`     | int (1-9)            |
| `COMPRESSION_BROTLI_QUALITY`  | Brotli quality (0-3=fast, 4-9=balanced, 10-11=max) | `4`   | int (0-11)           |
| `COMPRESSION_ZSTD_LEVEL`      | Zstd level (1-3=fast, 4-9=balanced, 10+=slow)    | `3`     | int (1-22)           |

**Compression Behavior:**
- Automatically negotiates algorithm based on client `Accept-Encoding` header
- Only compresses responses larger than `COMPRESSION_MINIMUM_SIZE` bytes (small responses not worth compression overhead)
- Adds `Vary: Accept-Encoding` header for proper cache behavior
- No client changes required (browsers/clients handle decompression automatically)
- Typical compression ratios: JSON responses 40-60%, HTML responses 50-70%

**Performance Impact:**
- CPU overhead: <5% (balanced settings)
- Bandwidth reduction: 30-70% for text responses
- Latency impact: <10ms for typical responses

**Testing Compression:**
```bash
# Start server
make dev

# Test Brotli (best compression)
curl -H "Accept-Encoding: br" http://localhost:8000/openapi.json -v | grep -i "content-encoding"

# Test GZip (universal fallback)
curl -H "Accept-Encoding: gzip" http://localhost:8000/openapi.json -v | grep -i "content-encoding"

# Test Zstd (fastest)
curl -H "Accept-Encoding: zstd" http://localhost:8000/openapi.json -v | grep -i "content-encoding"
```

**Tuning for Production:**
```bash
# High-traffic (optimize for speed)
COMPRESSION_GZIP_LEVEL=4
COMPRESSION_BROTLI_QUALITY=3
COMPRESSION_ZSTD_LEVEL=1

# Bandwidth-constrained (optimize for size)
COMPRESSION_GZIP_LEVEL=9
COMPRESSION_BROTLI_QUALITY=11
COMPRESSION_ZSTD_LEVEL=9
```

> **Note**: See [Scaling Guide](https://ibm.github.io/mcp-context-forge/manage/scale/) for compression performance optimization at scale.

### Logging

MCP Gateway provides flexible logging with **stdout/stderr output by default** and **optional file-based logging**. When file logging is enabled, it provides JSON formatting for structured logs and text formatting for console output.

| Setting                 | Description                        | Default           | Options                    |
| ----------------------- | ---------------------------------- | ----------------- | -------------------------- |
| `LOG_LEVEL`             | Minimum log level                  | `INFO`            | `DEBUG`...`CRITICAL`       |
| `LOG_FORMAT`            | Console log format                 | `json`            | `json`, `text`             |
| `LOG_TO_FILE`           | **Enable file logging**            | **`false`**       | **`true`, `false`**        |
| `LOG_FILE`              | Log filename (when enabled)        | `null`            | `mcpgateway.log`           |
| `LOG_FOLDER`            | Directory for log files            | `null`            | `logs`, `/var/log/gateway` |
| `LOG_FILEMODE`          | File write mode                    | `a+`              | `a+` (append), `w` (overwrite)|
| `LOG_ROTATION_ENABLED`  | **Enable log file rotation**       | **`false`**       | **`true`, `false`**        |
| `LOG_MAX_SIZE_MB`       | Max file size before rotation (MB) | `1`               | Any positive integer       |
| `LOG_BACKUP_COUNT`      | Number of backup files to keep     | `5`               | Any non-negative integer   |
| `LOG_BUFFER_SIZE_MB`    | Size of in-memory log buffer (MB)  | `1.0`             | float > 0                  |

**Logging Behavior:**
- **Default**: Logs only to **stdout/stderr** with human-readable text format
- **File Logging**: When `LOG_TO_FILE=true`, logs to **both** file (JSON format) and console (text format)
- **Log Rotation**: When `LOG_ROTATION_ENABLED=true`, files rotate at `LOG_MAX_SIZE_MB` with `LOG_BACKUP_COUNT` backup files (e.g., `.log.1`, `.log.2`)
- **Directory Creation**: Log folder is automatically created if it doesn't exist
- **Centralized Service**: All modules use the unified `LoggingService` for consistent formatting

**Example Configurations:**

```bash
# Default: stdout/stderr only (recommended for containers)
LOG_LEVEL=INFO
# No additional config needed - logs to stdout/stderr

# Optional: Enable file logging (no rotation)
LOG_TO_FILE=true
LOG_FOLDER=/var/log/mcpgateway
LOG_FILE=gateway.log
LOG_FILEMODE=a+

# Optional: Enable file logging with rotation
LOG_TO_FILE=true
LOG_ROTATION_ENABLED=true
LOG_MAX_SIZE_MB=10
LOG_BACKUP_COUNT=3
LOG_FOLDER=/var/log/mcpgateway
LOG_FILE=gateway.log
```

**Default Behavior:**
- Logs are written **only to stdout/stderr** in human-readable text format
- File logging is **disabled by default** (no files created)
- Set `LOG_TO_FILE=true` to enable optional file logging with JSON format

### Observability (OpenTelemetry)

MCP Gateway includes **vendor-agnostic OpenTelemetry support** for distributed tracing. Works with Phoenix, Jaeger, Zipkin, Tempo, DataDog, New Relic, and any OTLP-compatible backend.

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_ENABLE_OBSERVABILITY`     | Master switch for observability               | `true`                | `true`, `false`                           |
| `OTEL_SERVICE_NAME`             | Service identifier in traces                   | `mcp-gateway`         | string                                     |
| `OTEL_SERVICE_VERSION`          | Service version in traces                      | `0.9.0`               | string                                     |
| `OTEL_DEPLOYMENT_ENVIRONMENT`   | Environment tag (dev/staging/prod)            | `development`         | string                                     |
| `OTEL_TRACES_EXPORTER`          | Trace exporter backend                         | `otlp`                | `otlp`, `jaeger`, `zipkin`, `console`, `none` |
| `OTEL_RESOURCE_ATTRIBUTES`      | Custom resource attributes                     | (empty)               | `key=value,key2=value2`                   |

**OTLP Configuration** (for Phoenix, Tempo, DataDog, etc.):

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_EXPORTER_OTLP_ENDPOINT`   | OTLP collector endpoint                        | (none)                | `http://localhost:4317`                   |
| `OTEL_EXPORTER_OTLP_PROTOCOL`   | OTLP protocol                                  | `grpc`                | `grpc`, `http/protobuf`                   |
| `OTEL_EXPORTER_OTLP_HEADERS`    | Authentication headers                         | (empty)               | `api-key=secret,x-auth=token`             |
| `OTEL_EXPORTER_OTLP_INSECURE`   | Skip TLS verification                          | `true`                | `true`, `false`                           |

**Alternative Backends** (optional):

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_EXPORTER_JAEGER_ENDPOINT` | Jaeger collector endpoint                      | `http://localhost:14268/api/traces` | URL                             |
| `OTEL_EXPORTER_ZIPKIN_ENDPOINT` | Zipkin collector endpoint                      | `http://localhost:9411/api/v2/spans` | URL                            |

**Performance Tuning**:

| Setting                         | Description                                    | Default               | Options                                    |
| ------------------------------- | ---------------------------------------------- | --------------------- | ------------------------------------------ |
| `OTEL_TRACES_SAMPLER`           | Sampling strategy                              | `parentbased_traceidratio` | `always_on`, `always_off`, `traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG`       | Sample rate (0.0-1.0)                         | `0.1`                 | float (0.1 = 10% sampling)                |
| `OTEL_BSP_MAX_QUEUE_SIZE`       | Max queued spans                              | `2048`                | int > 0                                    |
| `OTEL_BSP_MAX_EXPORT_BATCH_SIZE`| Max batch size for export                     | `512`                 | int > 0                                    |
| `OTEL_BSP_SCHEDULE_DELAY`       | Export interval (ms)                          | `5000`                | int > 0                                    |

**Quick Start with Phoenix**:
```bash
# Start Phoenix for LLM observability
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

# Configure gateway
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Run gateway - traces automatically sent to Phoenix
mcpgateway
```

> 🔍 **What Gets Traced**: Tool invocations, prompt rendering, resource fetching, gateway federation, health checks, plugin execution (if enabled)
>
> 🚀 **Zero Overhead**: When `OTEL_ENABLE_OBSERVABILITY=false`, all tracing is disabled with no performance impact
>
> 📊 **View Traces**: Phoenix UI at `http://localhost:6006`, Jaeger at `http://localhost:16686`, or your configured backend

### Internal Observability & Tracing

The gateway includes built-in observability features for tracking HTTP requests, spans, and traces independent of OpenTelemetry. This provides database-backed trace storage and analysis directly in the Admin UI.

| Setting                              | Description                                           | Default                                              | Options          |
| ------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------- | ---------------- |
| `OBSERVABILITY_ENABLED`              | Enable internal observability tracing and metrics     | `false`                                              | bool             |
| `OBSERVABILITY_TRACE_HTTP_REQUESTS`  | Automatically trace HTTP requests                     | `true`                                               | bool             |
| `OBSERVABILITY_TRACE_RETENTION_DAYS` | Number of days to retain trace data                   | `7`                                                  | int (≥ 1)        |
| `OBSERVABILITY_MAX_TRACES`           | Maximum number of traces to retain                    | `100000`                                             | int (≥ 1000)     |
| `OBSERVABILITY_SAMPLE_RATE`          | Trace sampling rate (0.0-1.0)                        | `1.0`                                                | float (0.0-1.0)  |
| `OBSERVABILITY_EXCLUDE_PATHS`        | Paths to exclude from tracing (regex patterns)        | `/health,/healthz,/ready,/metrics,/static/.*`        | comma-separated  |
| `OBSERVABILITY_METRICS_ENABLED`      | Enable metrics collection                             | `true`                                               | bool             |
| `OBSERVABILITY_EVENTS_ENABLED`       | Enable event logging within spans                     | `true`                                               | bool             |

**Key Features:**
- 📊 **Database-backed storage**: Traces stored in SQLite/PostgreSQL for persistence
- 🔍 **Admin UI integration**: View traces, spans, and metrics in the diagnostics tab
- 🎯 **Sampling control**: Configure sampling rate to reduce overhead in high-traffic scenarios
- 🕐 **Automatic cleanup**: Old traces automatically purged based on retention settings
- 🚫 **Path filtering**: Exclude health checks and static resources from tracing

**Configuration Effects:**
- `OBSERVABILITY_ENABLED=false`: Completely disables internal observability (no database writes, zero overhead)
- `OBSERVABILITY_SAMPLE_RATE=0.1`: Traces 10% of requests (useful for high-volume production)
- `OBSERVABILITY_EXCLUDE_PATHS=/health,/metrics`: Prevents noisy endpoints from creating traces

> 📝 **Note**: This is separate from OpenTelemetry. You can use both systems simultaneously - internal observability for Admin UI visibility and OpenTelemetry for external systems like Phoenix/Jaeger.
>
> 🎛️ **Admin UI Access**: When enabled, traces appear in **Admin → Diagnostics → Observability** tab with filtering, search, and export capabilities

### Prometheus Metrics

The gateway exposes Prometheus-compatible metrics at `/metrics/prometheus` for monitoring and alerting.

| Setting                      | Description                                              | Default   | Options          |
| ---------------------------- | -------------------------------------------------------- | --------- | ---------------- |
| `ENABLE_METRICS`             | Enable Prometheus metrics instrumentation                | `true`    | bool             |
| `METRICS_EXCLUDED_HANDLERS`  | Regex patterns for paths to exclude from metrics         | (empty)   | comma-separated  |
| `METRICS_NAMESPACE`          | Prometheus metrics namespace (prefix)                    | `default` | string           |
| `METRICS_SUBSYSTEM`          | Prometheus metrics subsystem (secondary prefix)          | (empty)   | string           |
| `METRICS_CUSTOM_LABELS`      | Static custom labels for app_info gauge                  | (empty)   | `key=value,...`  |

**Key Features:**
- 📊 **Standard metrics**: HTTP request duration, response codes, active requests
- 🏷️ **Custom labels**: Add static labels (environment, region, team) for filtering in Prometheus/Grafana
- 🚫 **Path exclusions**: Prevent high-cardinality issues by excluding dynamic paths
- 📈 **Namespace isolation**: Group metrics by application or organization

**Configuration Examples:**

```bash
# Production deployment with custom labels
ENABLE_METRICS=true
METRICS_NAMESPACE=mycompany
METRICS_SUBSYSTEM=gateway
METRICS_CUSTOM_LABELS=environment=production,region=us-east-1,team=platform

# Exclude high-volume endpoints from metrics
METRICS_EXCLUDED_HANDLERS=/servers/.*/sse,/static/.*,.*health.*

# Disable metrics for development
ENABLE_METRICS=false
```

**Metric Names:**
- With namespace + subsystem: `mycompany_gateway_http_requests_total`
- Default (no namespace/subsystem): `default_http_requests_total`

> ⚠️ **High-Cardinality Warning**: Never use high-cardinality values (user IDs, request IDs, timestamps) in `METRICS_CUSTOM_LABELS`. Only use low-cardinality static values (environment, region, cluster).
>
> 📊 **Prometheus Endpoint**: Access metrics at `GET /metrics/prometheus` (requires authentication if `AUTH_REQUIRED=true`)
>
> 🎯 **Grafana Integration**: Import metrics into Grafana dashboards using the configured namespace as a filter

### Transport

| Setting                   | Description                        | Default | Options                         |
| ------------------------- | ---------------------------------- | ------- | ------------------------------- |
| `TRANSPORT_TYPE`          | Enabled transports                 | `all`   | `http`,`ws`,`sse`,`stdio`,`all` |
| `WEBSOCKET_PING_INTERVAL` | WebSocket ping (secs)              | `30`    | int > 0                         |
| `SSE_RETRY_TIMEOUT`       | SSE retry timeout (ms)             | `5000`  | int > 0                         |
| `SSE_KEEPALIVE_ENABLED`   | Enable SSE keepalive events        | `true`  | bool                            |
| `SSE_KEEPALIVE_INTERVAL`  | SSE keepalive interval (secs)      | `30`    | int > 0                         |
| `USE_STATEFUL_SESSIONS`   | streamable http config             | `false` | bool                            |
| `JSON_RESPONSE_ENABLED`   | json/sse streams (streamable http) | `true`  | bool                            |

> **💡 SSE Keepalive Events**: The gateway sends periodic keepalive events to prevent connection timeouts with proxies and load balancers. Disable with `SSE_KEEPALIVE_ENABLED=false` if your client doesn't handle unknown event types. Common intervals: 30s (default), 60s (AWS ALB), 240s (Azure).

### Federation

| Setting                    | Description            | Default | Options    |
| -------------------------- | ---------------------- | ------- | ---------- |
| `FEDERATION_ENABLED`       | Enable federation      | `true`  | bool       |
| `FEDERATION_DISCOVERY`     | Auto-discover peers    | `false` | bool       |
| `FEDERATION_PEERS`         | Comma-sep peer URLs    | `[]`    | JSON array |
| `FEDERATION_TIMEOUT`       | Gateway timeout (secs) | `30`    | int > 0    |
| `FEDERATION_SYNC_INTERVAL` | Sync interval (secs)   | `300`   | int > 0    |

### Resources

| Setting               | Description           | Default    | Options    |
| --------------------- | --------------------- | ---------- | ---------- |
| `RESOURCE_CACHE_SIZE` | LRU cache size        | `1000`     | int > 0    |
| `RESOURCE_CACHE_TTL`  | Cache TTL (seconds)   | `3600`     | int > 0    |
| `MAX_RESOURCE_SIZE`   | Max resource bytes    | `10485760` | int > 0    |
| `ALLOWED_MIME_TYPES`  | Acceptable MIME types | see code   | JSON array |

### Tools

| Setting                 | Description                    | Default | Options |
| ----------------------- | ------------------------------ | ------- | ------- |
| `TOOL_TIMEOUT`          | Tool invocation timeout (secs) | `60`    | int > 0 |
| `MAX_TOOL_RETRIES`      | Max retry attempts             | `3`     | int ≥ 0 |
| `TOOL_RATE_LIMIT`       | Tool calls per minute          | `100`   | int > 0 |
| `TOOL_CONCURRENT_LIMIT` | Concurrent tool invocations    | `10`    | int > 0 |
| `GATEWAY_TOOL_NAME_SEPARATOR` | Tool name separator for gateway routing | `-`     | `-`, `--`, `_`, `.` |

### Prompts

| Setting                 | Description                      | Default  | Options |
| ----------------------- | -------------------------------- | -------- | ------- |
| `PROMPT_CACHE_SIZE`     | Cached prompt templates          | `100`    | int > 0 |
| `MAX_PROMPT_SIZE`       | Max prompt template size (bytes) | `102400` | int > 0 |
| `PROMPT_RENDER_TIMEOUT` | Jinja render timeout (secs)      | `10`     | int > 0 |

### Health Checks

| Setting                 | Description                               | Default | Options |
| ----------------------- | ----------------------------------------- | ------- | ------- |
| `HEALTH_CHECK_INTERVAL` | Health poll interval (secs)               | `60`    | int > 0 |
| `HEALTH_CHECK_TIMEOUT`  | Health request timeout (secs)             | `10`    | int > 0 |
| `UNHEALTHY_THRESHOLD`   | Fail-count before peer deactivation,      | `3`     | int > 0 |
|                         | Set to -1 if deactivation is not needed.  |         |         |
| `GATEWAY_VALIDATION_TIMEOUT` | Gateway URL validation timeout (secs) | `5`     | int > 0 |
| `FILELOCK_NAME`         | File lock for leader election             | `gateway_service_leader.lock` | string |
| `DEFAULT_ROOTS`         | Default root paths for resources          | `[]`    | JSON array |

### Database

| Setting                 | Description                     | Default | Options |
| ----------------------- | ------------------------------- | ------- | ------- |
| `DB_POOL_SIZE`   .      | SQLAlchemy connection pool size | `200`   | int > 0 |
| `DB_MAX_OVERFLOW`.      | Extra connections beyond pool   | `10`    | int ≥ 0 |
| `DB_POOL_TIMEOUT`.      | Wait for connection (secs)      | `30`    | int > 0 |
| `DB_POOL_RECYCLE`.      | Recycle connections (secs)      | `3600`  | int > 0 |
| `DB_MAX_RETRIES` .      | Max Retry Attempts              | `3`     | int > 0 |
| `DB_RETRY_INTERVAL_MS`  | Retry Interval (ms)             | `2000`  | int > 0 |

### Cache Backend

| Setting                   | Description                | Default  | Options                  |
| ------------------------- | -------------------------- | -------- | ------------------------ |
| `CACHE_TYPE`              | Backend type | `database` | `none`, `memory`, `database`, `redis` |
| `REDIS_URL`               | Redis connection URL       | (none)   | string or empty          |
| `CACHE_PREFIX`            | Key prefix                 | `mcpgw:` | string                   |
| `SESSION_TTL`             | Session validity (secs)    | `3600`   | int > 0                  |
| `MESSAGE_TTL`             | Message retention (secs)   | `600`    | int > 0                  |
| `REDIS_MAX_RETRIES`       | Max Retry Attempts         | `3`      | int > 0                  |
| `REDIS_RETRY_INTERVAL_MS` | Retry Interval (ms)        | `2000`   | int > 0                  |

> 🧠 `none` disables caching entirely. Use `memory` for dev, `database` for local persistence, or `redis` for distributed caching across multiple instances.

### Database Management

MCP Gateway uses Alembic for database migrations. Common commands:

- `make db-current` - Show current database version
- `make db-upgrade` - Apply pending migrations
- `make db-migrate` - Create new migration
- `make db-history` - Show migration history
- `make db-status` - Detailed migration status

#### Troubleshooting

**Common Issues:**

- **"No 'script_location' key found"**: Ensure you're running from the project root directory.

- **"Unknown SSE event: keepalive" warnings**: Some MCP clients don't recognize keepalive events. These warnings are harmless and don't affect functionality. To disable: `SSE_KEEPALIVE_ENABLED=false`

- **Connection timeouts with proxies/load balancers**: If experiencing timeouts, adjust keepalive interval to match your infrastructure: `SSE_KEEPALIVE_INTERVAL=60` (AWS ALB) or `240` (Azure).

### Development

| Setting    | Description            | Default | Options |
| ---------- | ---------------------- | ------- | ------- |
| `DEV_MODE` | Enable dev mode        | `false` | bool    |
| `RELOAD`   | Auto-reload on changes | `false` | bool    |
| `DEBUG`    | Debug logging          | `false` | bool    |

### Well-Known URI Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `WELL_KNOWN_ENABLED`          | Enable well-known URI endpoints (/.well-known/*) | `true`                | bool    |
| `WELL_KNOWN_ROBOTS_TXT`       | robots.txt content                               | (blocks crawlers)     | string  |
| `WELL_KNOWN_SECURITY_TXT`     | security.txt content (RFC 9116)                 | (empty)               | string  |
| `WELL_KNOWN_CUSTOM_FILES`     | Additional custom well-known files (JSON)       | `{}`                  | JSON object |
| `WELL_KNOWN_CACHE_MAX_AGE`    | Cache control for well-known files (seconds)    | `3600`                | int > 0 |

> 🔍 **robots.txt**: By default, blocks all crawlers for security. Customize for your needs.
>
> 🔐 **security.txt**: Define security contact information per RFC 9116. Leave empty to disable.
>
> 📄 **Custom Files**: Add arbitrary well-known files like `ai.txt`, `dnt-policy.txt`, etc.

### Header Passthrough Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `ENABLE_HEADER_PASSTHROUGH`   | Enable HTTP header passthrough feature (⚠️ Security implications) | `false` | bool |
| `ENABLE_OVERWRITE_BASE_HEADERS` | Enable overwriting of base headers (⚠️ Advanced usage) | `false` | bool |
| `DEFAULT_PASSTHROUGH_HEADERS` | Default headers to pass through (JSON array)    | `["X-Tenant-Id", "X-Trace-Id"]` | JSON array |

> ⚠️ **Security Warning**: Header passthrough is disabled by default for security. Only enable if you understand the implications and have reviewed which headers should be passed through to backing MCP servers. Authorization headers are not included in defaults.

### Plugin Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `PLUGINS_ENABLED`             | Enable the plugin framework                      | `false`               | bool    |
| `PLUGIN_CONFIG_FILE`          | Path to main plugin configuration file          | `plugins/config.yaml` | string  |
| `PLUGINS_MTLS_CA_BUNDLE`      | (Optional) default CA bundle for external plugin mTLS | _(empty)_     | string  |
| `PLUGINS_MTLS_CLIENT_CERT`    | (Optional) gateway client certificate for plugin mTLS | _(empty)_     | string  |
| `PLUGINS_MTLS_CLIENT_KEY`     | (Optional) gateway client key for plugin mTLS | _(empty)_             | string  |
| `PLUGINS_MTLS_CLIENT_KEY_PASSWORD` | (Optional) password for plugin client key | _(empty)_             | string  |
| `PLUGINS_MTLS_VERIFY`         | (Optional) verify remote plugin certificates (`true`/`false`) | `true` | bool    |
| `PLUGINS_MTLS_CHECK_HOSTNAME` | (Optional) enforce hostname verification for plugins | `true`      | bool    |
| `PLUGINS_CLI_COMPLETION`      | Enable auto-completion for plugins CLI          | `false`               | bool    |
| `PLUGINS_CLI_MARKUP_MODE`     | Set markup mode for plugins CLI                 | (none)                | `rich`, `markdown`, `disabled` |

### HTTP Retry Configuration

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `RETRY_MAX_ATTEMPTS`          | Maximum retry attempts for HTTP requests         | `3`                   | int > 0 |
| `RETRY_BASE_DELAY`            | Base delay between retries (seconds)             | `1.0`                 | float > 0 |
| `RETRY_MAX_DELAY`             | Maximum delay between retries (seconds)          | `60`                  | int > 0 |
| `RETRY_JITTER_MAX`            | Maximum jitter fraction of base delay            | `0.5`                 | float 0-1 |

</details>

---

## Running

### Makefile

```bash
 make serve               # Run production Gunicorn server on
 make serve-ssl           # Run Gunicorn behind HTTPS on :4444 (uses ./certs)
```

### Script helper

To run the development (uvicorn) server:

```bash
make dev
# or
./run.sh --reload --log debug --workers 2
```

> `run.sh` is a wrapper around `uvicorn` that loads `.env`, supports reload, and passes arguments to the server.

Key flags:

| Flag             | Purpose          | Example            |
| ---------------- | ---------------- | ------------------ |
| `-e, --env FILE` | load env-file    | `--env prod.env`   |
| `-H, --host`     | bind address     | `--host 127.0.0.1` |
| `-p, --port`     | listen port      | `--port 8080`      |
| `-w, --workers`  | gunicorn workers | `--workers 4`      |
| `-r, --reload`   | auto-reload      | `--reload`         |

### Manual (Uvicorn)

```bash
uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 4
```

---

## Authentication examples

```bash
# Generate a JWT token using JWT_SECRET_KEY and export it as MCPGATEWAY_BEARER_TOKEN
# Note that the module needs to be installed. If running locally use:
export MCPGATEWAY_BEARER_TOKEN=$(JWT_SECRET_KEY=my-test-key python3 -m mcpgateway.utils.create_jwt_token)

# Use the JWT token in an API call
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```

---

## ☁️ AWS / Azure / OpenShift

Deployment details can be found in the GitHub Pages.

## ☁️ IBM Cloud Code Engine Deployment

This project supports deployment to [IBM Cloud Code Engine](https://cloud.ibm.com/codeengine) using the **ibmcloud** CLI and the IBM Container Registry.

<details>
<summary><strong>☁️ IBM Cloud Code Engine Deployment</strong></summary>

### 🔧 Prerequisites

- Podman **or** Docker installed locally
- IBM Cloud CLI (use `make ibmcloud-cli-install` to install)
- An [IBM Cloud API key](https://cloud.ibm.com/iam/apikeys) with access to Code Engine & Container Registry
- Code Engine and Container Registry services **enabled** in your IBM Cloud account

---

### 📦 Environment Variables

Create a **`.env`** file (or export the variables in your shell).
The first block is **required**; the second provides **tunable defaults** you can override:

```bash
# ── Required ─────────────────────────────────────────────
IBMCLOUD_REGION=us-south
IBMCLOUD_RESOURCE_GROUP=default
IBMCLOUD_PROJECT=my-codeengine-project
IBMCLOUD_CODE_ENGINE_APP=mcpgateway
IBMCLOUD_IMAGE_NAME=us.icr.io/myspace/mcpgateway:latest
IBMCLOUD_IMG_PROD=mcpgateway/mcpgateway
IBMCLOUD_API_KEY=your_api_key_here   # Optional - omit to use interactive `ibmcloud login --sso`

# ── Optional overrides (sensible defaults provided) ──────
IBMCLOUD_CPU=1                       # vCPUs for the app
IBMCLOUD_MEMORY=4G                   # Memory allocation
IBMCLOUD_REGISTRY_SECRET=my-regcred  # Name of the Container Registry secret
```

> ✅ **Quick check:** `make ibmcloud-check-env`

---

### 🚀 Make Targets

| Target                      | Purpose                                                                   |
| --------------------------- | ------------------------------------------------------------------------- |
| `make ibmcloud-cli-install` | Install IBM Cloud CLI and required plugins                                |
| `make ibmcloud-login`       | Log in to IBM Cloud (API key or SSO)                                      |
| `make ibmcloud-ce-login`    | Select the Code Engine project & region                                   |
| `make ibmcloud-tag`         | Tag the local container image                                             |
| `make ibmcloud-push`        | Push the image to IBM Container Registry                                  |
| `make ibmcloud-deploy`      | **Create or update** the Code Engine application (uses CPU/memory/secret) |
| `make ibmcloud-ce-status`   | Show current deployment status                                            |
| `make ibmcloud-ce-logs`     | Stream logs from the running app                                          |
| `make ibmcloud-ce-rm`       | Delete the Code Engine application                                        |

---

### 📝 Example Workflow

```bash
make ibmcloud-check-env
make ibmcloud-cli-install
make ibmcloud-login
make ibmcloud-ce-login
make ibmcloud-tag
make ibmcloud-push
make ibmcloud-deploy
make ibmcloud-ce-status
make ibmcloud-ce-logs
```

</details>

---

## API Endpoints

You can test the API endpoints through curl, or Swagger UI, and check detailed documentation on ReDoc:

* **Swagger UI** → [http://localhost:4444/docs](http://localhost:4444/docs)
* **ReDoc**    → [http://localhost:4444/redoc](http://localhost:4444/redoc)

Generate an API Bearer token, and test the various API endpoints.

<details>
<summary><strong>🔐 Authentication & Health Checks</strong></summary>

```bash
# Generate a bearer token using the configured secret key (use the same as your .env)
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --secret my-test-key)
echo ${MCPGATEWAY_BEARER_TOKEN}

# Quickly confirm that authentication works and the gateway is healthy
curl -s -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/health
# {"status":"healthy"}

# Quickly confirm the gateway version & DB connectivity
curl -s -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/version | jq
```

</details>

---

<details>
<summary><strong>🧱 Protocol APIs (MCP) /protocol</strong></summary>

```bash
# Initialize MCP session
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "protocol_version":"2025-03-26",
           "capabilities":{},
           "client_info":{"name":"MyClient","version":"1.0.0"}
         }' \
     http://localhost:4444/protocol/initialize

# Ping (JSON-RPC style)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' \
     http://localhost:4444/protocol/ping

# Completion for prompt/resource arguments (not implemented)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "ref":{"type":"ref/prompt","name":"example_prompt"},
           "argument":{"name":"topic","value":"py"}
         }' \
     http://localhost:4444/protocol/completion/complete

# Sampling (streaming) (not implemented)
curl -N -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "messages":[{"role":"user","content":{"type":"text","text":"Hello"}}],
           "maxTokens":16
         }' \
     http://localhost:4444/protocol/sampling/createMessage
```

</details>

---

<details>
<summary><strong>🧠 JSON-RPC Utility /rpc</strong></summary>

```bash
# Generic JSON-RPC calls (tools, gateways, roots, etc.)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"list_tools"}' \
     http://localhost:4444/rpc
```

Handles any method name: `list_tools`, `list_gateways`, `prompts/get`, or invokes a tool if method matches a registered tool name .

</details>

---

<details>
<summary><strong>🔧 Tool Management /tools</strong></summary>


```bash
# Register a new tool
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"clock_tool",
           "url":"http://localhost:9000/rpc",
           "description":"Returns current time",
           "input_schema":{
             "type":"object",
             "properties":{"timezone":{"type":"string"}},
             "required":[]
           }
         }' \
     http://localhost:4444/tools

# List tools
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools

# Get tool by ID
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools/1

# Update tool
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{ "description":"Updated desc" }' \
     http://localhost:4444/tools/1

# Toggle active status
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/tools/1/toggle?activate=false
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/tools/1/toggle?activate=true

# Delete tool
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools/1
```

</details>

---

<details>
<summary><strong>🤖 A2A Agent Management /a2a</strong></summary>

```bash
# Register a new A2A agent
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"hello_world_agent",
           "endpoint_url":"http://localhost:9999/",
           "agent_type":"jsonrpc",
           "description":"External AI agent for hello world functionality",
           "auth_type":"api_key",
           "auth_value":"your-api-key",
           "tags":["ai", "hello-world"]
         }' \
     http://localhost:4444/a2a

# List A2A agents
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/a2a

# Get agent by ID
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/a2a/agent-id

# Update agent
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{ "description":"Updated description" }' \
     http://localhost:4444/a2a/agent-id

# Test agent (direct invocation)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "parameters": {
             "method": "message/send",
             "params": {
               "message": {
                 "messageId": "test-123",
                 "role": "user",
                 "parts": [{"type": "text", "text": "Hello!"}]
               }
             }
           },
           "interaction_type": "test"
         }' \
     http://localhost:4444/a2a/agent-name/invoke

# Toggle agent status
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/a2a/agent-id/toggle?activate=false

# Delete agent
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/a2a/agent-id

# Associate agent with virtual server (agents become available as MCP tools)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"AI Assistant Server",
           "description":"Virtual server with AI agents",
           "associated_a2a_agents":["agent-id"]
         }' \
     http://localhost:4444/servers
```

> 🤖 **A2A Integration**: A2A agents are external AI agents that can be registered and exposed as MCP tools
> 🔄 **Protocol Detection**: Gateway automatically detects JSONRPC vs custom A2A protocols
> 📊 **Testing**: Built-in test functionality via Admin UI or `/a2a/{agent_id}/test` endpoint
> 🎛️ **Virtual Servers**: Associate agents with servers to expose them as standard MCP tools

</details>

---

<details>
<summary><strong>🌐 Gateway Management /gateways</strong></summary>

```bash
# Register an MCP server as a new gateway provider
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"peer_gateway","url":"http://peer:4444"}' \
     http://localhost:4444/gateways

# List gateways
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/gateways

# Get gateway by ID
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/gateways/1

# Update gateway
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"description":"New description"}' \
     http://localhost:4444/gateways/1

# Toggle active status
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/gateways/1/toggle?activate=false

# Delete gateway
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/gateways/1
```

</details>

---

<details>
<summary><strong>📁 Resource Management /resources</strong></summary>


```bash
# Register resource
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "uri":"config://app/settings",
           "name":"App Settings",
           "content":"key=value"
         }' \
     http://localhost:4444/resources

# List resources
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/resources

# Read a resource
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/resources/config://app/settings

# Update resource
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content":"new=value"}' \
     http://localhost:4444/resources/config://app/settings

# Delete resource
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/resources/config://app/settings

# Subscribe to updates (SSE)
curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/resources/subscribe/config://app/settings
```

</details>

---

<details>
<summary><strong>📝 Prompt Management /prompts</strong></summary>

```bash
# Create prompt template
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"greet",
           "template":"Hello, {{ user }}!",
           "argument_schema":{
             "type":"object",
             "properties":{"user":{"type":"string"}},
             "required":["user"]
           }
         }' \
     http://localhost:4444/prompts

# List prompts
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/prompts

# Get prompt (with args)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"user":"Alice"}' \
     http://localhost:4444/prompts/greet

# Get prompt (no args)
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/prompts/greet

# Update prompt
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"template":"Hi, {{ user }}!"}' \
     http://localhost:4444/prompts/greet

# Toggle active
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/prompts/5/toggle?activate=false

# Delete prompt
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/prompts/greet
```

</details>

---

<details>
<summary><strong>🌲 Root Management /roots</strong></summary>

```bash
# List roots
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/roots

# Add root
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"uri":"/data","name":"Data Root"}' \
     http://localhost:4444/roots

# Remove root
curl -X DELETE -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/roots/%2Fdata

# Subscribe to root changes (SSE)
curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/roots/changes
```

</details>

---

<details>
<summary><strong>🖥️ Server Management /servers</strong></summary>

```bash
# List servers
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers

# Get server
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers/UUID_OF_SERVER_1

# Create server
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"db","description":"Database","associatedTools": ["1","2","3"]}' \
     http://localhost:4444/servers

# Update server
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"description":"Updated"}' \
     http://localhost:4444/servers/UUID_OF_SERVER_1

# Toggle active
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/servers/UUID_OF_SERVER_1/toggle?activate=false
```

</details>

---

<details>
<summary><strong>📊 Metrics /metrics</strong></summary>

```bash
# Get aggregated metrics
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/metrics

# Reset metrics (all or per-entity)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/metrics/reset
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/metrics/reset?entity=tool&id=1
```

</details>

---

<details>
<summary><strong>📡 Events & Health</strong></summary>

```bash
# SSE: all events
curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/events

# WebSocket
wscat -c ws://localhost:4444/ws \
      -H "Authorization: Basic $(echo -n admin:changeme|base64)"

# Health check
curl http://localhost:4444/health
```

Full Swagger UI at `/docs`.

</details>

---

<details>
<summary><strong>🛠️ Sample Tool</strong></summary>

```bash
uvicorn sample_tool.clock_tool:app --host 0.0.0.0 --port 9000
```

```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"get_time","params":{"timezone":"UTC"}}' \
     http://localhost:9000/rpc
```

</details>

---

## Testing

```bash
make test            # Run unit tests
make lint            # Run lint tools
```

## Doctest Coverage

ContextForge implements comprehensive doctest coverage to ensure all code examples in documentation are tested and verified:

```bash
make doctest         # Run all doctests
make doctest-verbose # Run with detailed output
make doctest-coverage # Generate coverage report
make doctest-check   # Check coverage percentage
```

**Coverage Status:**
- ✅ **Transport Modules**: 100% (base, stdio, SSE, WebSocket, streamable HTTP)
- ✅ **Utility Functions**: 100% (slug generation, JWT tokens, validation)
- ✅ **Configuration**: 100% (settings, environment variables)
- 🔄 **Service Classes**: ~60% (in progress)
- 🔄 **Complex Classes**: ~40% (in progress)

**Benefits:**
- All documented examples are automatically tested
- Documentation stays accurate and up-to-date
- Developers can run examples directly from docstrings
- Regression prevention through automated verification

For detailed information, see the [Doctest Coverage Guide](https://ibm.github.io/mcp-context-forge/development/doctest-coverage/).

---

## Project Structure

<details>
<summary><strong>📁 Directory and file structure for mcpgateway</strong></summary>

```bash
# ────────── CI / Quality & Meta-files ──────────
├── .bumpversion.cfg                # Automated semantic-version bumps
├── .coveragerc                     # Coverage.py settings
├── .darglint                       # Doc-string linter rules
├── .dockerignore                   # Context exclusions for image builds
├── .editorconfig                   # Consistent IDE / editor behaviour
├── .env                            # Local runtime variables (git-ignored)
├── .env.ce                         # IBM Code Engine runtime env (ignored)
├── .env.ce.example                 # Sample env for IBM Code Engine
├── .env.example                    # Generic sample env file
├── .env.gcr                        # Google Cloud Run runtime env (ignored)
├── .eslintrc.json                  # ESLint rules for JS / TS assets
├── .flake8                         # Flake-8 configuration
├── .gitattributes                  # Git attributes (e.g. EOL normalisation)
├── .github                         # GitHub settings, CI/CD workflows & templates
│   ├── CODEOWNERS                  # Default reviewers
│   └── workflows/                  # Bandit, Docker, CodeQL, Python Package, Container Deployment, etc.
├── .gitignore                      # Git exclusion rules
├── .hadolint.yaml                  # Hadolint rules for Dockerfiles
├── .htmlhintrc                     # HTMLHint rules
├── .markdownlint.json              # Markdown-lint rules
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff, black, mypy, ...)
├── .pycodestyle                    # PEP-8 checker settings
├── .pylintrc                       # Pylint configuration
├── .pyspelling.yml                 # Spell-checker dictionary & filters
├── .ruff.toml                      # Ruff linter / formatter settings
├── .spellcheck-en.txt              # Extra dictionary entries
├── .stylelintrc.json               # Stylelint rules for CSS
├── .travis.yml                     # Legacy Travis CI config (reference)
├── .whitesource                    # WhiteSource security-scanning config
├── .yamllint                       # yamllint ruleset

# ────────── Documentation & Guidance ──────────
├── CHANGELOG.md                    # Version-by-version change log
├── CODE_OF_CONDUCT.md              # Community behaviour guidelines
├── CONTRIBUTING.md                 # How to file issues & send PRs
├── DEVELOPING.md                   # Contributor workflows & style guide
├── LICENSE                         # Apache License 2.0
├── README.md                       # Project overview & quick-start
├── SECURITY.md                     # Security policy & CVE disclosure process
├── TESTING.md                      # Testing strategy, fixtures & guidelines

# ────────── Containerisation & Runtime ──────────
├── Containerfile                   # OCI image build (Docker / Podman)
├── Containerfile.lite              # FROM scratch UBI-Micro production build
├── docker-compose.yml              # Local multi-service stack
├── podman-compose-sonarqube.yaml   # One-liner SonarQube stack
├── run-gunicorn.sh                 # Opinionated Gunicorn startup script
├── run.sh                          # Uvicorn shortcut with arg parsing

# ────────── Build / Packaging / Tooling ──────────
├── MANIFEST.in                     # sdist inclusion rules
├── Makefile                        # Dev & deployment targets
├── package-lock.json               # Deterministic npm lock-file
├── package.json                    # Front-end / docs tooling deps
├── pyproject.toml                  # Poetry / PDM config & lint rules
├── sonar-code.properties           # SonarQube analysis settings
├── uv.lock                         # UV resolver lock-file

# ────────── Kubernetes & Helm Assets ──────────
├── charts                          # Helm chart(s) for K8s / OpenShift
│   ├── mcp-stack                   # Umbrella chart
│   │   ├── Chart.yaml              # Chart metadata
│   │   ├── templates/...             # Manifest templates
│   │   └── values.yaml             # Default values
│   └── README.md                   # Install / upgrade guide
├── k8s                             # Raw (non-Helm) K8s manifests
│   └── *.yaml                      # Deployment, Service, PVC resources

# ────────── Documentation Source ──────────
├── docs                            # MkDocs site source
│   ├── base.yml                    # MkDocs "base" configuration snippet (do not modify)
│   ├── mkdocs.yml                  # Site configuration (requires base.yml)
│   ├── requirements.txt            # Python dependencies for the MkDocs site
│   ├── Makefile                    # Make targets for building/serving the docs
│   └── theme                       # Custom MkDocs theme assets
│       └── logo.png                # Logo for the documentation theme
│   └── docs                        # Markdown documentation
│       ├── architecture/           # ADRs for the project
│       ├── articles/               # Long-form writeups
│       ├── blog/                   # Blog posts
│       ├── deployment/             # Deployment guides (AWS, Azure, etc.)
│       ├── development/            # Development workflows & CI docs
│       ├── images/                 # Diagrams & screenshots
│       ├── index.md                # Top-level docs landing page
│       ├── manage/                 # Management topics (backup, logging, tuning, upgrade)
│       ├── overview/               # Feature overviews & UI documentation
│       ├── security/               # Security guidance & policies
│       ├── testing/                # Testing strategy & fixtures
│       └── using/                  # User-facing usage guides (agents, clients, etc.)
│       ├── media/                  # Social media, press coverage, videos & testimonials
│       │   ├── press/              # Press articles and blog posts
│       │   ├── social/             # Tweets, LinkedIn posts, YouTube embeds
│       │   ├── testimonials/       # Customer quotes & community feedback
│       │   └── kit/                # Media kit & logos for bloggers & press
├── dictionary.dic                  # Custom dictionary for spell-checker (make spellcheck)

# ────────── Application & Libraries ──────────
├── agent_runtimes                  # Configurable agentic frameworks converted to MCP Servers
├── mcpgateway                      # ← main application package
│   ├── __init__.py                 # Package metadata & version constant
│   ├── admin.py                    # FastAPI routers for Admin UI
│   ├── cache
│   │   ├── __init__.py
│   │   ├── resource_cache.py       # LRU+TTL cache implementation
│   │   └── session_registry.py     # Session ↔ cache mapping
│   ├── config.py                   # Pydantic settings loader
│   ├── db.py                       # SQLAlchemy models & engine setup
│   ├── federation
│   │   ├── __init__.py
│   │   ├── discovery.py            # Peer-gateway discovery
│   │   ├── forward.py              # RPC forwarding
│   ├── handlers
│   │   ├── __init__.py
│   │   └── sampling.py             # Streaming sampling handler
│   ├── main.py                     # FastAPI app factory & startup events
│   ├── mcp.db                      # SQLite fixture for tests
│   ├── py.typed                    # PEP 561 marker (ships type hints)
│   ├── schemas.py                  # Shared Pydantic DTOs
│   ├── services
│   │   ├── __init__.py
│   │   ├── completion_service.py   # Prompt / argument completion
│   │   ├── gateway_service.py      # Peer-gateway registry
│   │   ├── logging_service.py      # Central logging helpers
│   │   ├── prompt_service.py       # Prompt CRUD & rendering
│   │   ├── resource_service.py     # Resource registration & retrieval
│   │   ├── root_service.py         # File-system root registry
│   │   ├── server_service.py       # Server registry & monitoring
│   │   └── tool_service.py         # Tool registry & invocation
│   ├── static
│   │   ├── admin.css               # Styles for Admin UI
│   │   └── admin.js                # Behaviour for Admin UI
│   ├── templates
│   │   └── admin.html              # HTMX/Alpine Admin UI template
│   ├── transports
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract transport interface
│   │   ├── sse_transport.py        # Server-Sent Events transport
│   │   ├── stdio_transport.py      # stdio transport for embedding
│   │   └── websocket_transport.py  # WS transport with ping/pong
│   ├── models.py                   # Core enums / type aliases
│   ├── utils
│   │   ├── create_jwt_token.py     # CLI & library for JWT generation
│   │   ├── services_auth.py        # Service-to-service auth dependency
│   │   └── verify_credentials.py   # Basic / JWT auth helpers
│   ├── validation
│   │   ├── __init__.py
│   │   └── jsonrpc.py              # JSON-RPC 2.0 validation
│   └── version.py                  # Library version helper
├── mcpgateway-wrapper              # Stdio client wrapper (PyPI)
│   ├── pyproject.toml
│   ├── README.md
│   └── src/mcpgateway_wrapper/
│       ├── __init__.py
│       └── server.py               # Wrapper entry-point
├── mcp-servers                     # Sample downstream MCP servers
├── mcp.db                          # Default SQLite DB (auto-created)
├── mcpgrid                         # Experimental grid client / PoC
├── os_deps.sh                      # Installs system-level deps for CI

# ────────── Tests & QA Assets ──────────
├── test_readme.py                  # Guard: README stays in sync
├── tests
│   ├── conftest.py                 # Shared fixtures
│   ├── e2e/...                       # End-to-end scenarios
│   ├── hey/...                       # Load-test logs & helper script
│   ├── integration/...               # API-level integration tests
│   └── unit/...                      # Pure unit tests for business logic
```

</details>

---

## API Documentation

* **Swagger UI** → [http://localhost:4444/docs](http://localhost:4444/docs)
* **ReDoc**    → [http://localhost:4444/redoc](http://localhost:4444/redoc)
* **Admin Panel** → [http://localhost:4444/admin](http://localhost:4444/admin)

---

## Makefile targets

This project offer the following Makefile targets. Type `make` in the project root to show all targets.

<details>
<summary><strong>🔧 Available Makefile targets</strong></summary>

```bash
🐍 MCP CONTEXTFORGE  (An enterprise-ready Model Context Protocol Gateway)
🔧 SYSTEM-LEVEL DEPENDENCIES (DEV BUILD ONLY)
os-deps              - Install Graphviz, Pandoc, Trivy, SCC used for dev docs generation and security scan
🌱 VIRTUAL ENVIRONMENT & INSTALLATION
venv                 - Create a fresh virtual environment with uv & friends
activate             - Activate the virtual environment in the current shell
install              - Install project into the venv
install-dev          - Install project (incl. dev deps) into the venv
install-db           - Install project (incl. postgres and redis) into venv
update               - Update all installed deps inside the venv
check-env            - Verify all required env vars in .env are present
▶️ SERVE & TESTING
serve                - Run production Gunicorn server on :4444
certs                - Generate self-signed TLS cert & key in ./certs (won't overwrite)
serve-ssl            - Run Gunicorn behind HTTPS on :4444 (uses ./certs)
dev                  - Run fast-reload dev server (uvicorn)
run                  - Execute helper script ./run.sh
test                 - Run unit tests with pytest
test-curl            - Smoke-test API endpoints with curl script
pytest-examples      - Run README / examples through pytest-examples
clean                - Remove caches, build artefacts, virtualenv, docs, certs, coverage, SBOM, etc.
📊 COVERAGE & METRICS
coverage             - Run tests with coverage, emit md/HTML/XML + badge
pip-licenses         - Produce dependency license inventory (markdown)
scc                  - Quick LoC/complexity snapshot with scc
scc-report           - Generate HTML LoC & per-file metrics with scc
📚 DOCUMENTATION & SBOM
docs                 - Build docs (graphviz + handsdown + images + SBOM)
images               - Generate architecture & dependency diagrams
🔍 LINTING & STATIC ANALYSIS
lint                 - Run the full linting suite (see targets below)
black                - Reformat code with black
autoflake            - Remove unused imports / variables with autoflake
isort                - Organise & sort imports with isort
flake8               - PEP-8 style & logical errors
pylint               - Pylint static analysis
markdownlint         - Lint Markdown files with markdownlint (requires markdownlint-cli)
mypy                 - Static type-checking with mypy
bandit               - Security scan with bandit
pydocstyle           - Docstring style checker
pycodestyle          - Simple PEP-8 checker
pre-commit           - Run all configured pre-commit hooks
ruff                 - Ruff linter + formatter
ty                   - Ty type checker from astral
pyright              - Static type-checking with Pyright
radon                - Code complexity & maintainability metrics
pyroma               - Validate packaging metadata
importchecker        - Detect orphaned imports
spellcheck           - Spell-check the codebase
fawltydeps           - Detect undeclared / unused deps
wily                 - Maintainability report
pyre                 - Static analysis with Facebook Pyre
depend               - List dependencies in ≈requirements format
snakeviz             - Profile & visualise with snakeviz
pstats               - Generate PNG call-graph from cProfile stats
spellcheck-sort      - Sort local spellcheck dictionary
tox                  - Run tox across multi-Python versions
sbom                 - Produce a CycloneDX SBOM and vulnerability scan
pytype               - Flow-sensitive type checker
check-manifest       - Verify sdist/wheel completeness
yamllint            - Lint YAML files (uses .yamllint)
jsonlint            - Validate every *.json file with jq (--exit-status)
tomllint            - Validate *.toml files with tomlcheck
🕸️  WEBPAGE LINTERS & STATIC ANALYSIS (HTML/CSS/JS lint + security scans + formatting)
install-web-linters  - Install HTMLHint, Stylelint, ESLint, Retire.js & Prettier via npm
lint-web             - Run HTMLHint, Stylelint, ESLint, Retire.js and npm audit
format-web           - Format HTML, CSS & JS files with Prettier
osv-install          - Install/upgrade osv-scanner (Go)
osv-scan-source      - Scan source & lockfiles for CVEs
osv-scan-image       - Scan the built container image for CVEs
osv-scan             - Run all osv-scanner checks (source, image, licence)
📡 SONARQUBE ANALYSIS
sonar-deps-podman    - Install podman-compose + supporting tools
sonar-deps-docker    - Install docker-compose + supporting tools
sonar-up-podman      - Launch SonarQube with podman-compose
sonar-up-docker      - Launch SonarQube with docker-compose
sonar-submit-docker  - Run containerized Sonar Scanner CLI with Docker
sonar-submit-podman  - Run containerized Sonar Scanner CLI with Podman
pysonar-scanner      - Run scan with Python wrapper (pysonar-scanner)
sonar-info           - How to create a token & which env vars to export
🛡️ SECURITY & PACKAGE SCANNING
trivy                - Scan container image for CVEs (HIGH/CRIT). Needs podman socket enabled
grype-scan           - Scan container for security audit and vulnerability scanning
dockle               - Lint the built container image via tarball (no daemon/socket needed)
hadolint             - Lint Containerfile/Dockerfile(s) with hadolint
pip-audit            - Audit Python dependencies for published CVEs
📦 DEPENDENCY MANAGEMENT
deps-update          - Run update-deps.py to update all dependencies in pyproject.toml and docs/requirements.txt
containerfile-update - Update base image in Containerfile to latest tag
📦 PACKAGING & PUBLISHING
dist                 - Clean-build wheel *and* sdist into ./dist
wheel                - Build wheel only
sdist                - Build source distribution only
verify               - Build + twine + check-manifest + pyroma (no upload)
publish              - Verify, then upload to PyPI (needs TWINE_* creds)
🦭 PODMAN CONTAINER BUILD & RUN
podman-dev           - Build development container image
podman               - Build container image
podman-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
podman-run           - Run the container on HTTP  (port 4444)
podman-run-shell     - Run the container on HTTP  (port 4444) and start a shell
podman-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
podman-run-ssl-host  - Run the container on HTTPS with --network=host (port 4444, self-signed)
podman-stop          - Stop & remove the container
podman-test          - Quick curl smoke-test against the container
podman-logs          - Follow container logs (⌃C to quit)
podman-stats         - Show container resource stats (if supported)
podman-top           - Show live top-level process info in container
podman-shell         - Open an interactive shell inside the Podman container
🐋 DOCKER BUILD & RUN
docker-dev           - Build development Docker image
docker               - Build production Docker image
docker-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
docker-run           - Run the container on HTTP  (port 4444)
docker-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
docker-stop          - Stop & remove the container
docker-test          - Quick curl smoke-test against the container
docker-logs          - Follow container logs (⌃C to quit)
docker-stats         - Show container resource usage stats (non-streaming)
docker-top           - Show top-level process info in Docker container
docker-shell         - Open an interactive shell inside the Docker container
🛠️ COMPOSE STACK     - Build / start / stop the multi-service stack
compose-up           - Bring the whole stack up (detached)
compose-restart      - Recreate changed containers, pulling / building as needed
compose-build        - Build (or rebuild) images defined in the compose file
compose-pull         - Pull the latest images only
compose-logs         - Tail logs from all services (Ctrl-C to exit)
compose-ps           - Show container status table
compose-shell        - Open an interactive shell in the "gateway" container
compose-stop         - Gracefully stop the stack (keep containers)
compose-down         - Stop & remove containers (keep named volumes)
compose-rm           - Remove *stopped* containers
compose-clean        - ✨ Down **and** delete named volumes (data-loss ⚠)
☁️ IBM CLOUD CODE ENGINE
ibmcloud-check-env          - Verify all required IBM Cloud env vars are set
ibmcloud-cli-install        - Auto-install IBM Cloud CLI + required plugins (OS auto-detected)
ibmcloud-login              - Login to IBM Cloud CLI using IBMCLOUD_API_KEY (--sso)
ibmcloud-ce-login           - Set Code Engine target project and region
ibmcloud-list-containers    - List deployed Code Engine apps
ibmcloud-tag                - Tag container image for IBM Container Registry
ibmcloud-push               - Push image to IBM Container Registry
ibmcloud-deploy             - Deploy (or update) container image in Code Engine
ibmcloud-ce-logs            - Stream logs for the deployed application
ibmcloud-ce-status          - Get deployment status
ibmcloud-ce-rm              - Delete the Code Engine application
🧪 MINIKUBE LOCAL CLUSTER
minikube-install      - Install Minikube (macOS, Linux, or Windows via choco)
helm-install          - Install Helm CLI (macOS, Linux, or Windows)
minikube-start        - Start local Minikube cluster with Ingress + DNS + metrics-server
minikube-stop         - Stop the Minikube cluster
minikube-delete       - Delete the Minikube cluster
minikube-image-load   - Build and load ghcr.io/ibm/mcp-context-forge:latest into Minikube
minikube-k8s-apply    - Apply Kubernetes manifests from deployment/k8s/
minikube-status       - Show status of Minikube and ingress pods
🛠️ HELM CHART TASKS
helm-lint            - Lint the Helm chart (static analysis)
helm-package         - Package the chart into dist/ as mcp-stack-<ver>.tgz
helm-deploy          - Upgrade/Install chart into Minikube (profile mcpgw)
helm-delete          - Uninstall the chart release from Minikube
🏠 LOCAL PYPI SERVER
local-pypi-install   - Install pypiserver for local testing
local-pypi-start     - Start local PyPI server on :8084 (no auth)
local-pypi-start-auth - Start local PyPI server with basic auth (admin/admin)
local-pypi-stop      - Stop local PyPI server
local-pypi-upload    - Upload existing package to local PyPI (no auth)
local-pypi-upload-auth - Upload existing package to local PyPI (with auth)
local-pypi-test      - Install package from local PyPI
local-pypi-clean     - Full cycle: build → upload → install locally
🏠 LOCAL DEVPI SERVER
devpi-install        - Install devpi server and client
devpi-init           - Initialize devpi server (first time only)
devpi-start          - Start devpi server
devpi-stop           - Stop devpi server
devpi-setup-user     - Create user and dev index
devpi-upload         - Upload existing package to devpi
devpi-test           - Install package from devpi
devpi-clean          - Full cycle: build → upload → install locally
devpi-status         - Show devpi server status
devpi-web            - Open devpi web interface
```
</details>

## 🔍 Troubleshooting

<details>
<summary><strong>macOS: SQLite "disk I/O error" when running make serve</strong></summary>

If the gateway fails on macOS with `sqlite3.OperationalError: disk I/O error` (works on Linux/Docker), it's usually a filesystem/locking quirk rather than a schema bug.

Quick placement guidance (macOS):
- Avoid cloning/running the repo under `~/Documents` or `~/Desktop` if iCloud "Desktop & Documents" sync is enabled.
- A simple, safe choice is a project folder directly under your home directory:
  - `mkdir -p "$HOME/mcp-context-forge" && cd "$HOME/mcp-context-forge"`
  - If you keep the DB inside the repo, use a subfolder like `data/` and an absolute path in `.env`:
    - `mkdir -p "$HOME/mcp-context-forge/data"`
    - `DATABASE_URL=sqlite:////Users/$USER/mcp-context-forge/data/mcp.db`

- Use a safe, local APFS path for SQLite (avoid iCloud/Dropbox/OneDrive/Google Drive, network shares, or external exFAT/NAS):
  - Option A (system location): point the DB to Application Support (note spaces):
    - `mkdir -p "$HOME/Library/Application Support/mcpgateway"`
    - `export DATABASE_URL="sqlite:////Users/$USER/Library/Application Support/mcpgateway/mcp.db"`
  - Option B (project-local): keep the DB under `~/mcp-context-forge/data`:
    - `mkdir -p "$HOME/mcp-context-forge/data"`
    - `export DATABASE_URL="sqlite:////Users/$USER/mcp-context-forge/data/mcp.db"`
- Clean stale SQLite artifacts after any crash:
  - `pkill -f mcpgateway || true && rm -f mcp.db-wal mcp.db-shm mcp.db-journal`
- Reduce startup concurrency to rule out multi-process contention:
  - `GUNICORN_WORKERS=1 make serve` (or use `make dev` which runs single-process)
- Run the diagnostic helper to verify the environment:
  - `python3 scripts/test_sqlite.py --verbose`
- While debugging, consider lowering pool pressure and retry:
  - `DB_POOL_SIZE=10 DB_MAX_OVERFLOW=0 DB_POOL_TIMEOUT=60 DB_MAX_RETRIES=10 DB_RETRY_INTERVAL_MS=5000`
- Optional: temporarily disable the file-lock leader path by using the in-process mode:
  - `export CACHE_TYPE=none`

If the error persists, update SQLite and ensure Python links against it:
- `brew install sqlite3 && brew link --force sqlite3`
- `brew install python3 && /opt/homebrew/bin/python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`

See the full migration guide's "SQLite Troubleshooting Guide" for deeper steps (WAL cleanup, integrity check, recovery): `MIGRATION-0.7.0.md`.

</details>

<details>
<summary><strong>Port publishing on WSL2 (rootless Podman & Docker Desktop)</strong></summary>

### Diagnose the listener

```bash
# Inside your WSL distro
ss -tlnp | grep 4444        # Use ss
netstat -anp | grep 4444    # or netstat
```

*Seeing `:::4444 LISTEN rootlessport` is normal* - the IPv6 wildcard
socket (`::`) also accepts IPv4 traffic **when**
`net.ipv6.bindv6only = 0` (default on Linux).

### Why localhost fails on Windows

WSL 2's NAT layer rewrites only the *IPv6* side of the dual-stack listener. From Windows, `http://127.0.0.1:4444` (or Docker Desktop's "localhost") therefore times-out.

#### Fix (Podman rootless)

```bash
# Inside the WSL distro
echo "wsl" | sudo tee /etc/containers/podman-machine
systemctl --user restart podman.socket
```

`ss` should now show `0.0.0.0:4444` instead of `:::4444`, and the
service becomes reachable from Windows *and* the LAN.

#### Fix (Docker Desktop > 4.19)

Docker Desktop adds a "WSL integration" switch per-distro.
Turn it **on** for your distro, restart Docker Desktop, then restart the
container:

```bash
docker restart mcpgateway
```

</details>

<details>
<summary><strong>Gateway starts but immediately exits ("Failed to read DATABASE_URL")</strong></summary>

Copy `.env.example` to `.env` first:

```bash
cp .env.example .env
```

Then edit `DATABASE_URL`, `JWT_SECRET_KEY`, `BASIC_AUTH_PASSWORD`, etc.
Missing or empty required vars cause a fast-fail at startup.

</details>

## Contributing

1. Fork the repo, create a feature branch.
2. Run `make lint` and fix any issues.
3. Keep `make test` green and 100% coverage.
4. Open a PR - describe your changes clearly.

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.
---

## Changelog

A complete changelog can be found here: [CHANGELOG.md](./CHANGELOG.md)

## License

Licensed under the **Apache License 2.0** - see [LICENSE](./LICENSE)


## Core Authors and Maintainers

- [Mihai Criveti](https://www.linkedin.com/in/crivetimihai) - Distinguished Engineer, Agentic AI

Special thanks to our contributors for helping us improve ContextForge:

<a href="https://github.com/ibm/mcp-context-forge/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ibm/mcp-context-forge&max=100&anon=0&columns=10" />
</a>

## Star History and Project Activity

[![Star History Chart](https://api.star-history.com/svg?repos=ibm/mcp-context-forge&type=Date)](https://www.star-history.com/#ibm/mcp-context-forge&Date)

<!-- === Usage Stats === -->
[![PyPi Downloads](https://static.pepy.tech/badge/mcp-contextforge-gateway/month)](https://pepy.tech/project/mcp-contextforge-gateway)&nbsp;
[![Stars](https://img.shields.io/github/stars/ibm/mcp-context-forge?style=social)](https://github.com/ibm/mcp-context-forge/stargazers)&nbsp;
[![Forks](https://img.shields.io/github/forks/ibm/mcp-context-forge?style=social)](https://github.com/ibm/mcp-context-forge/network/members)&nbsp;
[![Contributors](https://img.shields.io/github/contributors/ibm/mcp-context-forge)](https://github.com/ibm/mcp-context-forge/graphs/contributors)&nbsp;
[![Last Commit](https://img.shields.io/github/last-commit/ibm/mcp-context-forge)](https://github.com/ibm/mcp-context-forge/commits)&nbsp;
[![Open Issues](https://img.shields.io/github/issues/ibm/mcp-context-forge)](https://github.com/ibm/mcp-context-forge/issues)&nbsp;
