# Using MCP Gateway

This section focuses on how to use MCP Gateway effectively as a developer, integrator, or end user.

---

## 👨💻 Typical Use Cases

- You want to expose tools, prompts, or resources via MCP.
- You want to use `mcpgateway-wrapper` to connect to any MCP Gateway service using `stdio`, while still supporting authentication to the gateway.
- You're building a client or agent framework that speaks the MCP protocol.
- You want to consume Gateway APIs from an LLM agent, browser app, or CLI tool.

---

## 📚 What You'll Find in This Section

| Page | Description |
|------|-------------|
| [Code Execution Virtual Servers](code-execution-virtual-server.md) | Configure and use secure `code_execution` servers with `shell_exec` and `fs_browse` |
| [Tool Annotations](tool-annotations.md) | Configure behavior hints for tools (safety, idempotency, etc.) |
| [mcpgateway-wrapper](mcpgateway-wrapper.md) | Wrap CLI tools or subprocesses to expose them via SSE/stdio |
| [Clients](clients/index.md) | Compatible UIs and developer tools |
| [Agents](agents/index.md) | LangChain, LangGraph, CrewAI, and other frameworks |

---

## 🔑 Authentication Reminder

All Gateway usage requires authentication unless `AUTH_REQUIRED=false`. Refer to:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools
```

The Admin UI uses email/password authentication (`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`). Basic auth is only used if you explicitly enable `API_ALLOW_BASIC_AUTH=true` or `DOCS_ALLOW_BASIC_AUTH=true`.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---
