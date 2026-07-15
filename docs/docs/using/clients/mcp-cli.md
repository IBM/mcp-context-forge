# 🖥️ MCP CLI + ContextForge Gateway

A powerful, feature-rich command-line interface for interacting with Model Context Protocol servers through **IBM's ContextForge Gateway**. The mcp-cli provides multiple operational modes including chat, interactive shell, and scriptable automation, with support for multiple LLM providers.

With mcp-cli → ContextForge Gateway you can:

* 🔧 **Auto-discover tools** from your ContextForge Gateway and use them seamlessly
* 🔄 **Switch between providers** (OpenAI, Anthropic, Ollama) during sessions
* 📊 **Export conversation history** to JSON for analysis and debugging
* 🤖 **Chat with LLMs** that automatically invoke Gateway tools and resources
* 📜 **Automate workflows** with scriptable command-line operations
* 🛠️ **Compare modes** - chat vs. interactive vs. command-line automation

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 🛠 Prerequisites

* **Python ≥ 3.11**
* **uv** (recommended) or pip for dependency management
* **ContextForge Gateway** running locally or remotely (default: http://localhost:4444)
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

### Install ContextForge Gateway

```bash
# Clone ContextForge repository
git clone https://github.com/IBM/mcp-context-forge
cd mcp-context-forge

# Install and start the gateway
make venv install serve
# Gateway will be available at http://localhost:4444
```

---

## ⚙️ Configuring Your Server

Create a `server_config.json` file to define your ContextForge Gateway connection:

### Basic Configuration (Direct HTTP)

```json
{
  "mcpServers": {
    "contextforge": {
      "transport": {
        "type": "http",
        "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
        "headers": {
          "Authorization": "Bearer <YOUR_AUTH_TOKEN_HERE>"
        }
      }
    }
  }
}
```

### Docker-based Configuration (Production)

```json
{
  "mcpServers": {
    "contextforge": {
      "transport": {
        "type": "http",
        "url": "http://host.docker.internal:4444/servers/UUID_OF_SERVER_1/mcp",
        "headers": {
          "Authorization": "Bearer ${MCPGATEWAY_BEARER_TOKEN}"
        }
      }
    }
  }
}
```

> **💡 Generate a JWT token for your Gateway**

```bash
# From your mcp-context-forge directory
python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes
```

> **⚠️ Important Notes**
> - Make sure your ContextForge Gateway is running on the correct port (default: 4444)

---

## 🌐 Available Modes

### 1. Chat Mode (Default)

Natural language interface where LLMs automatically use available tools:

```bash
# Default chat mode with OpenAI (using HTTP transport)
export OPENAI_API_KEY="your-api-key"
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge

# Using Ollama (recommended to avoid OpenAI tool name length limits)
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest

# Using Anthropic
export ANTHROPIC_API_KEY="your-api-key"
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider anthropic --model claude-sonnet-4-20250514
```

### 2. Interactive Mode

Command-driven shell interface for direct server operations:

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli interactive --server contextforge
```

### 3. Command Mode

Unix-friendly interface for automation and pipeline integration:

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# Process content with LLM
mcp-cli cmd --server contextforge --input document.md --prompt "Summarize: {{input}}"

# Direct tool invocation
mcp-cli cmd --server contextforge --tool github-server-list-notifications --raw

# Search for GitHub issues
mcp-cli cmd --server contextforge --tool github-server-search-issues --tool-args '{"q":"assignee:@me"}' --raw
```

### 4. Direct Commands

Run individual commands without entering interactive mode:

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# List available tools
mcp-cli tools list --server contextforge

# Ping the gateway
mcp-cli ping --server contextforge

# List available prompts
mcp-cli prompts list --server contextforge

# List available resources
mcp-cli resources list --server contextforge
```

---

## 🧪 Verify Tool Discovery

Once connected to your ContextForge Gateway, mcp-cli automatically discovers all available tools:

1. **Test connection:** `mcp-cli ping --server contextforge`
2. **List tools:** `mcp-cli tools list --server contextforge`
3. **Start Chat Mode:** `mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest`
4. **Type `/tools`** - your Gateway tools should list automatically
5. **Try asking:** `"What tools are available?"` and the LLM will show discovered tools
6. **Test GitHub integration:** `"What issues have been assigned to me?"`

The CLI auto-discovers tools from your Gateway and makes them available across all modes.

---

## 🔧 LLM Provider Setup

### OpenAI (Has 64-character tool name limitation)

```bash
export OPENAI_API_KEY="sk-your-api-key-here"
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider openai --model gpt-4o-mini
```

**⚠️ Known Issue:** OpenAI has a 64-character limit for tool names, but some ContextForge tools exceed this limit (e.g., `github-server-add-pull-request-review-comment-to-pending-review` is 69 characters).

### Ollama (Recommended - No tool name limitations)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a function-calling capable model
ollama pull mistral-nemo:latest
# or
ollama pull llama3.2:latest

# Use with mcp-cli
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest
```

### Anthropic Claude

```bash
export ANTHROPIC_API_KEY="sk-ant-your-api-key-here"
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider anthropic --model claude-3-sonnet
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
# ContextForge Gateway connection
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

**Solution:** Ensure the mcp-cli package is correctly installed and the gateway is running.

```json
{
  "mcpServers": {
    "contextforge": {
      "transport": {
        "type": "http",
        "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
        "headers": {
          "Authorization": "Bearer <your-jwt-token>"
        }
      }
    }
  }
}
```

#### "MCP_SERVER_URL environment variable is required"

**Solution:** Ensure your server configuration includes the correct transport URL in the config file.

#### OpenAI Tool Name Length Error

**Error:** `string too long. Expected a string with maximum length 64`

**Solution:** Use Ollama or Anthropic instead:

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest
```

#### Model doesn't support tools

**Error:** `does not support tools (status code: 400)`

**Solution:** Use a function-calling capable model:

```bash
# Pull compatible models
ollama pull mistral-nemo:latest
ollama pull llama3.2:latest

# Use in mcp-cli
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"
mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest
```

---

## 📈 Advanced Usage Examples

### GitHub Integration

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# Get your GitHub profile
mcp-cli cmd --server contextforge --tool github-server-get-me --raw

# List notifications
mcp-cli cmd --server contextforge --tool github-server-list-notifications --raw

# Search for issues assigned to you
mcp-cli cmd --server contextforge --tool github-server-search-issues \
  --tool-args '{"q":"assignee:@me is:open"}' --raw

# Create a new issue
mcp-cli cmd --server contextforge --tool github-server-create-issue \
  --tool-args '{"owner":"username","repo":"repository","title":"New Issue","body":"Issue description"}' --raw
```

### File System Operations

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# List allowed directories
mcp-cli cmd --server contextforge --tool filesystem-downloads-list-allowed-directories --raw

# Read a file
mcp-cli cmd --server contextforge --tool filesystem-downloads-read-file \
  --tool-args '{"path":"/path/to/file.txt"}' --raw

# Search for files
mcp-cli cmd --server contextforge --tool filesystem-downloads-search-files \
  --tool-args '{"path":"/Users/username/Downloads","pattern":"*.pdf"}' --raw
```

### Memory Management

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# Store a memory
mcp-cli cmd --server contextforge --tool memory-server-store-memory \
  --tool-args '{"content":"Important project note","bucket":"work"}' --raw

# Get memories
mcp-cli cmd --server contextforge --tool memory-server-get-memories \
  --tool-args '{"bucket":"work"}' --raw
```

### Time Operations

```bash
export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp"

# Get current time
mcp-cli cmd --server contextforge --tool time-server-get-system-time --raw

# Convert time zones
mcp-cli cmd --server contextforge --tool time-server-convert-time \
  --tool-args '{"from_timezone":"UTC","to_timezone":"America/New_York","time":"2025-01-01T12:00:00Z"}' --raw
```

---

## 🔗 Integration with ContextForge Gateway

The mcp-cli integrates with ContextForge Gateway through HTTP transport:

### Local Development Setup

1. **Start the Gateway:**
   ```bash
   cd mcp-context-forge
   make serve  # Starts on http://localhost:4444
   ```

2. **Configure mcp-cli** (create `server_config.json`):
   ```json
   {
     "mcpServers": {
       "contextforge": {
         "transport": {
           "type": "http",
           "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp",
           "headers": {
             "Authorization": "Bearer <your-jwt-token>"
           }
         }
       }
     }
   }
   ```

3. **Test the connection:**
   ```bash
   mcp-cli ping --server contextforge
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
  ghcr.io/ibm/mcp-context-forge:1.0.0-RC-3

# Generate token
export MCPGATEWAY_BEARER_TOKEN=$(docker exec mcpgateway python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-secret-key)

# Test connection
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools
```

---

## 📝 Available Tool Categories

Your ContextForge Gateway provides these tool categories:

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
* **ContextForge Gateway** → [https://github.com/IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge)
* **MCP Specification** → [https://modelcontextprotocol.io/](https://modelcontextprotocol.io/)

---

## 🎯 Quick Start Checklist

- [ ] Install mcp-cli: `pip install -e ".[cli,dev]"`
- [ ] Install ContextForge Gateway
- [ ] Start gateway: `make serve` (runs on localhost:4444)
- [ ] Create `server_config.json` with correct Python path
- [ ] Generate JWT token for authentication
- [ ] Test connection: `mcp-cli ping --server contextforge`
- [ ] Install Ollama and pull a compatible model (recommended)
- [ ] Start chat: `export MCP_SERVER_URL="http://localhost:4444/servers/UUID_OF_SERVER_1/mcp" && mcp-cli chat --server contextforge --provider ollama --model mistral-nemo:latest`
- [ ] Try asking: "What tools are available?" or "What issues have been assigned to me?"
