# 🧰 Media Kit

Everything you need to write about **[ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)**-assets, ready-to-use copy, badges, images, and quick-start commands.

---

## 🤔 What is MCP (Model Context Protocol)?

[MCP](https://modelcontextprotocol.io/introduction) is an open-source protocol released by Anthropic in **November 2024** that lets AI agents communicate with external tools through a standard JSON-RPC envelope. It's often described as the "USB-C of AI"-a universal connector for language models.

It's widely supported by GitHub Copilot, Microsoft Copilot, AWS Bedrock, Google Cloud AI, IBM watsonx, and **15,000+ servers** in the community.

### ⚡ Why it matters

- ✅ Standardized interface contracts via typed JSON Schema
- ✅ Supported across the ecosystem - GitHub/Microsoft Copilot, AWS Bedrock, Google Cloud AI, IBM watsonx, AgentBee, LangChain, CrewAI, and more
- ✅ Strong ecosystem - **15,000+** MCP-compatible servers and multiple clients, with announcements from multiple major vendors

### ❌ Current challenges

- ❌ Fragmented transports: STDIO, SSE, HTTP - with some methods already deprecated
- ❌ Inconsistent authentication: none, JWT, OAuth
- ❌ Operational overhead: managing endpoints, credentials, retries, and logs for each tool
- ❌ Version mismatch: clients and servers may support different MCP versions

---

## 💡 Why [ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)?

> **Problem:** Most teams build one-off adapters for each tool or model, leading to maintenance burden and slow development.

[ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge) solves this by proxying all MCP and REST tool servers through a **single HTTPS + JSON-RPC endpoint**, with discovery, security, and observability built in.

It lets you create Virtual Servers - remixing tools/prompts/resources from multiple servers, introduce strong Auth - and change protocol versions on the fly. It lets you easily create new MCP Servers without having to write any code - by proxing existing REST services.

And is readily available as open source, published a container image and as a Python module published on PyPi - so you can get started with a single command - and scale all the way up to multi-regional Kubernetes clusters.

| Pain Point                           | How Gateway Solves It                            |
|--------------------------------------|--------------------------------------------------|
| Transport fragmentation (STDIO/SSE/HTTP) | Unifies everything under HTTPS + JSON-RPC    |
| DIY wrappers & retry logic           | Automatic, schema-validated retry handling       |
| Weak auth layers                     | Built-in JWT (or OAuth) & rate limiting          |
| No visibility                        | Per-call and per-server metrics & logging        |
| Onboarding difficulties              | Built-in admin UI for tools, prompts, and resources |

![Architecture Overview](https://ibm.github.io/mcp-context-forge/images/mcpgateway.svg)

---

## 📑 Sample Announcements

???+ "📣 Non-Technical Post"
    ### Meet ContextForge MCP Gateway: Simplify AI Tool Connections

    Building AI agents should be easy-but each tool speaks a different dialect.

    **[ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)** is a universal hub: one secure endpoint that discovers your tools and works seamlessly with Copilot, CrewAI, LangChain, and more.

    > "What should be simple often becomes a debugging nightmare. The ContextForge MCP Gateway solves that." - Mihai Criveti

    **Try it in 60 seconds:**
    ```bash
    docker run -d --name mcpgateway \
      -p 4444:4444 \
      -e JWT_SECRET_KEY=YOUR_KEY \
      -e PLATFORM_ADMIN_EMAIL=admin@example.com \
      -e PLATFORM_ADMIN_PASSWORD=changeme \
      -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
      ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
    ```

    Please ⭐ the project on GitHub if you find this useful, it helps us grow!

???+ "🛠️ Technical Post"
    ### Introducing ContextForge MCP Gateway: The Missing Proxy for AI Agents and Tools

    **[ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)** normalizes STDIO, SSE, REST, and HTTP MCP servers into one HTTPS + JSON-RPC interface with full MCP support.

    It includes schema-validated retries, JWT auth, and a built-in catalog UI.

    **Docker:**
    ```bash
    docker run -d --name mcpgateway \
      -p 4444:4444 \
      -e JWT_SECRET_KEY=YOUR_KEY \
      -e PLATFORM_ADMIN_EMAIL=admin@example.com \
      -e PLATFORM_ADMIN_PASSWORD=changeme \
      -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
      ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
    ```

    **PyPI:**
    ```bash
    pip install mcp-contextforge-gateway

    # Option 1: Use the provided .env.example
    curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
    cp .env.example .env
    # Edit .env to customize your settings
    mcpgateway --host 0.0.0.0 --port 4444

    # Option 2: Set environment variables directly
    PLATFORM_ADMIN_EMAIL=admin@example.com \
    PLATFORM_ADMIN_PASSWORD=changeme \
    PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
    mcpgateway --host 0.0.0.0 --port 4444
    ```

    Please ⭐ the project on GitHub if you find this useful, it helps us grow!

---

???+ "🛠️ Connect Cline VS Code Extension to ContextForge MCP Gateway"

    > A great idea is to create posts, videos or articles on using specific clients or with MCP Gateway.
    Provide details on how to run and register a number of useful MCP Servers, adding them to the gateway, then using specific clients to connect. For example, Visual Studio Cline, GitHub Copilot, Langchain, etc. Example:

    ### Connect your Cline extension to MCP Gateway

    **[ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)** offers a unified HTTPS + JSON-RPC endpoint for AI tools, making integration seamless-including with **Cline**, a VS Code extension that supports MCP.

    **Start the Gateway (Docker):**
    ```bash
    docker run -d --name mcpgateway \
      -p 4444:4444 \
      -e JWT_SECRET_KEY=YOUR_KEY \
      -e PLATFORM_ADMIN_EMAIL=admin@example.com \
      -e PLATFORM_ADMIN_PASSWORD=changeme \
      -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
      ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
    ```

    **Or install via PyPI:**

    ```bash
    pip install mcp-contextforge-gateway

    # Option 1: Use the provided .env.example
    curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
    cp .env.example .env
    # Edit .env to customize your settings
    mcpgateway --host 0.0.0.0 --port 4444

    # Option 2: Set environment variables directly
    PLATFORM_ADMIN_EMAIL=admin@example.com \
    PLATFORM_ADMIN_PASSWORD=changeme \
    PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
    mcpgateway --host 0.0.0.0 --port 4444
    ```

    ⭐ Enjoying this? Leave a star on GitHub!

    ---

    #### 🔍 What is Cline?

    [Cline](https://cline.bot/) is a powerful AI coding assistant for VS Code. It supports MCP, allowing it to discover and use tools provided through MCP Gateway.

    ---

    #### 🔐 Set up JWT Authentication

    In your Cline settings, add an MCP server:

    ```json
    {
      "name": "MCP Gateway",
      "url": "http://localhost:4444",
      "auth": {
        "type": "bearer",
        "token": "<YOUR_JWT_TOKEN>"
      }
    }
    ```

    Enable the server in Cline-you should see a green "connected" indicator when authentication succeeds.

    ---

    #### 🚀 Using MCP Tools in Cline

    With the connection live, Cline can:

    * Automatically list tools exposed by the Gateway
    * Use simple prompts to invoke tools, e.g.:

      ```
      Run the `list_files` tool with path: "./src"
      ```
    * Display results and JSON output directly within the VS Code interface

    Try it yourself-and don't forget to ⭐ the project at [ContextForge MCP Gateway](https://github.com/IBM/mcp-context-forge)!


## 🖼️ Logo & Images

| Asset | URL |
|-------|-----|
| Transparent PNG logo  | `https://ibm.github.io/mcp-context-forge/logo.png` |
| Hero demo GIF         | `https://ibm.github.io/mcp-context-forge/images/mcpgateway.gif` |
| Architecture overview | [SVG](https://ibm.github.io/mcp-context-forge/images/mcpgateway.svg) |

---

## 📣 Social Snippets

**Tweet / X**

!!! example "Twitter / X"
    🚀 ContextForge MCP Gateway is now open source! One endpoint to unify & secure AI-tool connections (STDIO, SSE, REST). Give it a spin and drop a ⭐ → https://github.com/IBM/mcp-context-forge #mcp #ai #tools

**LinkedIn**

!!! example
    Thrilled to share **ContextForge MCP Gateway**-an open-source hub that turns fragmented AI-tool integrations into a single secure interface with discovery, observability, and a live catalog UI. Check it out on GitHub and leave us a star ⭐!
    `#mcp #ai #tools`

!!! tip Examples Posts
    See [Social](../social/index.md) for example articles and social media posts - and add your own there once published!
