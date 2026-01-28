# Cline (VS Code Extension)

[Cline](https://cline.bot/) is a Visual Studio Code extension that brings AI-powered coding assistance directly into your editor. It supports the Model Context Protocol (MCP), enabling seamless integration with MCP-compatible servers like MCP Gateway.

---

## 🧰 Key Features

- **AI-Powered Coding**: Leverages advanced AI models (e.g., Claude 3.5 Sonnet, DeepSeek Chat) for code generation, editing, and debugging.
- **MCP Integration**: Connects to MCP servers to discover and utilize tools dynamically.
- **Terminal and Browser Access**: Executes terminal commands and performs browser operations with user permission.
- **Custom Tools**: Supports adding custom tools via MCP for extended functionality.

---

## 🛠 Installation

1. **Install Cline Extension**:
   - Open VS Code.
   - Navigate to the Extensions view (`Ctrl+Shift+X` or `Cmd+Shift+X`).
   - Search for "Cline" and click "Install".

2. **Sign In to Cline**:
   - Click the Cline icon in the Activity Bar.
   - Follow the prompts to sign in or create a new account at [app.cline.bot](https://app.cline.bot/).
   - New users receive free credits; no credit card required.

---

## 🔗 Connecting to MCP Gateway

To integrate Cline with your MCP Gateway:

1. **Configure MCP Server**:
   - Open the Cline settings in VS Code.
   - Navigate to the MCP Servers section.
   - Add a new MCP server with the following configuration under mcpServers as shown below:

     ```json
     "mcpServers": {
         "mcpgateway-wrapper": {
            "disabled": true,
            "timeout": 60,
            "type": "stdio",
            "command": "uv",
            "args": [
            "run",
            "--directory",
            "REPLACE_WITH_PATH_TO_REPO",
            "-m",
            "mcpgateway.wrapper"
            ],
            "env": {
               "MCP_SERVER_URL": "http://localhost:4444",
               "MCP_AUTH": "Bearer REPLACE_WITH_MCPGATEWAY_BEARER_TOKEN",
               "MCP_WRAPPER_LOG_LEVEL": "OFF"
            }
         }
      }
     ```

2. **Enable the MCP Server**:
   - Ensure the newly added MCP server is enabled in the Cline settings.

3. **Verify Connection**:
   - In the Cline interface, navigate to the MCP Servers section.
   - Confirm that the MCP Gateway server is listed and shows a green status indicator.

---

## 🧪 Using MCP Tools in Cline

Once connected:

- **Discover Tools**: Cline will automatically fetch and list available tools from the MCP Gateway.
- **Invoke Tools**: Use natural language prompts in Cline to invoke tools. For example:
  - "Run the `hello_world` tool with the argument `name: Alice`."
- **Monitor Responses**: Cline will display the tool's output directly within the chat interface.

---

## 📝 Tips for Effective Use

- **.clinerules File**: Create a `.clinerules` file in your project root to define project-specific behaviors and instructions for Cline.
- **Custom Instructions**: Utilize Cline's Custom Instructions feature to tailor its behavior across all projects.
- **Model Selection**: Choose the AI model that best fits your project's needs within the Cline settings.

---

## 📚 Additional Resources

- [Cline Official Website](https://cline.bot/)
- [Cline Documentation](https://docs.cline.bot/)

---
