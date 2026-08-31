# Admin Console Concepts

> This guide introduces each major section of the Gateway Admin UI and how it connects to the Model Context Protocol (MCP).

---

## 🆕 Setting up a new MCP Server to federate to the gateway

???+ example "🔌 How do I expose an MCP server over SSE?"
    To federate a new MCP Server to your gateway, it must run over **Server-Sent Events (SSE)** so the gateway can communicate with it.

    Use the built-in translate bridge to wrap any `stdio`-only MCP server and expose it over SSE:

    ```bash
    python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 8001
    python3 -m mcpgateway.translate --stdio "uvx mcp_server_time -- --local-timezone=Europe/Dublin" --expose-sse --port 8002
    ```

    ✅ **Important:** The gateway must be able to reach the MCP server's network address.

    If you're running services inside Docker (or other containerized environments), ensure networking is configured properly:

    - Use `host` networking when needed.
    - Expose ports to the host machine.
    - Make sure internal container IPs are reachable from the gateway.


## 📦 Virtual Servers

> A virtual server is a logical wrapper that combines selected tools, resources, and prompts under one context-specific endpoint.

???+ info "🔗 What are Virtual Servers?"

    - A Virtual Server defines a project-specific toolset.
    - Each one is backed by a real SSE or STDIO interface.
    - You can activate/deactivate, view metrics, and invoke tools from this server.



---

## 🛠 Global Tools

> Tools are remote functions that an LLM can invoke, either via MCP or REST. Think of them like typed APIs with schemas and optional auth.

???+ example "⚙️ What do Tools represent?"

    - Integration Types: `MCP`, `REST`
    - Request Types: `STDIO`, `SSE`, `GET`, `POST`, etc.
    - Input Schema: JSON Schema defines valid input.
    - Supports Basic Auth, Bearer, or Custom headers.



---

## 📁 Global Resources

> Resources expose read-only data like files, database rows, logs, or screenshots. LLMs can read this content through a URI.

???+ example "📖 How do Resources work?"

    - Text and Binary data supported.
    - Exposed via unique URI (`file:///`, `db://`, etc.).
    - Resources can be listed, templated, or subscribed to.



---

## 🧾 Global Prompts

> Prompts are reusable message templates with arguments. They define system prompts, user instructions, or chainable inputs.

???+ info "🗒 What's in a Prompt?"

    - Each prompt has a name, template, and arguments.
    - Arguments are defined with name, description, and required status.
    - Used to enforce consistency across tool use or system messaging.



---

## 🌐 Gateways (MCP Servers)

> Gateways are other MCP-compatible servers. When registered, their tools/resources/prompts become usable locally.

???+ example "🌉 What is a federated Gateway?"

    - Syncs public tools from a remote MCP server.
    - Peer tools show up in your catalog with `gateway_id`.
    - Can be toggled active/inactive.

### Testing Gateway Connectivity

After registering a new gateway, you can use the **"Test Gateway Connectivity"** dialog to verify basic network reachability.

???+ warning "⚠️ What Test Gateway Connectivity Does (and Doesn't Do)"

    **What it does:**

    - Sends a plain HTTP request to the upstream server to check reachability
    - Verifies that the gateway can reach the registered URL
    - Useful for confirming network connectivity and basic endpoint availability
    - Default test: `GET /health` (configurable path and method)

    **What it does NOT do:**

    - Does **not** establish an MCP protocol session
    - Does **not** perform MCP handshake or capability negotiation
    - Does **not** return tool listings or MCP-specific data
    - Does **not** work for testing SSE session establishment

    **This is a basic connectivity check, not an MCP protocol test.**

???+ tip "🧪 How to Test SSE Servers End-to-End"

    For SSE-based MCP servers, you need to establish a session and use the session ID for subsequent requests:

    **Step 1: Open SSE stream and capture session ID**
    ```bash
    # The session ID is returned in the first SSE event
    curl -s -N -H "Authorization: Bearer $TOKEN" \
      $GW_URL/servers/$SERVER_UUID/sse
    ```

    **Step 2: Use session ID to send MCP requests**
    ```bash
    # In a separate terminal, send tools/list request
    curl -X POST -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' \
      "$GW_URL/messages/?session_id=<SESSION_ID>"
    ```

    **Alternative: Test individual tools directly**

    The "Test" button on individual tools in the UI invokes tools via the `/rpc` endpoint, which does not require an active SSE session.

???+ info "🔍 Difference Between Test Methods"

    | Test Method | Purpose | Requires Session | Tests MCP Protocol |
    |-------------|---------|------------------|-------------------|
    | **Test Gateway Connectivity** | Network reachability check | No | No |
    | **SSE Stream + /messages/** | Full MCP session testing | Yes | Yes |
    | **Tool "Test" Button** | Direct tool invocation | No | Partial |

    Choose the appropriate test method based on what you need to verify.



---

## 📂 Roots

> Roots define base folders for file-based resources. They control what files MCP clients can access from your local system.

???+ tip "📁 What are Roots used for?"

    - Restrict access to specific folders (`file:///workspace`)
    - Prevent tools from referencing outside their sandbox.
    - Deleting a root invalidates its associated resources.



---

## 📈 Metrics

> Track tool calls, resource reads, prompt renders, and overall usage in one place.

???+ info "📊 What does the Metrics tab show?"

    - Overall executions by server/tool/prompt.
    - Latency, failure rate, and hot paths.
    - Top tools, resources, prompts, and servers.



---

## 🧪 Version & Diagnostics

> The `/version` endpoint returns structured JSON diagnostics including system info, DB/Redis health, and Git SHA.

???+ example "🩺 What does the Version panel include?"

    - MCP protocol version and server metadata.
    - Live system metrics (CPU, memory).
    - Environment checks and service readiness.



---

## 📚 Learn More

- 🔗 [MCP Specification](https://modelcontextprotocol.org/spec)
