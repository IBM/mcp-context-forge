# LangChain Integration with ContextForge

LangChain is a framework for developing applications powered by language models. Integrating LangChain with the Model Context Protocol (MCP) allows agents to utilize tools defined across one or more MCP servers, enabling seamless interaction with external data sources and services.

---

## 🧰 Key Features

- **Dynamic Tool Access**: Connects to MCP servers to fetch available tools in real time.
- **Multi-Server Support**: Interact with tools defined on multiple MCP servers simultaneously.
- **Standardized Communication**: Utilizes the open MCP standard for consistent tool integration.

---

## 🛠 Installation

To use MCP tools in LangChain, install the `langchain-mcp-adapters` package:

```bash
pip install langchain-mcp-adapters
```

---

## 🔗 Connecting to ContextForge

Here's how to set up a connection to your ContextForge:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

client = MultiServerMCPClient(
    {
        "gateway": {
            "url": "http://localhost:4444/mcp",
            "transport": "streamable_http",
        }
    }
)
```

Replace `"http://localhost:4444/mcp"` with the URL of your ContextForge.

---

## 🤖 Creating an Agent

After setting up the client, you can create a LangChain agent:

```python
agent = create_react_agent(
    tools=client.get_tools(),
    llm=your_language_model,
)
```

Replace `your_language_model` with your configured language model instance.

---

## 🧪 Using the Agent

Once the agent is created, you can use it to perform tasks:

```python
response = agent.run("Use the 'weather' tool to get the forecast for Dublin.")
print(response)
```
## 📚 Additional Resources

* [LangChain MCP Adapters Documentation](https://langchain-ai.github.io/langgraph/agents/mcp/)
* [LangChain GitHub Repository](https://github.com/langchain-ai/langchain)
* [Model Context Protocol Overview](https://modelcontextprotocol.io/)

---
