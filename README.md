# MCP Gateway

> Model Context Protocol gateway & proxy — unify REST, MCP, and A2A with federation, virtual servers, retries, security, and an optional admin UI.

![](docs/docs/images/contextforge-banner.png)

<!-- === CI / Security / Build Badges === -->
[![Build Python Package](https://github.com/IBM/mcp-context-forge/actions/workflows/python-package.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/python-package.yml)&nbsp;
[![CodeQL](https://github.com/IBM/mcp-context-forge/actions/workflows/codeql.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/codeql.yml)&nbsp;
[![Bandit Security](https://github.com/IBM/mcp-context-forge/actions/workflows/bandit.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/bandit.yml)&nbsp;
[![Dependency Review](https://github.com/IBM/mcp-context-forge/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/dependency-review.yml)&nbsp;
[![Tests & Coverage](https://github.com/IBM/mcp-context-forge/actions/workflows/pytest.yml/badge.svg)](https://github.com/IBM/mcp-context-forge/actions/workflows/pytest.yml)&nbsp;

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
- [Overview & Goals](#-overview--goals)
- [Quick Start — PyPI](#quick-start--pypi)
  - [1 · Install & run (copy‑paste friendly)](#1--install--run-copypaste-friendly)
- [Quick Start — Containers](#quick-start--containers)
  - [Docker](#-docker)
    - [1 · Minimum viable run](#1--minimum-viable-run)
    - [2 · Persist the SQLite database](#2--persist-the-sqlite-database)
    - [3 · Local tool discovery (host network)](#3--local-tool-discovery-host-network)
  - [Podman (rootless-friendly)](#-podman-rootless-friendly)
    - [1 · Basic run](#1--basic-run)
    - [2 · Persist SQLite](#2--persist-sqlite)
    - [3 · Host networking (rootless)](#3--host-networking-rootless)
- [Testing `mcpgateway.wrapper` by hand:](#testing-mcpgatewaywrapper-by-hand)
  - [Running from an MCP Client (`mcpgateway.wrapper`)](#-running-from-an-mcp-client-mcpgatewaywrapper)
    - [1 · Install <code>uv</code>  (<code>uvenv</code> is an alias it provides)](#1--install-uv--uvenv-is-an-alias-it-provides)
    - [2 · Create an on-the-spot venv & run the wrapper](#2--create-an-on-the-spot-venv--run-the-wrapper)
    - [Claude Desktop JSON (runs through **uvenv run**)](#claude-desktop-json-runs-through-uvenv-run)
  - [Using with Claude Desktop (or any GUI MCP client)](#-using-with-claude-desktop-or-any-gui-mcp-client)
- [Quick Start: VS Code Dev Container](#-quick-start-vs-code-dev-container)
  - [1 · Clone & Open](#1--clone--open)
  - [2 · First-Time Build (Automatic)](#2--first-time-build-automatic)
- [Quick Start (manual install)](#quick-start-manual-install)
  - [Prerequisites](#prerequisites)
  - [One-liner (dev)](#one-liner-dev)
  - [Containerised (self-signed TLS)](#containerised-self-signed-tls)
  - [Smoke-test the API](#smoke-test-the-api)
- [Installation](#installation)
  - [Via Make](#via-make)
  - [UV (alternative)](#uv-alternative)
  - [pip (alternative)](#pip-alternative)
  - [Optional (PostgreSQL adapter)](#optional-postgresql-adapter)
    - [Quick Postgres container](#quick-postgres-container)
- [Configuration (`.env` or env vars)](#configuration-env-or-env-vars)
  - [Basic](#basic)
  - [Authentication](#authentication)
  - [UI Features](#ui-features)
  - [Security](#security)
  - [Logging](#logging)
  - [Transport](#transport)
  - [Federation](#federation)
  - [Resources](#resources)
  - [Tools](#tools)
  - [Prompts](#prompts)
  - [Health Checks](#health-checks)
  - [Database](#database)
  - [Cache Backend](#cache-backend)
  - [Development](#development)
- [Running](#running)
- [Makefile](#makefile)
  - [Script helper](#script-helper)
  - [Manual (Uvicorn)](#manual-uvicorn)
- [Authentication examples](#authentication-examples)
- [AWS / Azure / OpenShift](#️-aws--azure--openshift)
- [IBM Cloud Code Engine Deployment](#️-ibm-cloud-code-engine-deployment)
  - [Prerequisites](#-prerequisites)
  - [Environment Variables](#-environment-variables)
  - [Make Targets](#-make-targets)
  - [Example Workflow](#-example-workflow)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [API Documentation](#api-documentation)
- [Makefile targets](#makefile-targets)
- [Troubleshooting](#-troubleshooting)
  - [Diagnose the listener](#diagnose-the-listener)
  - [Why localhost fails on Windows](#why-localhost-fails-on-windows)
    - [Fix (Podman rootless)](#fix-podman-rootless)
    - [Fix (Docker Desktop > 4.19)](#fix-docker-desktop--419)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [License](#license)
- [Core Authors and Maintainers](#core-authors-and-maintainers)
- [Star History and Project Activity](#star-history-and-project-activity)


## 🚀 Overview & Goals

**ContextForge MCP Gateway** is a production-grade gateway, registry, and proxy that sits in front of any [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server or REST API—exposing a unified endpoint for all your AI clients.

It supports:

* Federation across multiple MCP and REST services
* Virtualization of legacy APIs as MCP-compliant tools and servers
* Transport over HTTP, JSON-RPC, WebSocket, SSE, stdio and streamable-HTTP
* An Admin UI for real-time management and configuration
* Built-in auth, observability, retries, and rate-limiting
* Scalable deployments via Docker or PyPI, Redis-backed caching, and multi-cluster federation

![MCP Gateway Architecture](https://ibm.github.io/mcp-context-forge/images/mcpgateway.svg)

For a list of upcoming features, check out the [ContextForge MCP Gateway Roadmap](https://ibm.github.io/mcp-context-forge/architecture/roadmap/)

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

## Quick Start — PyPI

MCP Gateway is published on [PyPI](https://pypi.org/project/mcp-contextforge-gateway/) as `mcp-contextforge-gateway`.

---

<details>
<summary><strong>📋 Prerequisites</strong></summary>

* **Python ≥ 3.10** (3.11 recommended)
* **curl + jq** – only for the last smoke‑test step

</details>

### 1 · Install & run (copy‑paste friendly)

```bash
# 1️⃣  Isolated env + install from pypi
mkdir mcpgateway && cd mcpgateway
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install mcp-contextforge-gateway

# 2️⃣  Launch on all interfaces with custom creds & secret key
BASIC_AUTH_PASSWORD=pass JWT_SECRET_KEY=my-test-key \
  mcpgateway --host 0.0.0.0 --port 4444 &   # admin/pass

# 3️⃣  Generate a bearer token & smoke‑test the API
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 10080 --secret my-test-key)

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/version | jq
```

<details>
<summary><strong>More configuration</strong></summary>

Copy [.env.example](.env.example) to `.env` and tweak any of the settings (or use them as env variables).

</details>

<details>
<summary><strong>🚀 End‑to‑end demo (register a local MCP server)</strong></summary>

```bash
# 1️⃣  Spin up a sample MCP server (Node supergateway)
pip install uvenv
npx -y supergateway --stdio "uvenv run mcp_server_time -- --local-timezone=Europe/Dublin" --port 8002 &

# 2️⃣  Register it with the gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"local_time","url":"http://localhost:8002/sse"}' \
     http://localhost:4444/gateways

# 3️⃣  Verify tool catalog
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools | jq

# 4️⃣  Create a *virtual server* bundling those tools
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"demo_server","description":"Time tools","associatedTools":["1","2"]}' \
     http://localhost:4444/servers | jq

# 5️⃣  List servers (should now include ID 1)
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers | jq

# 6️⃣  Client SSE endpoint. Inspect it interactively with the MCP Inspector CLI (or use any MCP client)
npx -y @modelcontextprotocol/inspector
# Transport Type: SSE, URL: http://localhost:4444/servers/1/sse,  Header Name: "Authorization", Bearer Token
```

</details>

<details>
<summary><strong>🖧 Using the stdio wrapper (mcpgateway-wrapper)</strong></summary>

```bash
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1
python3 -m mcpgateway.wrapper  # Ctrl‑C to exit
```

You can also run it with `uv` or inside Docker/Podman – see the *Containers* section above.

In MCP Inspector, define `MCP_AUTH_TOKEN` and `MCP_SERVER_CATALOG_URLS` env variables, and select `python3` as the Command, and `-m mcpgateway.wrapper` as Arguments.

```bash
echo $PWD/.venv/bin/python3 # Using the Python3 full path ensures you have a working venv
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/1'
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
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

</details>

---

## Quick Start — Containers

Use the official OCI image from GHCR with **Docker** *or* **Podman**.

---

### 🐳 Docker

#### 1 · Minimum viable run

```bash
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  -e DATABASE_URL=sqlite:///./mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.1.1

# Tail logs (Ctrl+C to quit)
docker logs -f mcpgateway

# Generating an API key
docker run --rm -it ghcr.io/ibm/mcp-context-forge:0.1.1 \
  python -m mcpgateway.utils.create_jwt_token --username admin --exp 0 --secret my-test-key
```

Browse to **[http://localhost:4444/admin](http://localhost:4444/admin)** (user `admin` / pass `changeme`).

#### 2 · Persist the SQLite database

```bash
mkdir -p $(pwd)/data

docker run -d --name mcpgateway \
  --restart unless-stopped \
  -p 4444:4444 \
  -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-test-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  ghcr.io/ibm/mcp-context-forge:0.1.1
```

SQLite now lives on the host at `./data/mcp.db`.

#### 3 · Local tool discovery (host network)

```bash
docker run -d --name mcpgateway \
  --network=host \
  -e HOST=0.0.0.0 \
  -e PORT=4444 \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -v $(pwd)/data:/data \
  ghcr.io/ibm/mcp-context-forge:0.1.1
```

Using `--network=host` allows Docker to access the local network, allowing you to add MCP servers running on your host. See [Docker Host network driver documentation](https://docs.docker.com/engine/network/drivers/host/) for more details.

---

### 🦭 Podman (rootless-friendly)

#### 1 · Basic run

```bash
podman run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e DATABASE_URL=sqlite:///./mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.1.1
```

#### 2 · Persist SQLite

```bash
mkdir -p $(pwd)/data

podman run -d --name mcpgateway \
  --restart=on-failure \
  -p 4444:4444 \
  -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.1.1
```

#### 3 · Host networking (rootless)

```bash
podman run -d --name mcpgateway \
  --network=host \
  -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  ghcr.io/ibm/mcp-context-forge:0.1.1
```

---

<details>
<summary><strong>✏️ Docker/Podman tips</strong></summary>

* **.env files** — Put all the `-e FOO=` lines into a file and replace them with `--env-file .env`. See the provided [.env.example](.env.example) for reference.
* **Pinned tags** — Use an explicit version (e.g. `v0.1.1`) instead of `latest` for reproducible builds.
* **JWT tokens** — Generate one in the running container:

  ```bash
  docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token -u admin -e 10080 --secret my-test-key
  ```
* **Upgrades** — Stop, remove, and rerun with the same `-v $(pwd)/data:/data` mount; your DB and config stay intact.

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
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/1'
export MCP_TOOL_CALL_TIMEOUT=120
export MCP_WRAPPER_LOG_LEVEL=DEBUG  # or OFF to disable logging

docker run --rm -i \
  -e MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN \
  -e MCP_SERVER_CATALOG_URLS=http://host.docker.internal:4444/servers/1 \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  -e MCP_WRAPPER_LOG_LEVEL=DEBUG \
  ghcr.io/ibm/mcp-context-forge:0.1.1 \
  python3 -m mcpgateway.wrapper
```

</details>

---

## Testing `mcpgateway.wrapper` by hand:

Because the wrapper speaks JSON-RPC over stdin/stdout, you can interact with it using nothing more than a terminal or pipes.

```bash
# Run a time server, then register it in your gateway..
pip install mcp-server-time
npx -y supergateway --stdio "uvenv run mcp_server_time -- --local-timezone=Europe/Dublin"

# Start the MCP Gateway Wrapper
export MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN}
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1
python3 -m mcpgateway.wrapper
# Alternatively with uv
uv run --directory . -m mcpgateway.wrapper
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
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_current_time","arguments":{"timezone":"Europe/Dublin"}}}
```

</details>

<details>
<summary><strong>Expected responses from mcpgateway.wrapper</strong></summary>

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false}},"serverInfo":{"name":"mcpgateway-wrapper","version":"0.1.1"}}}

# When there's no tools
{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}

# After you add some tools and create a virtual server
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_current_time","description":"Get current time in a specific timezones","inputSchema":{"type":"object","properties":{"timezone":{"type":"string","description":"IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Use 'America/New_York' as local timezone if no timezone provided by the user."}},"required":["timezone"]}}]}}

# Running the time tool:
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{'content': [{'type': 'text', 'text': '{\\n  \"timezone\": \"Europe/Dublin\",\\n  \"datetime\": \"2025-06-08T21:47:07+01:00\",\\n  \"is_dst\": true\\n}'}], 'is_error': False}"}],"isError":false}}
```

</details>

### 🧩 Running from an MCP Client (`mcpgateway.wrapper`)

The `mcpgateway.wrapper` exposes everything your Gateway knows about over **stdio**, so any MCP client that *can't* (or *shouldn't*) open an authenticated SSE stream still gets full tool-calling power.

> **Remember** to substitute your real Gateway URL (and server ID) for `http://localhost:4444/servers/1`.
> When inside Docker/Podman, that often becomes `http://host.docker.internal:4444/servers/1` (macOS/Windows) or the gateway container's hostname (Linux).

---

<details>
<summary><strong>🐳 Docker / Podman</strong></summary>

```bash
docker run -i --rm \
  --network=host \
  -e MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1 \
  -e MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN} \
  -e MCP_TOOL_CALL_TIMEOUT=120 \
  ghcr.io/ibm/mcp-context-forge:0.1.1 \
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
MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1 \
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
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

</details>

---

<details>
<summary><strong>⚡ uv / uvenv (light-speed venvs)</strong></summary>

#### 1 · Install <code>uv</code>  (<code>uvenv</code> is an alias it provides)

```bash
# (a) official one-liner
curl -Ls https://astral.sh/uv/install.sh | sh

# (b) or via pipx
pipx install uv
```

#### 2 · Create an on-the-spot venv & run the wrapper

```bash
# Create venv in ~/.venv/mcpgateway (or current dir if you prefer)
uv venv ~/.venv/mcpgateway
source ~/.venv/mcpgateway/bin/activate

# Install the gateway package using uv
uv pip install mcp-contextforge-gateway

# Launch wrapper
MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN} \
MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1 \
uv run --directory . -m mcpgateway.wrapper # Use this just for testing, as the Client will run the uv command
```

#### Claude Desktop JSON (runs through **uvenv run**)

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "uvenv",
      "args": [
        "run",
        "--",
        "python",
        "-m",
        "mcpgateway.wrapper"
      ],
      "env": {
        "MCP_AUTH_TOKEN": "<your-token>",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1"
    }
  }
}
```

</details>

---

### 🚀 Using with Claude Desktop (or any GUI MCP client)

1. **Edit Config** → `File ▸ Settings ▸ Developer ▸ Edit Config`
2. Paste one of the JSON blocks above (Docker / pipx / uvenv).
3. Restart the app so the new stdio server is spawned.
4. Open logs in the same menu to verify `mcpgateway-wrapper` started and listed your tools.

Need help? See:

* **MCP Debugging Guide** – [https://modelcontextprotocol.io/docs/tools/debugging](https://modelcontextprotocol.io/docs/tools/debugging)

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

### 1 · Clone & Open

```bash
git clone https://github.com/ibm/mcp-context-forge.git
cd mcp-context-forge
code .
```

VS Code will detect the `.devcontainer` and prompt:
**"Reopen in Container"**
*or* manually run: <kbd>Ctrl/Cmd ⇧ P</kbd> → **Dev Containers: Reopen in Container**

---

### 2 · First-Time Build (Automatic)

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

* `make bash` — drop into an interactive shell
* `make clean` — clear build artefacts & caches
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
* Optional: **Docker / Podman** for containerised runs

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

### Containerised (self-signed TLS)


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
| `HOST`          | Bind address for the app                 | `0.0.0.0`              | IPv4/IPv6              |
| `PORT`          | Port the server listens on               | `4444`                 | 1–65535                |
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
>   python3 -m mcpgateway.utils.create_jwt_token -u admin -e 10080 > token.txt
>   export MCPGATEWAY_BEARER_TOKEN=$(cat token.txt)
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
| `MCPGATEWAY_UI_ENABLED`        | Enable the interactive Admin dashboard | `true`  | bool    |
| `MCPGATEWAY_ADMIN_API_ENABLED` | Enable API endpoints for admin ops     | `true`  | bool    |

> 🖥️ Set both to `false` to disable management UI and APIs in production.

### Security

| Setting           | Description                    | Default                                        | Options    |
| ----------------- | ------------------------------ | ---------------------------------------------- | ---------- |
| `SKIP_SSL_VERIFY` | Skip upstream TLS verification | `false`                                        | bool       |
| `ALLOWED_ORIGINS` | CORS allow‐list                | `["http://localhost","http://localhost:4444"]` | JSON array |
| `CORS_ENABLED`    | Enable CORS                    | `true`                                         | bool       |

> Note: do not quote the ALLOWED_ORIGINS values, this needs to be valid JSON, such as: `ALLOWED_ORIGINS=["http://localhost", "http://localhost:4444"]`

### Logging

| Setting      | Description       | Default | Options            |
| ------------ | ----------------- | ------- | ------------------ |
| `LOG_LEVEL`  | Minimum log level | `INFO`  | `DEBUG`…`CRITICAL` |
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
| `FEDERATION_DISCOVERY`     | Auto‐discover peers    | `false` | bool       |
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

| Setting           | Description                     | Default | Options |
| ----------------- | ------------------------------- | ------- | ------- |
| `DB_POOL_SIZE`    | SQLAlchemy connection pool size | `200`   | int > 0 |
| `DB_MAX_OVERFLOW` | Extra connections beyond pool   | `10`    | int ≥ 0 |
| `DB_POOL_TIMEOUT` | Wait for connection (secs)      | `30`    | int > 0 |
| `DB_POOL_RECYCLE` | Recycle connections (secs)      | `3600`  | int > 0 |

### Cache Backend

| Setting        | Description                | Default  | Options                  |
| -------------- | -------------------------- | -------- | ------------------------ |
| `CACHE_TYPE`   | Backend (`memory`/`redis`) | `memory` | `none`, `memory`,`redis` |
| `REDIS_URL`    | Redis connection URL       | (none)   | string or empty          |
| `CACHE_PREFIX` | Key prefix                 | `mcpgw:` | string                   |

> 🧠 `none` disables caching entirely. Use `memory` for dev, `database` for persistence, or `redis` for distributed caching.

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
IBMCLOUD_API_KEY=your_api_key_here   # Optional – omit to use interactive `ibmcloud login --sso`

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
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers/1

# Create server
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"db","description":"Database","associatedTools": ["1","2","3"]}' \
     http://localhost:4444/servers

# Update server
curl -X PUT -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"description":"Updated"}' \
     http://localhost:4444/servers/1

# Toggle active
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/servers/1/toggle?activate=false
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
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff, black, mypy, …)
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
│   │   ├── templates/…             # Manifest templates
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
│   │   └── manager.py              # Orchestration & health checks
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
│   ├── types.py                    # Core enums / type aliases
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
│   ├── e2e/…                       # End-to-end scenarios
│   ├── hey/…                       # Load-test logs & helper script
│   ├── integration/…               # API-level integration tests
│   └── unit/…                      # Pure unit tests for business logic
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
jsonlint            - Validate every *.json file with jq (‐‐exit-status)
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
sonar-submit-docker  - Run containerised Sonar Scanner CLI with Docker
sonar-submit-podman  - Run containerised Sonar Scanner CLI with Podman
pysonar-scanner      - Run scan with Python wrapper (pysonar-scanner)
sonar-info           - How to create a token & which env vars to export
🛡️ SECURITY & PACKAGE SCANNING
trivy                - Scan container image for CVEs (HIGH/CRIT). Needs podman socket enabled
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
minikube-k8s-apply    - Apply Kubernetes manifests from k8s/
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

*Seeing `:::4444 LISTEN rootlessport` is normal* – the IPv6 wildcard
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
4. Open a PR – describe your changes clearly.

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.
---

## Changelog

A complete changelog can be found here: [CHANGELOG.md](./CHANGELOG.md)

## License

Licensed under the **Apache License 2.0** – see [LICENSE](./LICENSE)


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
