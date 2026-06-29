# BeeAI Framework Integration with ContextForge

[BeeAI Framework](https://framework.beeai.dev/) is a dual-language framework for
building agentic applications in Python and TypeScript. It can use tools exposed
by any MCP server through BeeAI's `MCPTool`, which discovers remote tools from an
MCP client and makes them available to BeeAI agents.

ContextForge can be used in two common ways:

- Start `mcpgateway-wrapper` as a local stdio MCP server for clients that spawn
  subprocesses.
- Connect BeeAI directly to ContextForge over Streamable HTTP, or to a legacy SSE
  endpoint when required.

---

## 🛠 Installation

Install the Python packages when building BeeAI agents in Python:

```bash
pip install "beeai-framework[mcp]" mcp-contextforge-gateway
```

Install the TypeScript packages when building BeeAI agents in Node.js:

```bash
npm install beeai-framework @modelcontextprotocol/sdk zod
```

Prepare the ContextForge connection values used in the examples:

```bash
export MCPGATEWAY_BEARER_TOKEN="<gateway-token>"
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}" # pragma: allowlist secret

# Virtual server endpoint used by mcpgateway-wrapper.
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# Direct MCP endpoints used by HTTP/SSE clients.
export MCP_GATEWAY_MCP_URL="http://localhost:4444/mcp"
export MCP_GATEWAY_SSE_URL="http://localhost:4444/sse"
```

See [mcpgateway-wrapper](../mcpgateway-wrapper.md) for details on generating
tokens and choosing the correct virtual server URL.

---

## 🔗 Python: stdio via `mcpgateway-wrapper`

Use the wrapper when you want BeeAI to spawn ContextForge as a local stdio MCP
server while the wrapper forwards calls to the gateway.

```python
import asyncio
import os

from mcp import StdioServerParameters, stdio_client

from beeai_framework.agents.requirement import RequirementAgent
from beeai_framework.backend import ChatModel
from beeai_framework.tools.mcp import MCPTool

server_params = StdioServerParameters(
    command="python3",
    args=["-m", "mcpgateway.wrapper"],
    env={
        "MCP_SERVER_URL": os.environ["MCP_SERVER_URL"],
        "MCP_AUTH": os.environ["MCP_AUTH"],
        "MCP_WRAPPER_LOG_LEVEL": "OFF",
    },
)


async def main() -> None:
    client = stdio_client(server_params)
    tools = await MCPTool.from_client(client)

    agent = RequirementAgent(
        llm=ChatModel.from_name(os.getenv("BEEAI_CHAT_MODEL", "ollama:granite4:micro")),
        tools=tools,
    )

    response = await agent.run("List the tools available through ContextForge.")
    print(response.last_message.text)


if __name__ == "__main__":
    asyncio.run(main())
```

`MCPTool.from_client(...)` calls the MCP client's tool listing endpoint and
creates one BeeAI tool per gateway tool. Filter the returned list before creating
the agent if a workflow should only expose a small tool subset:

```python
tools = [tool for tool in await MCPTool.from_client(client) if tool.name.startswith("github-")]
```

---

## 🌐 Python: Streamable HTTP and SSE

For direct network connections, use the MCP Python SDK transports that BeeAI
supports. Streamable HTTP is the preferred transport for current MCP servers;
SSE remains useful for older deployments.

### Streamable HTTP

```python
import asyncio
import os

import httpx
from mcp.client.streamable_http import streamable_http_client

from beeai_framework.agents.requirement import RequirementAgent
from beeai_framework.backend import ChatModel
from beeai_framework.tools.mcp import MCPTool


async def main() -> None:
    headers = {"Authorization": os.environ["MCP_AUTH"]}
    async with httpx.AsyncClient(headers=headers) as http_client:
        client = streamable_http_client(
            os.getenv("MCP_GATEWAY_MCP_URL", "http://localhost:4444/mcp"),
            http_client=http_client,
        )
        tools = await MCPTool.from_client(client)

        agent = RequirementAgent(
            llm=ChatModel.from_name(os.getenv("BEEAI_CHAT_MODEL", "ollama:granite4:micro")),
            tools=tools,
        )
        response = await agent.run("Use an appropriate ContextForge tool for this request.")
        print(response.last_message.text)


if __name__ == "__main__":
    asyncio.run(main())
```

### SSE

```python
import asyncio
import os

from mcp.client.sse import sse_client

from beeai_framework.agents.requirement import RequirementAgent
from beeai_framework.backend import ChatModel
from beeai_framework.tools.mcp import MCPTool


async def main() -> None:
    client = sse_client(
        os.getenv("MCP_GATEWAY_SSE_URL", "http://localhost:4444/sse"),
        headers={"Authorization": os.environ["MCP_AUTH"]},
    )
    tools = await MCPTool.from_client(client)

    agent = RequirementAgent(
        llm=ChatModel.from_name(os.getenv("BEEAI_CHAT_MODEL", "ollama:granite4:micro")),
        tools=tools,
    )
    response = await agent.run("Summarize which ContextForge tools are available.")
    print(response.last_message.text)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🔗 TypeScript: stdio via `mcpgateway-wrapper`

BeeAI's TypeScript MCP integration uses the MCP TypeScript SDK `Client` and
`MCPTool.fromClient(...)`. Start with the same stdio wrapper when you want a local
subprocess bridge into ContextForge.

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ReActAgent } from "beeai-framework/agents/react/agent";
import { OllamaChatModel } from "beeai-framework/adapters/ollama/backend/chat";
import { UnconstrainedMemory } from "beeai-framework/memory/unconstrainedMemory";
import { MCPTool } from "beeai-framework/tools/mcp";

const client = new Client(
  { name: "contextforge-beeai-client", version: "1.0.0" },
  { capabilities: {} }
);

await client.connect(
  new StdioClientTransport({
    command: "python3",
    args: ["-m", "mcpgateway.wrapper"],
    env: {
      MCP_SERVER_URL: process.env.MCP_SERVER_URL!,
      MCP_AUTH: process.env.MCP_AUTH!, # pragma: allowlist secret
      MCP_WRAPPER_LOG_LEVEL: "OFF",
    },
  })
);

try {
  const tools = await MCPTool.fromClient(client);
  const agent = new ReActAgent({
    llm: new OllamaChatModel(process.env.BEEAI_CHAT_MODEL ?? "granite4:micro"),
    memory: new UnconstrainedMemory(),
    tools,
  });

  await agent.run({ prompt: "List the tools available through ContextForge." });
} finally {
  await client.close();
}
```

---

## 🌐 TypeScript: Streamable HTTP and SSE

The BeeAI part stays the same for HTTP transports: create an MCP SDK `Client`,
connect it with the desired transport, then call `MCPTool.fromClient(client)`.

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { ReActAgent } from "beeai-framework/agents/react/agent";
import { OllamaChatModel } from "beeai-framework/adapters/ollama/backend/chat";
import { UnconstrainedMemory } from "beeai-framework/memory/unconstrainedMemory";
import { MCPTool } from "beeai-framework/tools/mcp";

const headers = { Authorization: process.env.MCP_AUTH! };

async function runWithTransport(transport: Parameters<Client["connect"]>[0]) {
  const client = new Client(
    { name: "contextforge-beeai-client", version: "1.0.0" },
    { capabilities: {} }
  );

  await client.connect(transport);
  try {
    const tools = await MCPTool.fromClient(client);
    const agent = new ReActAgent({
      llm: new OllamaChatModel(
        process.env.BEEAI_CHAT_MODEL ?? "granite4:micro"
      ),
      memory: new UnconstrainedMemory(),
      tools,
    });
    await agent.run({
      prompt: "Use an appropriate ContextForge tool for this request.",
    });
  } finally {
    await client.close();
  }
}

await runWithTransport(
  new StreamableHTTPClientTransport(
    new URL(process.env.MCP_GATEWAY_MCP_URL ?? "http://localhost:4444/mcp"),
    {
      requestInit: { headers },
    }
  )
);

// Legacy SSE endpoint variant.
await runWithTransport(
  new SSEClientTransport(
    new URL(process.env.MCP_GATEWAY_SSE_URL ?? "http://localhost:4444/sse"),
    {
      requestInit: { headers },
      eventSourceInit: {
        fetch: (url, init) =>
          fetch(url, {
            ...init,
            headers: { ...headers, ...(init?.headers ?? {}) },
          }),
      },
    }
  )
);
```

---

## ✅ Integration Tips

- Prefer Streamable HTTP for direct network connections and use SSE only when the
  target deployment still exposes a legacy SSE endpoint.
- Use `mcpgateway-wrapper` when BeeAI runs in an environment that expects a
  local stdio MCP server, or when you want the wrapper to manage gateway auth and
  virtual server selection.
- Keep each agent's tool list small. ContextForge virtual servers are useful for
  grouping only the tools a BeeAI workflow should discover.
- Apply ContextForge policies, caching, observability, and rate limits at the
  gateway. BeeAI still receives standard MCP tool schemas through `MCPTool`.
- Do not pass raw gateway tokens to model prompts or tool arguments. Keep them in
  process environment variables or a secret manager.

---

## 📚 Additional Resources

- [BeeAI Framework Documentation](https://framework.beeai.dev/)
- [BeeAI MCP tool documentation](https://framework.beeai.dev/modules/tools#mcp)
- [BeeAI Framework GitHub repository](https://github.com/i-am-bee/beeai-framework)
- [BeeAI Python MCP examples](https://github.com/i-am-bee/beeai-framework/tree/main/python/examples/tools/mcp)
- [BeeAI TypeScript MCP example](https://github.com/i-am-bee/beeai-framework/blob/main/typescript/examples/tools/mcp.ts)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [Model Context Protocol documentation](https://modelcontextprotocol.io/)
- [ContextForge mcpgateway-wrapper](../mcpgateway-wrapper.md)

---
