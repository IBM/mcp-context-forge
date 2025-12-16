# OpenWebUI with Ollama, LiteLLM, MCPO, and MCP Gateway Deployment Guide

This guide provides a comprehensive walkthrough for deploying OpenWebUI with local LLM models via Ollama, integrated with MCP (Model Context Protocol) tools through MCPO and MCP Gateway.

## 🏗 Architecture Overview

This deployment creates a powerful AI assistant platform with local model hosting and extensible tool capabilities:

```mermaid
flowchart TD
  %% User Interface
  U[🌐 User Browser] -->|HTTPS :443| OW

  %% Core Components
  subgraph "OpenWebUI Deployment"
    OW[OpenWebUI Container 🖥️<br/>Web Interface]
    LL[LiteLLM Proxy 🔄<br/>Model Gateway<br/>Port 4000]
    DB[PostgreSQL Database 🗄️<br/>Port 5432]
  end

  %% Local AI Backend
  subgraph "Local AI Backend"
    OL[Ollama Server 🤖<br/>Port 11434<br/>Local LLM Models]
  end

  %% MCP Integration Layer
  subgraph "MCP Integration"
    MCPO[MCPO Server 🔌<br/>Port 8000<br/>MCP → OpenAPI Bridge]
    MCG[MCP Gateway 🚪<br/>Port 4444<br/>MCP Registry & Federation]
    MCP1[MCP Server 1 📦]
    MCP2[MCP Server 2 📦]
    MCPN[MCP Server N 📦]
  end

  %% External Services
  subgraph "External Services"
    OP[OAuth Provider 🔐<br/>Port 443]
  end

  %% Connections
  OW -.->|"OAuth Login"| OP
  OW -->|"Model API Calls"| LL
  OW -->|"Tool API Calls"| MCPO
  OW -->|"DB Connection"| DB

  LL -->|"Model Requests"| OL

  MCPO -->|"Register & Proxy"| MCG
  MCG -->|"MCP Protocol"| MCP1
  MCG -->|"MCP Protocol"| MCP2
  MCG -->|"MCP Protocol"| MCPN

  %% Styling
  classDef deployment fill:#1F618D,stroke:#85C1E9,stroke-width:2px,color:#FFF;
  classDef ai fill:#27AE60,stroke:#58D68D,stroke-width:2px,color:#FFF;
  classDef mcp fill:#8E44AD,stroke:#BB8FCE,stroke-width:2px,color:#FFF;
  classDef external fill:#E74C3C,stroke:#F5B7B1,stroke-width:2px,color:#FFF;

  class OW,LL,DB deployment;
  class OL ai;
  class MCPO,MCG,MCP1,MCP2,MCPN mcp;
  class OP external;
```

### Components Overview

1. **OpenWebUI**: Feature-rich web interface for AI interactions
2. **Ollama**: Local LLM runtime supporting various models (Llama, Mistral, Granite, etc.)
3. **LiteLLM**: Unified proxy providing OpenAI-compatible API for multiple model backends
4. **MCPO**: Bridges MCP servers to OpenAPI, making tools accessible to OpenWebUI
5. **MCP Gateway**: Central registry and federation point for MCP servers
6. **PostgreSQL**: Persistent storage for OpenWebUI data

---

## 📋 Prerequisites

- **Operating System**: Linux, macOS, or Windows with WSL2
- **Docker/Podman**: Container runtime installed and running
- **Python 3.8+**: For running MCPO and MCP tools
- **8GB+ RAM**: Recommended for running local models
- **20GB+ Storage**: For model files and data

---

## 🚀 Deployment Steps

### Step 1: PostgreSQL Database Setup

First, set up a PostgreSQL database for OpenWebUI's persistent storage:

```bash
# Create a Docker network for service communication
docker network create openwebui-net

# Run PostgreSQL container
docker run -d \
  --name postgres \
  --network openwebui-net \
  -e POSTGRES_DB=openwebui \
  -e POSTGRES_USER=openwebui \
  -e POSTGRES_PASSWORD=changeme \
  -v postgres_data:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:15-alpine

# Verify PostgreSQL is running
docker logs postgres
```

### Step 2: Install and Configure Ollama

#### 2.1 Install Ollama

**Important**: Install Ollama on the host system, not in a container or WSL2.

```bash
# Universal installer for macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# For Windows, download from: https://ollama.com/download
```

#### 2.2 Pull AI Models

```bash
# Pull IBM Granite model (recommended)
ollama pull granite3.3

# Alternative smaller model for lower-end hardware
ollama pull granite3.3:2b

# Pull additional models as needed
ollama pull llama3.2
ollama pull mistral

# List installed models
ollama list

# Test model
ollama run granite3.3 "Hello, how are you?"
```

#### 2.3 Configure Ollama for Network Access

By default, Ollama only listens on localhost. To make it accessible to containers:

```bash
# Linux/macOS: Edit systemd service
sudo systemctl edit ollama.service

# Add these lines:
[Service]
Environment="OLLAMA_HOST=0.0.0.0"

# Restart Ollama
sudo systemctl restart ollama

# Verify it's listening on all interfaces
curl http://localhost:11434/api/tags
```

### Step 3: Deploy LiteLLM Proxy

LiteLLM provides an OpenAI-compatible API interface for Ollama models:

```bash
# Create LiteLLM configuration
cat > litellm_config.yaml <<EOF
model_list:

  - model_name: granite
    litellm_params:
      model: ollama/granite3.3
      api_base: http://host.docker.internal:11434

  - model_name: llama
    litellm_params:
      model: ollama/llama3.2
      api_base: http://host.docker.internal:11434

  - model_name: mistral
    litellm_params:
      model: ollama/mistral
      api_base: http://host.docker.internal:11434

general_settings:
  master_key: "sk-1234567890"  # Change this!
  database_url: "postgresql://openwebui:changeme@postgres:5432/litellm"
EOF

# Run LiteLLM container
docker run -d \
  --name litellm \
  --network openwebui-net \
  -v $(pwd)/litellm_config.yaml:/app/config.yaml \
  -p 4000:4000 \
  ghcr.io/berriai/litellm:main \
  --config /app/config.yaml \
  --detailed_debug

# Test LiteLLM
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer sk-1234567890"
```

### Step 4: Set Up MCP Gateway

Deploy the MCP Gateway (ContextForge) for managing MCP servers:

```bash
# Create data directory
mkdir -p $(pwd)/mcpgateway_data

# Run MCP Gateway
docker run -d \
  --name mcpgateway \
  --network openwebui-net \
  -p 4444:4444 \
  -v $(pwd)/mcpgateway_data:/data \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY=your-secret-key \
  -e BASIC_AUTH_USER=admin \
  -e BASIC_AUTH_PASSWORD=changeme \
  -e AUTH_REQUIRED=true \
  ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1

# Generate an API token for later use
docker exec mcpgateway \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username admin --exp 0 --secret your-secret-key
```

Access the MCP Gateway UI at http://localhost:4444/admin (admin/changeme).

### Step 5: Deploy MCPO

MCPO exposes MCP servers as OpenAPI-compatible endpoints:

```bash
# Install MCPO using UV (recommended)
pip install uv
uvx mcpo --version

# Or install with pip
pip install mcpo

# Create MCPO configuration
cat > mcpo_config.json <<EOF
{
  "mcpServers": {
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone=America/New_York"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
EOF

# Run MCPO with configuration
uvx mcpo \
  --port 8000 \
  --api-key "mcpo-secret-key" \
  --config mcpo_config.json

# Test MCPO endpoints
curl http://localhost:8000/docs
curl http://localhost:8000/time/docs
curl -H "Authorization: Bearer mcpo-secret-key" \
  http://localhost:8000/time/list-tools
```

### Step 6: Deploy OpenWebUI

Now deploy OpenWebUI with all integrations configured:

```bash
# Create OpenWebUI environment file
cat > openwebui.env <<EOF
# Database
DATABASE_URL=postgresql://openwebui:changeme@postgres:5432/openwebui

# OAuth (optional - adjust for your provider)
ENABLE_OAUTH_SIGNUP=false
ENABLE_SIGNUP=true
WEBUI_AUTH=true

# Model Backend (LiteLLM)
OPENAI_API_BASE_URL=http://litellm:4000/v1
OPENAI_API_KEY=sk-1234567890

# UI Settings
WEBUI_NAME=AI Assistant Platform
DEFAULT_MODELS=granite,llama,mistral

# MCP Tools URL (via MCPO)
TOOLS_FUNCTION_CALLING_PROMPT="Use available tools to assist with user requests"
EOF

# Run OpenWebUI
docker run -d \
  --name openwebui \
  --network openwebui-net \
  --env-file openwebui.env \
  -p 3000:8080 \
  -v openwebui_data:/app/backend/data \
  --restart always \
  ghcr.io/open-webui/open-webui:latest

# Check logs
docker logs -f openwebui
```

---

## ⚙️ Configuration

### 6.1 Configure OpenWebUI Model Connection

1. Access OpenWebUI at http://localhost:3000
2. Create an admin account on first login
3. Navigate to **Settings** → **Connections**
4. Verify the OpenAI connection is configured:
   - **API Base URL**: `http://litellm:4000/v1`
   - **API Key**: `sk-1234567890`

### 6.2 Register MCP Tools in OpenWebUI

1. Go to **Settings** → **Tools**
2. Click **Add Tool Server**
3. Add MCPO endpoints:
   ```
   Name: MCP Time Tool
   URL: http://host.docker.internal:8000/time
   API Key: mcpo-secret-key
   ```
4. Repeat for other MCPO tools (filesystem, memory, etc.)

### 6.3 Enable Tools for Models

1. Navigate to **Workspace** → **Models**
2. Edit each model (granite, llama, mistral)
3. Scroll to **Tools** section
4. Toggle on the MCP tools you want available
5. Click **Save**

### 6.4 Add MCP Servers to Gateway

1. Access MCP Gateway at http://localhost:4444/admin
2. Navigate to **Gateways** tab
3. Click **Add Gateway** to register external MCP servers
4. Example configuration:
   ```
   Name: Local MCP Time Server
   URL: http://host.docker.internal:8000/time
   Auth Type: Bearer Token
   Token: mcpo-secret-key
   ```

---

## 🧪 Testing the Integration

### Test 1: Model Connectivity

```bash
# Test LiteLLM is serving models
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-1234567890" \
  -d '{
    "model": "granite",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Test 2: MCP Tool Invocation

In OpenWebUI chat:

1. Enable the time tool by clicking the ➕ icon
2. Ask: "What's the current time in New York?"
3. The assistant should use the MCP time tool to respond

### Test 3: Multi-Tool Workflow

Try complex queries that require multiple tools:

- "Save a note about today's meeting at 3 PM EST"
- "What files are in the /tmp directory?"

---

## 🔧 Advanced Configuration

### Adding Custom MCP Servers

1. Install any MCP server:
   ```bash
   npm install -g @your-org/mcp-server-custom
   ```

2. Add to MCPO config:
   ```json
   {
     "mcpServers": {
       "custom": {
         "command": "mcp-server-custom",
         "args": ["--option", "value"]
       }
     }
   }
   ```

3. Restart MCPO and register in OpenWebUI

### Using Functions and Filters

OpenWebUI supports custom functions for extending capabilities:

1. Go to **Settings** → **Functions**
2. Enable built-in functions or import custom ones
3. Functions can:
   - Act as custom models (Pipe Functions)
   - Modify inputs/outputs (Filter Functions)
   - Add action buttons (Action Functions)

### Performance Tuning

For production deployments:

```yaml
# litellm_config.yaml additions
general_settings:
  max_parallel_requests: 100
  request_timeout: 600
  stream_timeout: 60

router_settings:
  routing_strategy: "usage-based-routing"
  redis_host: "redis"
  redis_port: 6379
```

---

## 📊 Monitoring and Maintenance

### Container Health Checks

```bash
# Check all containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View logs
docker logs --tail 50 -f openwebui
docker logs --tail 50 -f litellm
docker logs --tail 50 -f mcpgateway

# Resource usage
docker stats
```

### Backup and Restore

```bash
# Backup PostgreSQL
docker exec postgres pg_dump -U openwebui openwebui > backup.sql

# Backup volumes
docker run --rm -v postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_backup.tar.gz -C /data .

# Restore PostgreSQL
docker exec -i postgres psql -U openwebui openwebui < backup.sql
```

---

## 🚨 Troubleshooting

### Common Issues

**1. Models not appearing in OpenWebUI**

- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Verify LiteLLM can reach Ollama: `docker logs litellm`
- Ensure model names match in litellm_config.yaml

**2. MCP tools not working**

- Verify MCPO is running: `curl http://localhost:8000/docs`
- Check tool registration in OpenWebUI settings
- Ensure tools are enabled for the model

**3. Container connectivity issues**

- Use `host.docker.internal` for host access from containers
- Ensure all containers are on the same network
- Check firewall rules

### Debug Commands

```bash
# Test inter-container connectivity
docker exec openwebui ping postgres
docker exec openwebui curl http://litellm:4000/health

# Check MCPO tool availability
curl -H "Authorization: Bearer mcpo-secret-key" \
  http://localhost:8000/{tool-name}/list-tools

# Verify MCP Gateway
curl -H "Authorization: Bearer $(cat mcpgateway_token.txt)" \
  http://localhost:4444/tools
```

---

## 🎯 Next Steps

1. **Add More Models**: Explore Ollama's model library
2. **Integrate More MCP Servers**: Browse [MCP servers directory](https://github.com/modelcontextprotocol/servers)
3. **Customize UI**: Modify OpenWebUI themes and settings
4. **Set Up Authentication**: Configure OAuth for production use
5. **Enable Web Search**: Add search capabilities to models
6. **Document Indexing**: Set up RAG with document collections

---

## 📚 Resources

- [OpenWebUI Documentation](https://docs.openwebui.com/)
- [Ollama Documentation](https://github.com/ollama/ollama)
- [LiteLLM Documentation](https://docs.litellm.ai/)
- [MCPO Documentation](https://github.com/open-webui/mcpo)
- [MCP Gateway Documentation](https://github.com/ibm/mcp-context-forge)
- [Model Context Protocol Spec](https://modelcontextprotocol.io/)

---

## 🐳 Docker Compose Deployment

For easier management, use Docker Compose:

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: openwebui
      POSTGRES_USER: openwebui
      POSTGRES_PASSWORD: changeme
    volumes:

      - postgres_data:/var/lib/postgresql/data
    networks:

      - openwebui-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U openwebui"]
      interval: 10s
      timeout: 5s
      retries: 5

  litellm:
    image: ghcr.io/berriai/litellm:main
    command: --config /app/config.yaml --detailed_debug
    volumes:

      - ./litellm_config.yaml:/app/config.yaml
    ports:

      - "4000:4000"
    networks:

      - openwebui-net
    depends_on:
      postgres:
        condition: service_healthy
    extra_hosts:

      - "host.docker.internal:host-gateway"

  mcpgateway:
    image: ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1
    environment:
      MCPGATEWAY_UI_ENABLED: "true"
      MCPGATEWAY_ADMIN_API_ENABLED: "true"
      DATABASE_URL: "sqlite:////data/mcp.db"
      HOST: "0.0.0.0"
      JWT_SECRET_KEY: "your-secret-key"
      BASIC_AUTH_USER: "admin"
      BASIC_AUTH_PASSWORD: "changeme"
      AUTH_REQUIRED: "true"
    volumes:

      - mcpgateway_data:/data
    ports:

      - "4444:4444"
    networks:

      - openwebui-net

  openwebui:
    image: ghcr.io/open-webui/open-webui:latest
    env_file:

      - openwebui.env
    ports:

      - "3000:8080"
    volumes:

      - openwebui_data:/app/backend/data
    networks:

      - openwebui-net
    depends_on:

      - postgres
      - litellm
    extra_hosts:

      - "host.docker.internal:host-gateway"

volumes:
  postgres_data:
  mcpgateway_data:
  openwebui_data:

networks:
  openwebui-net:
    driver: bridge
```

Deploy with:
```bash
docker-compose up -d
docker-compose logs -f
```

---

## 🔒 Security Best Practices

### 1. Use Strong Secrets

```bash
# Generate secure tokens
openssl rand -hex 32  # For JWT secrets
openssl rand -base64 32  # For API keys
```

### 2. Enable HTTPS

For production, use a reverse proxy with SSL:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. Network Isolation

```yaml
# docker-compose.yml addition
services:
  openwebui:
    networks:

      - frontend
      - backend

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true
```

### 4. Resource Limits

```yaml
services:
  openwebui:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

---
