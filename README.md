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

## Table of Contents

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
* 9. [Configuration (`.env` or env vars)](#configuration-env-or-env-vars)
    * 9.1. [Basic](#basic)
    * 9.2. [Authentication](#authentication)
    * 9.3. [UI Features](#ui-features)
    * 9.4. [Security](#security)
    * 9.5. [Logging](#logging)
    * 9.6. [Transport](#transport)
    * 9.7. [Federation](#federation)
    * 9.8. [Resources](#resources)
    * 9.9. [Tools](#tools)
    * 9.10. [Prompts](#prompts)
    * 9.11. [Health Checks](#health-checks)
    * 9.12. [Database](#database)
    * 9.13. [Cache Backend](#cache-backend)
    * 9.14. [Development](#development)
* 10. [Running](#running)
    * 10.1. [Makefile](#makefile)
    * 10.2. [Script helper](#script-helper)
    * 10.3. [Manual (Uvicorn)](#manual-uvicorn)
* 11. [Authentication examples](#authentication-examples)
* 12. [☁️ AWS / Azure / OpenShift](#️-aws--azure--openshift)
* 13. [☁️ IBM Cloud Code Engine Deployment](#️-ibm-cloud-code-engine-deployment)
    * 13.1. [🔧 Prerequisites](#-prerequisites-1)
    * 13.2. [📦 Environment Variables](#-environment-variables)
    * 13.3. [🚀 Make Targets](#-make-targets)
    * 13.4. [📝 Example Workflow](#-example-workflow)
* 14. [API Endpoints](#api-endpoints)
* 15. [Testing](#testing)
* 16. [Project Structure](#project-structure)
* 17. [API Documentation](#api-documentation)
* 18. [Makefile targets](#makefile-targets)
* 19. [🔍 Troubleshooting](#-troubleshooting)
    * 19.1. [Diagnose the listener](#diagnose-the-listener)
    * 19.2. [Why localhost fails on Windows](#why-localhost-fails-on-windows)
        * 19.2.1. [Fix (Podman rootless)](#fix-podman-rootless)
        * 19.2.2. [Fix (Docker Desktop > 4.19)](#fix-docker-desktop--419)
* 20. [Contributing](#contributing)
* 21. [Changelog](#changelog)
* 22. [License](#license)
* 23. [Core Authors and Maintainers](#core-authors-and-maintainers)
* 24. [Star History and Project Activity](#star-history-and-project-activity)

<!-- vscode-markdown-toc-config
    numbering=true
    autoSave=true
    /vscode-markdown-toc-config -->
<!-- /vscode-markdown-toc -->



## 🚀 Overview & Goals

**ContextForge MCP Gateway** is a gateway, registry, and proxy that sits in front of any [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server or REST API-exposing a unified endpoint for all your AI clients.

**⚠️ Caution**: The current release (0.4.0) is considered alpha / early beta. It is not production-ready and should only be used for local development, testing, or experimentation. Features, APIs, and behaviors are subject to change without notice. **Do not** deploy in production environments without thorough security review, validation and additional security mechanisms.  Many of the features required for secure, large-scale, or multi-tenant production deployments are still on the [project roadmap](https://ibm.github.io/mcp-context-forge/architecture/roadmap/) - which is itself evolving.

It currently supports:

* Federation across multiple MCP and REST services
* Virtualization of legacy APIs as MCP-compliant tools and servers
* Transport over HTTP, JSON-RPC, WebSocket, SSE, stdio and streamable-HTTP
* An Admin UI for real-time management and configuration
* Built-in auth, observability, retries, and rate-limiting
* Scalable deployments via Docker or PyPI, Redis-backed caching, and multi-cluster federation

![MCP Gateway Architecture](https://ibm.github.io/mcp-context-forge/images/mcpgateway.svg)

For a list of upcoming features, check out the [ContextForge MCP Gateway Roadmap](https://ibm.github.io/mcp-context-forge/architecture/roadmap/)

**⚠️ Important**: MCP Gateway is not a standalone product - it is an open source component with **NO OFFICIAL SUPPORT** from IBM or its affiliates that can be integrated into your own solution architecture. If you choose to use it, you are responsible for evaluating its fit, securing the deployment, and managing its lifecycle. See [SECURITY.md](./SECURITY.md) for more details.

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
* Auth: Basic, JWT, or custom schemes
* Structured logs, health endpoints, metrics
* 400+ tests, Makefile targets, live reload, pre-commit hooks

</details>

---

## Quick Start - PyPI

MCP Gateway is published on [PyPI](https://pypi.org/project/mcp-contextforge-gateway/) as `mcp-contextforge-gateway`.

---

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

# 2️⃣  Launch on all interfaces with custom creds & secret key
# Enable the Admin API endpoints (true/false) - disabled by default
export MCPGATEWAY_UI_ENABLED=true
export MCPGATEWAY_ADMIN_API_ENABLED=true

BASIC_AUTH_PASSWORD=pass JWT_SECRET_KEY=my-test-key \
  mcpgateway --host 0.0.0.0 --port 4444 &   # admin/pass

# 3️⃣  Generate a bearer token & smoke-test the API
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 10080 --secret my-test-key)

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

# 2️⃣  Environment variables (session-only)
$Env:MCPGATEWAY_UI_ENABLED        = "true"
$Env:MCPGATEWAY_ADMIN_API_ENABLED = "true"
$Env:BASIC_AUTH_PASSWORD          = "changeme"      # admin/changeme
$Env:JWT_SECRET_KEY               = "my-test-key"

# 3️⃣  Launch the gateway
mcpgateway.exe --host 0.0.0.0 --port 4444

#   Optional: background it
# Start-Process -FilePath "mcpgateway.exe" -ArgumentList "--host 0.0.0.0 --port 4444"

# 4️⃣  Bearer token and smoke-test
$Env:MCPGATEWAY_BEARER_TOKEN = python3 -m mcpgateway.utils.create_jwt_token `
    --username admin --exp 10080 --secret my-test-key

curl -s -H "Authorization: Bearer $Env:MCPGATEWAY_BEARER_TOKEN" `
     http://127.0.0.1:4444/version | jq
```

</details>

<details>
<summary><strong>More configuration</strong></summary>

Copy [.env.example](.env.example) to `.env` and tweak any of the settings (or use them as env variables).

</details>

<details>
<summary><strong>🚀 End-to-end demo (register a local MCP server)</strong></summary>

```bash
# 1️⃣  Spin up the sample GO MCP time server using mcpgateway.translate & docker
python3 -m mcpgateway.translate \
     --stdio "docker run --rm -i -p 8888:8080 ghcr.io/ibm/fast-time-server:latest -transport=stdio" \
     --port 8003

# Or using the official mcp-server-git using uvx:
pip install uv # to install uvx, if not already installed
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000

# Alternative: running the local binary
# cd mcp-servers/go/fast-time-server; make build
# python3 -m mcpgateway.translate --stdio "./dist/fast-time-server -transport=stdio" --port 8002

# 2️⃣  Register it with the gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time","url":"http://localhost:9000/sse"}' \
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
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID_OF_SERVER_1
python3 -m mcpgateway.wrapper  # Ctrl-C to exit
```

You can also run it with `uv` or inside Docker/Podman - see the *Containers* section above.

In MCP Inspector, define `MCP_AUTH_TOKEN` and `MCP_SERVER_CATALOG_URLS` env variables, and select `python3` as the Command, and `-m mcpgateway.wrapper` as Arguments.

```bash
echo $PWD/.venv/bin/python3 # Using the Python3 full path ensures you have a working venv
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/UUID_OF_SERVER_1'
export MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN}
npx -y @modelcontextprotocol/inspector
```

When using a MCP Client such as Claude with stdio:

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH_TOKEN": "your-token-here",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/UUID_OF_SERVER_1",
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
  -e DATABASE_URL=sqlite:///./mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.4.0

# Tail logs (Ctrl+C to quit)
docker logs -f mcpgateway

# Generating an API key
docker run --rm -it ghcr.io/ibm/mcp-context-forge:0.4.0 \
  python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 0 --secret my-test-key
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
  ghcr.io/ibm/mcp-context-forge:0.4.0
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
  -v $(pwd)/data:/data \
  ghcr.io/ibm/mcp-context-forge:0.4.0
```

Using `--network=host` allows Docker to access the local network, allowing you to add MCP servers running on your host. See [Docker Host network driver documentation](https://docs.docker.com/engine/network/drivers/host/) for more details.

---

### 🦭 Podman (rootless-friendly)

#### 1 - Basic run

```bash
podman run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e DATABASE_URL=sqlite:///./mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.4.0
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
  ghcr.io/ibm/mcp-context-forge:0.4.0
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
  ghcr.io/ibm/mcp-context-forge:0.4.0
```

---

<details>
<summary><strong>✏️ Docker/Podman tips</strong></summary>

* **.env files** - Put all the `-e FOO=` lines into a file and replace them with `--env-file .env`. See the provided [.env.example](.env.example) for reference.
* **Pinned tags** - Use an explicit version (e.g. `v0.4.0`) instead of `latest` for reproducible builds.
* **JWT tokens** - Generate one in the running container:

  ```bash
  docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token -u admin -e 10080 --secret my-test-key
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
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret my-test-key)
export MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN}
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/UUID_OF_SERVER_1'
export MCP_TOOL_CALL_TIMEOUT=120
export MCP_WRAPPER_LOG_LEVEL=DEBUG  # or OFF to disable logging

docker run --rm -i \
  -e MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN \
  -e MCP_SERVER_CATALOG_URLS=http://host.docker.internal:4444/servers/UUID_OF_SERVER_1 \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  -e MCP_WRAPPER_LOG_LEVEL=DEBUG \
  ghcr.io/ibm/mcp-context-forge:0.4.0 \
  python3 -m mcpgateway.wrapper
```

</details>

---

## Testing `mcpgateway.wrapper` by hand:

Because the wrapper speaks JSON-RPC over stdin/stdout, you can interact with it using nothing more than a terminal or pipes.

```bash
# Start the MCP Gateway Wrapper
export MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN}
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/YOUR_SERVER_UUID
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
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false}},"serverInfo":{"name":"mcpgateway-wrapper","version":"0.4.0"}}}

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

> **Remember** to substitute your real Gateway URL (and server ID) for `http://localhost:4444/servers/UUID_OF_SERVER_1`.
> When inside Docker/Podman, that often becomes `http://host.docker.internal:4444/servers/UUID_OF_SERVER_1` (macOS/Windows) or the gateway container's hostname (Linux).

---

<details>
<summary><strong>🐳 Docker / Podman</strong></summary>

```bash
docker run -i --rm \
  --network=host \
  -e MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID_OF_SERVER_1 \
  -e MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN} \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  ghcr.io/ibm/mcp-context-forge:0.4.0 \
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
MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN} \
MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID_OF_SERVER_1 \
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
        "MCP_AUTH_TOKEN": "<your-token>",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/UUID_OF_SERVER_1",
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
MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN} \
MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID_OF_SERVER_1 \
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
        "MCP_AUTH_TOKEN": "<your-token>",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/UUID_OF_SERVER_1"
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

## Configuration (`.env` or env vars)

> ⚠️ If any required `.env` variable is missing or invalid, the gateway will fail fast at startup with a validation error via Pydantic.

You can get started by copying the provided [.env.example](.env.example) to `.env` and making the necessary edits to fit your environment.

<details>
<summary><strong>🔧 Environment Configuration Variables</strong></summary>

### Basic

| Setting         | Description                              | Default                | Options                |
| --------------- | ---------------------------------------- | ---------------------- | ---------------------- |
| `APP_NAME`      | Gateway / OpenAPI title                  | `MCP Gateway`          | string                 |
| `HOST`          | Bind address for the app                 | `127.0.0.1`            | IPv4/IPv6              |
| `PORT`          | Port the server listens on               | `4444`                 | 1-65535                |
| `DATABASE_URL`  | SQLAlchemy connection URL                | `sqlite:///./mcp.db`   | any SQLAlchemy dialect |
| `APP_ROOT_PATH` | Subpath prefix for app (e.g. `/gateway`) | (empty)                | string                 |
| `TEMPLATES_DIR` | Path to Jinja2 templates                 | `mcpgateway/templates` | path                   |
| `STATIC_DIR`    | Path to static files                     | `mcpgateway/static`    | path                   |

> 💡 Use `APP_ROOT_PATH=/foo` if reverse-proxying under a subpath like `https://host.com/foo/`.

### Authentication

| Setting               | Description                                                      | Default       | Options    |
| --------------------- | ---------------------------------------------------------------- | ------------- | ---------- |
| `BASIC_AUTH_USER`     | Username for Admin UI login and HTTP Basic authentication        | `admin`       | string     |
| `BASIC_AUTH_PASSWORD` | Password for Admin UI login and HTTP Basic authentication        | `changeme`    | string     |
| `AUTH_REQUIRED`       | Require authentication for all API routes                        | `true`        | bool       |
| `JWT_SECRET_KEY`      | Secret key used to **sign JWT tokens** for API access            | `my-test-key` | string     |
| `JWT_ALGORITHM`       | Algorithm used to sign the JWTs (`HS256` is default, HMAC-based) | `HS256`       | PyJWT algs |
| `TOKEN_EXPIRY`        | Expiry of generated JWTs in minutes                              | `10080`       | int > 0    |
| `AUTH_ENCRYPTION_SECRET` | Passphrase used to derive AES key for encrypting tool auth headers | `my-test-salt` | string |

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
>   export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 0 --secret my-test-key)
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

> 🖥️ Set both to `false` to disable management UI and APIs in production.

### Security

| Setting                   | Description                    | Default                                        | Options    |
| ------------------------- | ------------------------------ | ---------------------------------------------- | ---------- |
| `SKIP_SSL_VERIFY`         | Skip upstream TLS verification | `false`                                        | bool       |
| `ALLOWED_ORIGINS`         | CORS allow-list                | `["http://localhost","http://localhost:4444"]` | JSON array |
| `CORS_ENABLED`            | Enable CORS                    | `true`                                         | bool       |
| `DOCS_ALLOW_BASIC_AUTH`   | Allow Basic Auth for docs (in addition to JWT)         | `false`                                        | bool       |

> Note: do not quote the ALLOWED_ORIGINS values, this needs to be valid JSON, such as:
> ALLOWED_ORIGINS=["http://localhost", "http://localhost:4444"]
>
> Documentation endpoints (`/docs`, `/redoc`, `/openapi.json`) are always protected by authentication.
> By default, they require Bearer token authentication. Setting `DOCS_ALLOW_BASIC_AUTH=true` enables HTTP Basic Authentication as an additional method using the same credentials as `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`.


### Logging

| Setting      | Description       | Default | Options            |
| ------------ | ----------------- | ------- | ------------------ |
| `LOG_LEVEL`  | Minimum log level | `INFO`  | `DEBUG`...`CRITICAL` |
| `LOG_FORMAT` | Log format        | `json`  | `json`, `text`     |
| `LOG_FILE`   | Log output file   | (none)  | path or empty      |

### Transport

| Setting                   | Description                        | Default | Options                         |
| ------------------------- | ---------------------------------- | ------- | ------------------------------- |
| `TRANSPORT_TYPE`          | Enabled transports                 | `all`   | `http`,`ws`,`sse`,`stdio`,`all` |
| `WEBSOCKET_PING_INTERVAL` | WebSocket ping (secs)              | `30`    | int > 0                         |
| `SSE_RETRY_TIMEOUT`       | SSE retry timeout (ms)             | `5000`  | int > 0                         |
| `USE_STATEFUL_SESSIONS`   | streamable http config             | `false` | bool                            |
| `JSON_RESPONSE_ENABLED`   | json/sse streams (streamable http) | `true`  | bool                            |

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
| `CACHE_TYPE`              | Backend (`memory`/`redis`) | `memory` | `none`, `memory`,`redis` |
| `REDIS_URL`               | Redis connection URL       | (none)   | string or empty          |
| `CACHE_PREFIX`            | Key prefix                 | `mcpgw:` | string                   |
| `REDIS_MAX_RETRIES`       | Max Retry Attempts         | `3`      | int > 0                  |
| `REDIS_RETRY_INTERVAL_MS` | Retry Interval (ms)        | `2000`   | int > 0                  |

> 🧠 `none` disables caching entirely. Use `memory` for dev, `database` for persistence, or `redis` for distributed caching.

### Database Management

MCP Gateway uses Alembic for database migrations. Common commands:

- `make db-current` - Show current database version
- `make db-upgrade` - Apply pending migrations
- `make db-migrate` - Create new migration
- `make db-history` - Show migration history
- `make db-status` - Detailed migration status

#### Troubleshooting

If you see "No 'script_location' key found", ensure you're running from the project root directory.

### Development

| Setting    | Description            | Default | Options |
| ---------- | ---------------------- | ------- | ------- |
| `DEV_MODE` | Enable dev mode        | `false` | bool    |
| `RELOAD`   | Auto-reload on changes | `false` | bool    |
| `DEBUG`    | Debug logging          | `false` | bool    |

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
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
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

MCP Context Forge implements comprehensive doctest coverage to ensure all code examples in documentation are tested and verified:

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
🐍 MCP CONTEXT FORGE  (An enterprise-ready Model Context Protocol Gateway)
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

Special thanks to our contributors for helping us improve ContextForge MCP Gateway:

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
