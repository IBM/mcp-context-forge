# CrewAI Integration with MCP Gateway

CrewAI is a multi-agent orchestration framework that enables AI agents to collaborate on complex tasks. Integrating CrewAI with the Model Context Protocol (MCP) allows agents to dynamically discover and utilize tools hosted on MCP servers, enhancing their capabilities and flexibility.

---

## 🧰 Key Features

- **Dynamic Tool Discovery**: Agents can fetch available tools from MCP servers in real-time.
- **Standardized Communication**: Utilizes the open MCP standard for consistent tool integration.
- **Multi-Server Support**: Interact with tools defined on multiple MCP servers simultaneously.

---

## 🛠 Installation

To use MCP tools in CrewAI, install the `crewai-tools` package with MCP support:

```bash
pip install "crewai-tools[mcp]"
