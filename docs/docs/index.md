---
classification:
status: draft
owner: Mihai Criveti
---

# MCP Gateway

A flexible FastAPI-based gateway and router for **Model Context Protocol (MCP)** with support for virtual servers. It acts as a unified interface for tools, resources, prompts, virtual servers, and federated gateways - all accessible via rich multi-transport APIs and an interactive web-based Admin UI.


<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agentic Core</title>
    <style>
        .diagram-body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f7fa;
            color: #2c3e50;
        }

        .diagram-container {
            max-width: 1200px;
            margin: 0 auto;
        }

        .diagram-h1 {
            text-align: center;
            color: #2c3e50;
            margin-bottom: 40px;
            font-size: 2.5em;
            font-weight: 600;
        }

        /* Agentic Core section */
        .diagram-agentic-core {
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: white;
            border-radius: 12px;
            padding: 40px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .diagram-section-title {
            color: white;
            font-size: 1.8em;
            text-align: center;
            margin-bottom: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        .diagram-three-column-layout {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 30px;
            align-items: start;
        }

        .diagram-column {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .diagram-component-group {
            background: rgba(255, 255, 255, 0.1);
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-radius: 12px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }

        .diagram-component-group:hover {
            background: rgba(255, 255, 255, 0.15);
            border-color: rgba(255, 255, 255, 0.5);
        }

        .diagram-group-title {
            font-size: 1.2em;
            font-weight: 600;
            margin-bottom: 15px;
            color: white;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .diagram-group-items {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .diagram-item {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            padding: 8px 14px;
            font-size: 0.95em;
            color: #ecf0f1;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s ease;
        }

        .diagram-item:hover {
            background: rgba(255, 255, 255, 0.25);
            transform: translateX(4px);
        }

        /* Center column special styling */
        .diagram-center-column {
            display: flex;
            flex-direction: column;
            gap: 20px;
            align-items: center;
        }

        .diagram-gateway-box {
            width: 100%;
            background: rgba(52, 152, 219, 0.2);
            border: 2px solid rgba(52, 152, 219, 0.6);
            border-radius: 12px;
            padding: 25px;
            text-align: center;
        }

        .diagram-gateway-box:hover {
            background: rgba(52, 152, 219, 0.3);
            border-color: rgba(52, 152, 219, 0.8);
        }

        .diagram-gateway-title {
            font-size: 1.3em;
            font-weight: 600;
            margin-bottom: 10px;
            color: white;
        }

        .diagram-open-source-badge {
            display: inline-block;
            background: rgba(46, 204, 113, 0.3);
            border: 1px solid rgba(46, 204, 113, 0.6);
            border-radius: 20px;
            padding: 4px 16px;
            font-size: 0.85em;
            margin-bottom: 20px;
            color: #2ecc71;
        }

        .diagram-capability-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            text-align: left;
            margin-top: 20px;
        }

        .diagram-capability {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 0.9em;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .diagram-protocol-detail {
            font-size: 0.8em;
            opacity: 0.8;
            margin-left: 24px;
            margin-top: 4px;
        }

        @media (max-width: 968px) {
            .diagram-three-column-layout {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="diagram-container">
        <div class="diagram-agentic-core">
            <div class="diagram-section-title">
                ⚡ ContextForge MCP Gateway Use Case Overview
            </div>

            <div class="diagram-three-column-layout">
                <!-- Left Column -->
                <div class="diagram-column">
                    <div class="diagram-component-group">
                        <div class="diagram-group-title">🤖 Agent Frameworks</div>
                        <div class="diagram-group-items">
                            <div class="diagram-item">🔗 Langchain</div>
                            <div class="diagram-item">📊 Langgraph</div>
                            <div class="diagram-item">👥 crew.ai</div>
                            <div class="diagram-item">🔄 Autogen</div>
                            <div class="diagram-item">🐍 PydanticAI</div>
                            <div class="diagram-item">🤗 Huggingface Smol</div>
                            <div class="diagram-item">🐝 Agent Bee</div>
                        </div>
                    </div>

                    <div class="diagram-component-group">
                        <div class="diagram-group-title">💻 Visual Studio Code</div>
                        <div class="diagram-group-items">
                            <div class="diagram-item">🤖 GitHub Copilot</div>
                            <div class="diagram-item">🔧 Cline</div>
                            <div class="diagram-item">➡️ Continue</div>
                        </div>
                    </div>

                    <div class="diagram-component-group">
                        <div class="diagram-group-title">🔧 Other Clients</div>
                        <div class="diagram-group-items">
                            <div class="diagram-item">🌐 OpenWebUI</div>
                            <div class="diagram-item">⌨️ MCP-CLI</div>
                        </div>
                    </div>
                </div>

                <!-- Center Column -->
                <div class="diagram-center-column">
                    <div class="diagram-gateway-box">
                        <div class="diagram-gateway-title">🌐 MCP Gateway</div>
                        <div class="diagram-capability-list">
                            <div class="diagram-capability">📚 MCP Registry</div>
                            <div class="diagram-capability">🖥️ Virtual Servers</div>
                            <div class="diagram-capability">🔐 Authorization</div>
                            <div class="diagram-capability">🔑 Authentication</div>
                            <div class="diagram-capability" style="padding: 10px 12px;">
                                <div>🔄 Protocol Conversion → any to any</div>
                                <div style="font-size: 0.8em; opacity: 0.8; margin-left: 24px;">(stdio, SSE, Streamable HTTP, JSON-RPC, REST)</div>
                            </div>
                            <div class="diagram-capability">📊 Observability</div>
                            <div class="diagram-capability">⏱️ Rate Limiting</div>
                            <div class="diagram-capability">🔀 HA / Routing</div>
                            <div class="diagram-capability">💚 Healthchecks</div>
                            <div class="diagram-capability">🛠️ API / UI / CLI</div>
                        </div>
                    </div>

                    <div class="diagram-gateway-box">
                        <div class="diagram-gateway-title">🔌 Plugin Framework</div>
                        <div class="diagram-capability-list">
                            <div class="diagram-capability">🔒 PII Filtering</div>
                            <div class="diagram-capability">🛡️ XSS Filtering</div>
                            <div class="diagram-capability">📋 Open Policy Agent</div>
                        </div>
                    </div>
                </div>

                <!-- Right Column -->
                <div class="diagram-column">
                    <div class="diagram-component-group">
                        <div class="diagram-group-title">🔌 MCP Servers</div>
                        <div class="diagram-group-items">
                            <div class="diagram-item">🐙 GitHub</div>
                            <div class="diagram-item">📋 Jira</div>
                            <div class="diagram-item">🎫 ServiceNow</div>
                            <div class="diagram-item">🎭 Playwright</div>
                            <div class="diagram-item">🎨 Figma</div>
                            <div class="diagram-item">📅 Monday</div>
                            <div class="diagram-item">📦 Box</div>
                            <div class="diagram-item">🌐 Internet Search</div>
                        </div>
                    </div>

                    <div class="diagram-component-group">
                        <div class="diagram-group-title">🔗 REST APIs</div>
                        <div class="diagram-group-items">
                            <div class="diagram-item">🌍 External Services</div>
                            <div class="diagram-item">☁️ Cloud Providers</div>
                            <div class="diagram-item">📊 Data Sources</div>
                            <div class="diagram-item">🏢 Enterprise Systems</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>

![MCP Gateway](images/mcpgateway.gif)

**⚠️ Important**: MCP Gateway is not a standalone product - it is an open source component with **NO OFFICIAL SUPPORT** from IBM or its affiliates that can be integrated into your own solution architecture. If you choose to use it, you are responsible for evaluating its fit, securing the deployment, and managing its lifecycle. See [SECURITY.md](https://github.com/IBM/mcp-context-forge/blob/main/SECURITY.md) for more details, and the [roadmap](architecture/roadmap.md) for upcoming features.

---

## What it Does

- 🚪 Acts as a **gateway layer** in front of MCP servers or APIs
- 🔗 Connects and federates multiple MCP backends (auto-discovery, fail-over, merging)
- 🔄 Virtualizes REST APIs and external MCP servers as compliant tools and servers
- 🛠️ Centralizes registration and management of tools, prompts, and resources
- 📡 Exposes all endpoints over HTTP/JSON-RPC, WebSocket, Server-Sent Events (SSE), and **stdio**
- 📦 Provides a stdio wrapper (`mcpgateway-wrapper`) for terminal-based or headless MCP clients

---

## Key Features

- **Multi-Transport**: HTTP, WebSocket, SSE, Streamable HTTP and stdio with auto-negotiation
- **Federation & Health Checks**: Auto-discovery (mDNS or static), syncing, monitoring
- **Admin UI**: Real-time management (HTMX + Tailwind)
- **Tool Wrapping**: REST / CLI / local functions with JSON-Schema validation
- **Security**: JWT + Basic Auth, custom headers, rate limits, SSL control
- **Caching & Observability**: Redis/in-memory/database caching, metrics, structured logs
- **Virtual Servers**: Group tools/resources/prompts into MCP-compliant servers
- **Wrapper Mode**: `mcpgateway-wrapper` turns any remote gateway into a local stdio MCP server

For upcoming capabilities, see the [Roadmap](architecture/roadmap.md).

```mermaid
graph TD
    subgraph UI_and_Auth
        UI[🖥️ Admin UI]
        Auth[🔐 Auth - JWT and Basic]
        UI --> Core
        Auth --> Core
    end

    subgraph Gateway_Core
        Core[🚪 MCP Gateway Core]
        Protocol[📡 Protocol - Init Ping Completion]
        Federation[🌐 Federation Manager]
        Transports[🔀 Transports - HTTP WS SSE Stdio]
        Core --> Protocol
        Core --> Federation
        Core --> Transports
    end

    subgraph Services
        Tools[🧰 Tool Service]
        Resources[📁 Resource Service]
        Prompts[📝 Prompt Service]
        Servers[🧩 Server Service]
        Core --> Tools
        Core --> Resources
        Core --> Prompts
        Core --> Servers
    end

    subgraph Persistence
        DB[💾 Database - SQLAlchemy]
        Tools --> DB
        Resources --> DB
        Prompts --> DB
        Servers --> DB
    end

    subgraph Caching
        Cache[⚡ Cache - Redis or Memory]
        Core --> Cache
    end
```

---

## Audience

MCP Gateway serves:

* **AI Platform Teams** building unified gateways for LLM tools & services
* **DevOps Engineers** deploying secure, observable, federated control planes
* **Open-source contributors** extending MCP tooling or adapters
* **Cloud Architects** running on Kubernetes, IBM Code Engine, AWS, Azure, or bare Docker

---

## Installation & Deployment

| Scenario                      | One-liner / CLI Snippet                                                                              | Docs                                             |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| **Local (PyPI)**              | `pip install mcp-contextforge-gateway && mcpgateway --host 0.0.0.0 --port 4444`                      | [Quick Start](overview/quick_start.md)           |
| **Docker / Podman**           | `docker run -p 4444:4444 ghcr.io/ibm/mcp-context-forge:<tag>`                                        | [Containers](deployment/container.md)            |
| **Docker-Compose (dev)**      | `docker compose up`                                                                                  | [Compose](deployment/compose.md)                 |
| **Helm / Vanilla Kubernetes** | `helm repo add mcpgw https://IBM.github.io/mcp-context-forge && helm install mcpgw mcpgw/mcpgateway` | [Helm Chart](deployment/helm.md)                 |
| **Minikube (local k8s)**      | `make minikube`                                                                                      | [Minikube Guide](deployment/minikube.md)         |
| **OpenShift / OKD**           | `oc apply -k openshift/`                                                                             | [OpenShift](deployment/openshift.md)             |
| **Argo CD / GitOps**          | `kubectl apply -f argo.yaml`                                                                         | [Argo CD](deployment/argocd.md)                  |
| **IBM Cloud - Code Engine**   | `ibmcloud ce app create --name mcpgw --image ghcr.io/ibm/mcp-context-forge:<tag>`                    | [IBM Code Engine](deployment/ibm-code-engine.md) |
| **AWS - ECS (Fargate)**       | `aws ecs create-service --cli-input-json file://ecs.json`                                            | [AWS Guide](deployment/aws.md)                   |
| **AWS - EKS (Helm)**          | `helm install mcpgw mcpgw/mcpgateway`                                                                | [AWS Guide](deployment/aws.md)                   |
| **Google Cloud Run**          | `gcloud run deploy mcpgw --image ghcr.io/ibm/mcp-context-forge:<tag>`                                | [GCP Cloud Run](deployment/google-cloud-run.md)  |
| **Google GKE (Helm)**         | `helm install mcpgw mcpgw/mcpgateway`                                                                | [GCP Guide](deployment/google-cloud-run.md)      |
| **Azure - Container Apps**    | `az containerapp up --name mcpgw --image ghcr.io/ibm/mcp-context-forge:<tag>`                        | [Azure Guide](deployment/azure.md)               |
| **Azure - AKS (Helm)**        | `helm install mcpgw mcpgw/mcpgateway`                                                                | [Azure Guide](deployment/azure.md)               |


> **PyPI Package**: [`mcp-contextforge-gateway`](https://pypi.org/project/mcp-contextforge-gateway/)

> **OCI Image**: [`ghcr.io/ibm/mcp-context-forge:0.5.0`](https://github.com/IBM/mcp-context-forge/pkgs/container/mcp-context-forge)

---

## Get Started

Jump straight to:

* [Quick Start Guide](overview/quick_start.md)
* [Features Overview](overview/features.md)
* [Admin UI Walk-through](overview/ui.md)
* [Using the `mcpgateway-wrapper`](using/mcpgateway-wrapper.md)
* [Deployment Options](deployment/index.md)

!!! note
    Source → [https://github.com/IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge)

    Docs → [https://ibm.github.io/mcp-context-forge/](https://ibm.github.io/mcp-context-forge/)

---

## Authors and Contributors

* **Mihai Criveti** - IBM Distinguished Engineer, Agentic AI

<!-- [Download PDF](pdf/mcpgateway-docs.pdf){ .md-button } [Download DOCX](out/mcpgateway-docs.docx){ .md-button } -->
