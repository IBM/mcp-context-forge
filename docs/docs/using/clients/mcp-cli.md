# 🖥️ MCP CLI + MCP Context Forge Gateway

A powerful, feature-rich command-line interface for interacting with Model Context Protocol servers through **IBM's MCP Context Forge Gateway**. The mcp-cli provides multiple operational modes including chat, interactive shell, and scriptable automation, with support for multiple LLM providers.

With mcp-cli → MCP Context Forge Gateway you can:

* 🔧 **Auto-discover tools** from your MCP Context Forge Gateway and use them seamlessly
* 🔄 **Switch between providers** (OpenAI, Anthropic, Ollama) during sessions
* 📊 **Export conversation history** to JSON for analysis and debugging
* 🤖 **Chat with LLMs** that automatically invoke Gateway tools and resources
* 📜 **Automate workflows** with scriptable command-line operations
* 🛠️ **Compare modes** - chat vs. interactive vs. command-line automation

The mcp-cli supports **stdio** connections out-of-the-box through the bundled **`mcpgateway.wrapper`** bridge, with optional direct SSE access for production environments.

---

## 🛠 Prerequisites

* **Python ≥ 3.11**
* **uv** (recommended) or pip for dependency management
* **MCP Context Forge Gateway** running locally or remotely (default: http://localhost:4444)
* **JWT or Basic Auth credentials** for Gateway access
* **LLM Provider API keys** (optional, for chat mode):
  * OpenAI: `OPENAI_API_KEY` environment variable
  * Anthropic: `ANTHROPIC_API_KEY` environment variable
  * Ollama: Local Ollama installation with function-calling capable models

---

## 🚀 Installation

### Install MCP CLI

```bash
git clone https://github.com/chrishayuk/mcp-cli
cd mcp-cli
pip install -e ".[cli,dev]"
```

### Using UV (Recommended)

```bash
# Install UV if not already installed
pip install uv

# Clone and install
git clone https://github.com/chrishayuk/mcp-cli
cd mcp-cli
uv sync --reinstall

# Run using UV
uv run mcp-cli --help
```

### Install MCP Context Forge Gateway

```bash
# Clone the MCP Context Forge repository
git clone https://github.com/IBM/mcp-context-forge
cd mcp-context-forge

# Install and start the gateway
make venv install serve
# Gateway will be available at http://localhost:4444
```

---

## ⚙️ Configuring Your Server

Create a `server_config.json` file to define your MCP Context Forge Gateway connection:

### Basic Configuration (Local Development)

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "/path/to/mcp-context-forge/.venv/bin/python",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH": "Bearer <YOUR_AUTH_TOKEN_HERE>",
        "MCP_SERVER_URL": "http://localhost:4444",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

### Docker-based Configuration (Production)

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "MCP_SERVER_URL=http://host.docker.internal:4444",
        "-e",
        "MCP_AUTH=${MCPGATEWAY_BEARER_TOKEN}",
        "--entrypoint",
        "uv",
        "ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2",
        "run",
        "--directory",
        "mcpgateway-wrapper",
        "mcpgateway-wrapper"
      ],
      "env": {
        "MCPGATEWAY_BEARER_TOKEN": "your-jwt-token-here"
      }
    }
  }
}
```

> **💡 Generate a JWT token for your Gateway**

```bash
# From your mcp-context-forge directory
python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --exp 10080 --secret my-test-key
```

> **⚠️ Important Notes**
> - Use the **full path** to your virtual environment's Python to avoid import errors
> - Make sure your MCP Context Forge Gateway is running on the correct port (default: 4444)
> - The wrapper requires `MCP_SERVER_URL` environment variable

---

## 🌐 Available Modes

### 1. Chat Mode (Default)

Natural language interface where LLMs automatically use available tools:

```bash
# Default chat mode with OpenAI
export OPENAI_API_KEY="your-api-key"
mcp-cli chat --server mcpgateway-wrapper

# Using Ollama (recommended to avoid OpenAI tool name length limits)
mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest

# Using Anthropic
export ANTHROPIC_API_KEY="your-api-key"
mcp-cli chat --server mcpgateway-wrapper --provider anthropic --model claude-sonnet-4-20250514
```

### 2. Interactive Mode

Command-driven shell interface for direct server operations:

```bash
mcp-cli interactive --server mcpgateway-wrapper
```

### 3. Command Mode

Unix-friendly interface for automation and pipeline integration:

```bash
# Process content with LLM
mcp-cli cmd --server mcpgateway-wrapper --input document.md --prompt "Summarize: {{input}}"

# Direct tool invocation
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-list-notifications --raw

# Search for GitHub issues
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-search-issues --tool-args '{"q":"assignee:@me"}' --raw
```

### 4. Direct Commands

Run individual commands without entering interactive mode:

```bash
# List available tools
mcp-cli tools list --server mcpgateway-wrapper

# Ping the gateway
mcp-cli ping --server mcpgateway-wrapper

# List available prompts
mcp-cli prompts list --server mcpgateway-wrapper

# List available resources
mcp-cli resources list --server mcpgateway-wrapper
```

---

## 🧪 Verify Tool Discovery

Once connected to your MCP Context Forge Gateway, mcp-cli automatically discovers all available tools:

1. **Test connection:** `mcp-cli ping --server mcpgateway-wrapper`
2. **List tools:** `mcp-cli tools list --server mcpgateway-wrapper`
3. **Start Chat Mode:** `mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest`
4. **Type `/tools`** - your Gateway tools should list automatically
5. **Try asking:** `"What tools are available?"` and the LLM will show discovered tools
6. **Test GitHub integration:** `"What issues have been assigned to me?"`

The CLI auto-discovers tools from your Gateway and makes them available across all modes.

---

## 🔧 LLM Provider Setup

### OpenAI (Has 64-character tool name limitation)

```bash
export OPENAI_API_KEY="sk-your-api-key-here"
mcp-cli chat --server mcpgateway-wrapper --provider openai --model gpt-4o-mini
```

**⚠️ Known Issue:** OpenAI has a 64-character limit for tool names, but some MCP Context Forge tools exceed this limit (e.g., `github-server-add-pull-request-review-comment-to-pending-review` is 69 characters).

### Ollama (Recommended - No tool name limitations)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a function-calling capable model
ollama pull mistral-nemo:latest
# or
ollama pull llama3.2:latest

# Use with mcp-cli
mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest
```

### Anthropic Claude

```bash
export ANTHROPIC_API_KEY="sk-ant-your-api-key-here"
mcp-cli chat --server mcpgateway-wrapper --provider anthropic --model claude-3-sonnet
```

---

## 🧪 Basic Usage

### Chat Mode Commands

In chat mode, use these slash commands for enhanced functionality:

#### General Commands
* `/help` - Show available commands
* `/quickhelp` or `/qh` - Quick reference guide
* `exit` or `quit` - Exit chat mode

#### Provider & Model Management
* `/provider` - Show current provider and model
* `/provider list` - List all configured providers
* `/provider <name>` - Switch to different provider
* `/model <name>` - Switch to different model

#### Tool Management
* `/tools` - Display all available tools from your Gateway
* `/tools --all` - Show detailed tool information
* `/toolhistory` or `/th` - Show tool call history

#### Conversation Management
* `/conversation` or `/ch` - Show conversation history
* `/save <filename>` - Save conversation to JSON file
* `/compact` - Condense conversation history

### Example Chat Interactions

```
> what issues have been assigned to me?
[Tool Call: github-server-get-me]
[Tool Call: github-server-search-issues with q="assignee:username"]

> what files are in my Downloads folder?
[Tool Call: filesystem-downloads-list-directory]

> create a memory about this conversation
[Tool Call: memory-server-store-memory]

> what time is it in London?
[Tool Call: time-server-get-system-time with timezone="Europe/London"]
```

### Interactive Mode Commands

In interactive mode, use these commands:

* `/help` - Show available commands
* `/tools` or `/t` - List/call tools interactively
* `/resources` or `/res` - List available resources
* `/prompts` or `/p` - List available prompts
* `/servers` or `/srv` - List connected servers
* `/ping` - Ping connected servers

### Command Mode Options

* `--input` - Input file path (use `-` for stdin)
* `--output` - Output file path (use `-` for stdout)
* `--prompt` - Prompt template with `{{input}}` placeholder
* `--tool` - Directly call a specific tool
* `--tool-args` - JSON arguments for tool call
* `--provider` - Specify LLM provider
* `--model` - Specify model to use
* `--raw` - Output raw response without formatting

---

## 🔧 Advanced Configuration

### Environment Variables

```bash
# MCP Context Forge Gateway connection
export MCP_AUTH="Bearer your-jwt-token"
export MCP_SERVER_URL="http://localhost:4444"

# LLM Provider API keys
export OPENAI_API_KEY="sk-your-openai-key"
export ANTHROPIC_API_KEY="sk-ant-your-anthropic-key"

# Default provider settings
export LLM_PROVIDER="ollama"
export LLM_MODEL="mistral-nemo:latest"
```

### Troubleshooting Common Issues

#### "ModuleNotFoundError: No module named 'mcpgateway'"

**Solution:** Use the full path to your virtual environment's Python:

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "/Users/username/path/to/mcp-context-forge/.venv/bin/python",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": { ... }
    }
  }
}
```

#### "MCP_SERVER_URL environment variable is required"

**Solution:** Ensure your `server_config.json` includes the required environment variables in the `env` section.

#### OpenAI Tool Name Length Error

**Error:** `string too long. Expected a string with maximum length 64`

**Solution:** Use Ollama or Anthropic instead:

```bash
mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest
```

#### Model doesn't support tools

**Error:** `does not support tools (status code: 400)`

**Solution:** Use a function-calling capable model:

```bash
# Pull compatible models
ollama pull mistral-nemo:latest
ollama pull llama3.2:latest

# Use in mcp-cli
mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest
```

---

## 📈 Advanced Usage Examples

### GitHub Integration

```bash
# Get your GitHub profile
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-get-me --raw

# List notifications
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-list-notifications --raw

# Search for issues assigned to you
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-search-issues \
  --tool-args '{"q":"assignee:@me is:open"}' --raw

# Create a new issue
mcp-cli cmd --server mcpgateway-wrapper --tool github-server-create-issue \
  --tool-args '{"owner":"username","repo":"repository","title":"New Issue","body":"Issue description"}' --raw
```

### File System Operations

```bash
# List allowed directories
mcp-cli cmd --server mcpgateway-wrapper --tool filesystem-downloads-list-allowed-directories --raw

# Read a file
mcp-cli cmd --server mcpgateway-wrapper --tool filesystem-downloads-read-file \
  --tool-args '{"path":"/path/to/file.txt"}' --raw

# Search for files
mcp-cli cmd --server mcpgateway-wrapper --tool filesystem-downloads-search-files \
  --tool-args '{"path":"/Users/username/Downloads","pattern":"*.pdf"}' --raw
```

### Memory Management

```bash
# Store a memory
mcp-cli cmd --server mcpgateway-wrapper --tool memory-server-store-memory \
  --tool-args '{"content":"Important project note","bucket":"work"}' --raw

# Get memories
mcp-cli cmd --server mcpgateway-wrapper --tool memory-server-get-memories \
  --tool-args '{"bucket":"work"}' --raw
```

### Time Operations

```bash
# Get current time
mcp-cli cmd --server mcpgateway-wrapper --tool time-server-get-system-time --raw

# Convert time zones
mcp-cli cmd --server mcpgateway-wrapper --tool time-server-convert-time \
  --tool-args '{"from_timezone":"UTC","to_timezone":"America/New_York","time":"2025-01-01T12:00:00Z"}' --raw
```

---

## 🔗 Integration with MCP Context Forge Gateway

The mcp-cli integrates with MCP Context Forge Gateway through multiple connection methods:

### Local Development Setup

1. **Start the Gateway:**
   ```bash
   cd mcp-context-forge
   make serve  # Starts on http://localhost:4444
   ```

2. **Configure mcp-cli:**
   ```json
   {
     "mcpServers": {
       "mcpgateway-wrapper": {
         "command": "/path/to/mcp-context-forge/.venv/bin/python",
         "args": ["-m", "mcpgateway.wrapper"],
         "env": {
           "MCP_AUTH": "Bearer <your-jwt-token>",
           "MCP_SERVER_URL": "http://localhost:4444"
         }
       }
     }
   }
   ```

3. **Test the connection:**
   ```bash
   mcp-cli ping --server mcpgateway-wrapper
   ```

### Production Docker Setup

Use the official Docker image for production environments:

```bash
# Start the gateway
docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=my-secret-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=changeme \
  -e PLATFORM_ADMIN_FULL_NAME="Platform Administrator" \
  ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2

# Generate token
export MCPGATEWAY_BEARER_TOKEN=$(docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-secret-key)

# Test connection
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```

---

## 📝 Available Tool Categories

Your MCP Context Forge Gateway provides these tool categories:

### 🗂️ Filesystem Tools
- **Downloads & Documents:** Read, write, edit, search files
- **Directory Operations:** List, create, move files and directories
- **File Management:** Get file info, create directory trees

### 🐙 GitHub Integration
- **Issue Management:** Create, update, list, search issues
- **Pull Requests:** Create, review, merge, comment on PRs
- **Repository Operations:** Fork, create, manage repositories
- **Notifications:** List, manage, dismiss notifications
- **Code Analysis:** Search code, get commits, manage branches

### 🧠 Memory Server
- **Memory Storage:** Store and retrieve contextual memories
- **Bucket Management:** Organize memories in buckets
- **Memory Querying:** Search and filter stored memories

### ⏰ Time Operations
- **System Time:** Get current time in any timezone
- **Time Conversion:** Convert between different timezones

### 📊 Features Comparison

| Feature | Chat Mode | Interactive Mode | Command Mode |
|---------|-----------|------------------|--------------|
| Natural language interface | ✅ | ❌ | ❌ |
| Automatic tool usage | ✅ | ❌ | ❌ |
| Direct tool invocation | ❌ | ✅ | ✅ |
| Scriptable automation | ❌ | ❌ | ✅ |
| Conversation history | ✅ | ❌ | ❌ |
| Provider switching | ✅ | ✅ | ✅ |
| Batch processing | ❌ | ❌ | ✅ |
| Pipeline integration | ❌ | ❌ | ✅ |
| GitHub integration | ✅ | ✅ | ✅ |
| File system access | ✅ | ✅ | ✅ |

---

## 📚 Further Reading

* **mcp-cli GitHub** → [https://github.com/chrishayuk/mcp-cli](https://github.com/chrishayuk/mcp-cli)
* **CHUK-MCP Protocol** → [https://github.com/chrishayuk/chuk-mcp](https://github.com/chrishayuk/chuk-mcp)
* **MCP Context Forge Gateway** → [https://github.com/IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge)
* **MCP Specification** → [https://modelcontextprotocol.io/](https://modelcontextprotocol.io/)

---

## 🎯 Quick Start Checklist

- [ ] Install mcp-cli: `pip install -e ".[cli,dev]"`
- [ ] Install MCP Context Forge Gateway
- [ ] Start gateway: `make serve` (runs on localhost:4444)
- [ ] Create `server_config.json` with correct Python path
- [ ] Generate JWT token for authentication
- [ ] Test connection: `mcp-cli ping --server mcpgateway-wrapper`
- [ ] Install Ollama and pull a compatible model (recommended)
- [ ] Start chat: `mcp-cli chat --server mcpgateway-wrapper --provider ollama --model mistral-nemo:latest`
- [ ] Try asking: "What tools are available?" or "What issues have been assigned to me?"
