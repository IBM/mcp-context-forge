# Agent Integrations

This section provides guidance on integrating various AI agent frameworks with the Model Context Protocol (MCP) Gateway. MCP enables agents to dynamically discover and utilize tools across multiple servers, enhancing their capabilities and flexibility.

---

## 🧠 Supported Agent Frameworks

### Using ContextForge (Agent frameworks as MCP clients)
- [LangChain](langchain.md): Utilize MCP tools within LangChain agents using the `langchain-mcp-adapters` package.
- [LangGraph](langgraph.md): Integrate MCP tools into LangGraph agents for advanced workflow orchestration.
- [CrewAI](crewai.md): Connect CrewAI agents to MCP servers using the `crewai-tools` library.
- [Bee Agent Framework](bee.md): Leverage MCP tools within the Bee Agent Framework for scalable agent deployments.
- [AutoGen](autogen.md): Integrate MCP tools with AutoGen agents using the `autogen-ext-mcp` package.
- [LlamaIndex](llamaindex.md): Incorporate MCP tools into LlamaIndex workflows for enhanced data retrieval and question answering.
- [OpenAI Agents SDK](openai-sdk.md): Utilize MCP tools within OpenAI's Agents SDK for building AI agents with standardized tool access.
- [Semantic Kernel](semantic-kernel.md): Connect Semantic Kernel agents to MCP servers for enriched context and tool integration.

### A2A (Agent-to-Agent) Integration (External agents in ContextForge)
- **[A2A Integration](a2a.md)**: Complete guide to registering external AI agents in the ContextForge
- **External AI Agents**: Register external AI agents (OpenAI, Anthropic, custom) as A2A agents in the gateway
- **Tool Exposure**: A2A agents are automatically exposed as MCP tools for other agents to discover and use
- **Protocol Support**: Supports JSONRPC, custom protocols, and multiple authentication methods
- **Admin Management**: Full admin UI for registering, testing, and managing external agents
- **Virtual Server Integration**: Associate A2A agents with virtual servers for organized tool catalogs

---

## 🔍 Overview

Each integration guide includes:

- **Installation Instructions**: Step-by-step setup for the respective agent framework.
- **Configuration Details**: How to connect the agent to the ContextForge, including authentication and transport options.
- **Usage Examples**: Sample code demonstrating how to invoke MCP tools within the agent's workflow.
- **Additional Resources**: Links to official documentation and repositories for further reference.

---

## 📚 Additional Resources

- [Model Context Protocol Overview](https://modelcontextprotocol.io/)
- [ContextForge Documentation](../index.md)

---
