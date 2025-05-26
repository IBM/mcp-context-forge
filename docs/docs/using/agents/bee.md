# Bee Agent Framework Integration with MCP Gateway

The Bee Agent Framework is an open-source platform developed by IBM for building, deploying, and managing AI agents at scale. Integrating Bee with the Model Context Protocol (MCP) allows agents to dynamically discover and utilize tools hosted on MCP servers, enhancing their capabilities and flexibility.

---

## 🧰 Key Features

- **Dynamic Tool Discovery**: Agents can fetch available tools from MCP servers in real-time.
- **Standardized Communication**: Utilizes the open MCP standard for consistent tool integration.
- **Multi-Server Support**: Interact with tools defined on multiple MCP servers simultaneously.
- **Human-in-the-Loop**: Incorporate human feedback into agent workflows for improved decision-making.

---

## 🛠 Installation

To use MCP tools in the Bee Agent Framework, follow these steps:

1. **Clone the Bee Agent Framework Repository**:

   ```bash
   git clone https://github.com/i-am-bee/bee-agent-framework.git
   cd bee-agent-framework
```

2. **Install Dependencies**:

   ```bash
   yarn install
   ```

3. **Set Up the Environment**:

   Ensure you have Node.js and Yarn installed. You may also need to set environment variables for your MCP server:

   ```bash
   export MCP_GATEWAY_BASE_URL=http://localhost:4444
   export MCP_AUTH_USER=admin
   export MCP_AUTH_PASS=changeme
   ```

---

## 🔗 Connecting to MCP Gateway

Bee provides a native `MCPTool` class to simplify integration with MCP servers. Here's how to set it up:

1. **Import the MCPTool Class**:

   ```javascript
   import { MCPTool } from 'bee-agent-framework/tools/mcp';
   ```

2. **Configure the MCPTool**:

   ```javascript
   const mcpTool = new MCPTool({
     baseUrl: process.env.MCP_GATEWAY_BASE_URL,
     auth: {
       username: process.env.MCP_AUTH_USER,
       password: process.env.MCP_AUTH_PASS,
     },
   });
   ```

3. **Register the Tool with Your Agent**:

   ```javascript
   agent.registerTool(mcpTool);
   ```

This setup allows your Bee agent to discover and invoke tools from the specified MCP server dynamically.

---

## 🤖 Creating an Agent

After setting up the MCPTool, you can create a Bee agent:

```javascript
import { Agent } from 'bee-agent-framework';

const agent = new Agent({
  name: 'Data Analyst',
  tools: [mcpTool],
});
```

---

## 🧪 Using the Agent

Once the agent is created, you can assign tasks and execute them:

```javascript
agent.runTask('Generate a sales report for Q1 2025');
```

The agent will utilize tools from the MCP server to accomplish the task.

---

## 📚 Additional Resources

* [Bee Agent Framework Documentation](https://i-am-bee.github.io/beeai-framework/#/)
* [Bee Agent Framework GitHub Repository](https://github.com/i-am-bee/bee-agent-framework)
* [Model Context Protocol Overview](https://modelcontextprotocol.io/)

---
