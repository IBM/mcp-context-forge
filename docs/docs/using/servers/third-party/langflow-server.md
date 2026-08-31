# 🌊 Langflow MCP Server Integration

**Langflow** is a visual framework for building multi-agent and RAG applications through an intuitive drag-and-drop interface. Langflow implements the **Model Context Protocol (MCP)** natively, exposing flows as MCP tools via Server-Sent Events (SSE). When integrated with **ContextForge Gateway**, Langflow workflows become accessible as standardized MCP tools with enterprise-grade security, observability, and federation capabilities.

> **Perfect for visual AI workflow automation** - Langflow's visual interface combined with ContextForge's federation capabilities creates powerful, discoverable AI automation tools.

**Documentation**: See [Langflow MCP Server Documentation](https://docs.langflow.org/mcp-server) for Langflow's native MCP implementation details.

---

## 🌟 Overview

### What is Langflow?

**Langflow** is a visual framework that allows you to:

- **Build AI workflows visually** with drag-and-drop components
- **Create RAG applications** with document processing and retrieval
- **Design multi-agent systems** with coordinated AI agents
- **Expose workflows as APIs** for integration with external systems
- **Support multiple LLM providers** (OpenAI, Anthropic, local models)

### Integration Benefits

When federated with ContextForge, you get:

- ✅ **Workflow-as-Tools** - Langflow workflows become discoverable MCP tools
- ✅ **Visual Development** - No code required for complex AI automation
- ✅ **Enterprise Security** - JWT authentication and rate limiting via ContextForge
- ✅ **Observability** - Comprehensive metrics and logging for workflow execution
- ✅ **Federation** - Combine Langflow workflows with other MCP servers
- ✅ **Version Control** - Track and manage workflow versions through ContextForge

---

## 🚀 Prerequisites

### Required Software

- **Langflow 1.0+** installed and running
- **ContextForge Gateway** running (see [Quick Start](../../../overview/quick_start.md))
- **Python 3.10+** for Langflow
- **Docker** (optional, for containerized deployment)

### Langflow Installation

#### Option A: pip Installation (Recommended)
```bash
# Install Langflow
pip install langflow

# Start Langflow server
langflow run --host 0.0.0.0 --port 7860
```

#### Option B: Docker Installation
```bash
# Run Langflow container
docker run -it --rm \
    -p 7860:7860 \
    -v $(pwd)/langflow_data:/app/data \
    langflowai/langflow:latest

# Or with custom configuration
docker run -it --rm \
    -p 7860:7860 \
    -e LANGFLOW_HOST=0.0.0.0 \
    -e LANGFLOW_PORT=7860 \
    -v $(pwd)/langflow_data:/app/data \
    langflowai/langflow:latest
```

#### Option C: Development Installation
```bash
# Clone Langflow repository
git clone https://github.com/logspace-ai/langflow.git
cd langflow

# Install development dependencies
pip install -e ".[dev]"

# Start development server
langflow run --dev
```

### Required Environment Variables

```bash
# Langflow Configuration
LANGFLOW_HOST=0.0.0.0
LANGFLOW_PORT=7860
LANGFLOW_BACKEND_ONLY=false
LANGFLOW_DATABASE_URL=sqlite:///./langflow.db

# Optional: Authentication
LANGFLOW_SECRET_KEY=your-secret-key
LANGFLOW_SUPERUSER=admin@example.com
LANGFLOW_SUPERUSER_PASSWORD=admin123

# Optional: LLM Provider Keys
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
```

---

## 🔧 Server Configuration

### Workflow Setup

#### Step 1: Create Langflow Workflows

1. **Access Langflow UI**: Navigate to `http://localhost:7860`
2. **Create a new workflow** using the visual interface
3. **Add components** (LLMs, prompts, retrievers, etc.)
4. **Configure inputs and outputs**
5. **Test the workflow** to ensure it works correctly
6. **Save the workflow** with a descriptive name

#### Step 2: API Endpoint Configuration

Langflow automatically exposes workflows as REST API endpoints:

```bash
# Default API endpoint format
http://localhost:7860/api/v1/run/{flow_id}

# With custom tweaks
http://localhost:7860/api/v1/run/{flow_id}?tweaks={tweaks_json}

# Example workflow endpoints
http://localhost:7860/api/v1/run/document-qa-workflow
http://localhost:7860/api/v1/run/multi-agent-chat
http://localhost:7860/api/v1/run/data-analysis-pipeline
```

#### Step 3: Workflow Exposure Configuration

Configure workflows for MCP integration:

```python
# langflow_config.py
LANGFLOW_MCP_CONFIG = {
    "workflows": [
        {
            "id": "document-qa-workflow",
            "name": "Document Q&A",
            "description": "Answer questions about uploaded documents",
            "inputs": ["question", "document"],
            "outputs": ["answer", "sources"]
        },
        {
            "id": "multi-agent-chat",
            "name": "Multi-Agent Chat",
            "description": "Coordinate multiple AI agents for complex tasks",
            "inputs": ["task", "context"],
            "outputs": ["result", "agent_logs"]
        },
        {
            "id": "data-analysis-pipeline",
            "name": "Data Analysis Pipeline",
            "description": "Analyze data and generate insights",
            "inputs": ["data", "analysis_type"],
            "outputs": ["insights", "visualizations"]
        }
    ]
}
```

---

## 🔌 ContextForge Integration

### Server Registration

**Important**: Langflow implements the Model Context Protocol (MCP) natively. Each Langflow project exposes its flows as MCP tools via an SSE endpoint.

#### Step 1: Get Your Langflow Project ID

1. **Open Langflow UI**: Navigate to `http://localhost:7860`
2. **Navigate to Projects**: Click "Projects" in the left sidebar
3. **Select or Create a Project**: Open your project or create a new one
4. **Go to MCP Server Tab**: Click on the "MCP Server" tab (or "Settings" → "MCP Server")
5. **Copy the Project ID**: Format is a UUID like `9776a127-e839-4427-936c-4bb28156a62c`

The MCP endpoint format is:
```
http://localhost:7860/api/v1/mcp/project/{PROJECT_ID}/sse
```

**Save the Project ID**:
```bash
export LANGFLOW_PROJECT_ID="<paste-your-project-id-here>"
# Example: export LANGFLOW_PROJECT_ID="9776a127-e839-4427-936c-4bb28156a62c"
```

#### Step 2: Register Langflow MCP Server

```bash
# Register Langflow as a peer gateway using the correct SSE endpoint
curl -X POST "http://localhost:4444/gateways" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "name": "Langflow MCP Server",
    "url": "http://localhost:7860/api/v1/mcp/project/'"$LANGFLOW_PROJECT_ID"'/sse",
    "description": "Langflow MCP server exposing flows as tools",
    "transport_type": "sse"
  }'
```

**Important Notes**:

- ✅ **Correct**: `http://localhost:7860/api/v1/mcp/project/{PROJECT_ID}/sse` - This is the MCP SSE endpoint
- ❌ **Wrong**: `http://localhost:7860` - This is just the Langflow UI, not an MCP endpoint
- The `transport_type` must be `"sse"`, not `"http"`
- Each Langflow project has a unique MCP endpoint based on its Project ID

#### Step 3: Verify Gateway Registration

```bash
# List all registered gateways
curl -X GET "http://localhost:4444/gateways" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Should see your Langflow gateway in the list
```

**Verify in Admin UI**:

1. Open http://localhost:4444/admin
2. Navigate to "Gateways" section
3. Confirm "Langflow MCP Server" appears with status "active"

### Discover Available Tools

Once the Langflow gateway is registered, ContextForge automatically discovers all flows and exposes them as tools.

```bash
# List all tools across all gateways
curl -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | jq

# You should see your Langflow flows listed as tools with names like:
# - langflow-mcp-server-test-echo-workflow
# - langflow-mcp-server-basic-prompting
```

**Example Response:**
```json
[
  {
    "id": "tool-id-here",
    "name": "langflow-mcp-server-test-echo-workflow",
    "displayName": "Test Echo Workflow",
    "description": "Chain the Words, Master Language!",
    "gatewaySlug": "langflow-mcp-server",
    "enabled": true,
    "reachable": true,
    "inputSchema": {
      "type": "object",
      "properties": {
        "input_value": {
          "type": "string",
          "description": "Message to be passed as input."
        }
      }
    }
  }
]
```

**Workflow-to-Tool Naming Convention**:

- Langflow flows are automatically converted to MCP tools
- Tool names follow the pattern: `langflow-mcp-server-{flow-name}`
- Each tool includes the complete input/output schema

---

## 💡 Usage Examples

**Important**: ContextForge uses JSON-RPC protocol for tool invocation via the `/rpc` endpoint.

### Echo Workflow Example

```bash
# Execute test echo workflow using JSON-RPC
curl -X POST "http://localhost:4444/rpc" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "langflow-mcp-server-test-echo-workflow",
      "arguments": {
        "input_value": "Hello from ContextForge!"
      }
    },
    "id": 1
  }'

# Expected Response
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Hello from ContextForge!"
      }
    ],
    "is_error": false
  }
}
```

### Basic Prompting Workflow

```bash
# Execute the basic_prompting workflow using JSON-RPC
curl -X POST "http://localhost:4444/rpc" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "langflow-mcp-server-basic-prompting",
      "arguments": {
        "input_value": "What is the meaning of life?"
      }
    },
    "id": 2
  }'

# Expected Response
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "The meaning of life is a philosophical question..."
      }
    ],
    "is_error": false
  }
}
```

**Note**: This workflow requires an OpenAI API key to be configured in Langflow.

### View Execution Metrics

After executing tools, check the updated metrics:

```bash
# Get updated tool list with metrics
curl -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | jq '.[].metrics'
```

You'll see updated metrics including:

- `totalExecutions`: Number of times the tool was invoked
- `successfulExecutions`: Successful invocations
- `failedExecutions`: Failed invocations
- `avgResponseTime`: Average response time
- `lastExecutionTime`: Timestamp of last execution

### Best Practices for Workflow Design

#### 1. Modular Workflow Design
```python
# Example: Modular RAG workflow
components = {
    "document_loader": {
        "type": "file_loader",
        "config": {"chunk_size": 1000, "overlap": 200}
    },
    "embeddings": {
        "type": "openai_embeddings",
        "config": {"model": "text-embedding-3-small"}
    },
    "vector_store": {
        "type": "chroma",
        "config": {"persist_directory": "./chroma_db"}
    },
    "retriever": {
        "type": "similarity_search",
        "config": {"k": 5}
    },
    "llm": {
        "type": "openai_chat",
        "config": {"model": "gpt-4", "temperature": 0.1}
    }
}
```

#### 2. Error Handling and Validation
```python
# Workflow input validation
def validate_workflow_inputs(workflow_id, inputs):
    validation_rules = {
        "document-qa-workflow": {
            "question": {"type": "string", "required": True, "min_length": 5},
            "document": {"type": "string", "required": True}
        },
        "data-analysis-pipeline": {
            "data": {"type": "string", "required": True},
            "analysis_type": {"type": "string", "enum": ["trend", "correlation", "summary"]}
        }
    }
    return validate_inputs(inputs, validation_rules[workflow_id])
```

#### 3. Performance Optimization
```python
# Workflow caching configuration
cache_config = {
    "enable_caching": True,
    "cache_duration": 3600,  # 1 hour
    "cache_key_fields": ["question", "document_hash"],
    "cache_backend": "redis"
}
```

---

## 🔍 Troubleshooting

### Critical: Gateway Registration Failures

**Problem**: "Unable to connect to gateway" error when registering Langflow

**Common Causes**:

1. **Wrong URL** - Most common issue!
   ```bash
   # ❌ WRONG - This will fail
   "url": "http://localhost:7860"

   # ✅ CORRECT - Use the MCP SSE endpoint
   "url": "http://localhost:7860/api/v1/mcp/project/{PROJECT_ID}/sse"
   ```

2. **Missing Project ID**
   ```bash
   # Get your project ID from Langflow UI
   # Projects → Your Project → MCP Server tab
   ```

3. **Wrong transport_type**
   ```bash
   # ❌ WRONG
   "transport_type": "http"

   # ✅ CORRECT
   "transport_type": "sse"
   ```

**Debug:**
```bash
# Check Langflow is accessible
curl -v http://localhost:7860/health

# Test MCP endpoint (should return SSE stream)
curl -v http://localhost:7860/api/v1/mcp/project/$LANGFLOW_PROJECT_ID/sse

# Try registration with verbose output
curl -v -X POST "http://localhost:4444/gateways" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "name": "Langflow MCP Server",
    "url": "http://localhost:7860/api/v1/mcp/project/'"$LANGFLOW_PROJECT_ID"'/sse",
    "description": "Langflow MCP server",
    "transport_type": "sse"
  }'
```

### Critical: Tool Invocation Failures

**Problem**: "Method Not Allowed" error when invoking tools

**Root Cause**: Using wrong endpoint or HTTP method

**Solution**:
```bash
# ❌ WRONG - This will fail with "Method Not Allowed"
curl -X POST "http://localhost:4444/tools/invoke"

# ✅ CORRECT - Use /rpc endpoint with JSON-RPC format
curl -X POST "http://localhost:4444/rpc" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "langflow-mcp-server-test-echo-workflow",
      "arguments": {
        "input_value": "test"
      }
    },
    "id": 1
  }'
```

**Debug Steps**:
```bash
# 1. Check exact tool names
curl -s -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | jq '.[].name'

# 2. Check tool input schema
curl -s -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | \
  jq '.[] | select(.name == "langflow-mcp-server-test-echo-workflow") | .inputSchema'

# 3. Check tool reachability
curl -s -X GET "http://localhost:4444/tools" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | \
  jq '.[] | {name, enabled, reachable}'
```

### Workflow Execution Errors

**Problem**: Workflow fails with component errors

**Solution**:
```bash
# Check Langflow logs
docker logs langflow-container

# Enable debug mode
LANGFLOW_LOG_LEVEL=DEBUG langflow run

# Validate workflow configuration
curl -X GET "http://localhost:7860/api/v1/flows/{flow_id}/validate"
```

**Problem**: Timeout errors for long-running workflows

**Solution**:
```yaml
# Increase timeout in ContextForge configuration
servers:

  - id: "langflow-server"
    settings:
      timeout: 300  # 5 minutes
      retry_attempts: 1
```

### API Connectivity Issues

**Problem**: Cannot connect to Langflow API

**Solution**:
```bash
# Check Langflow health
curl -X GET "http://localhost:7860/health"

# Verify API endpoints
curl -X GET "http://localhost:7860/api/v1/flows"

# Check network connectivity
telnet localhost 7860
```

**Problem**: Authentication errors

**Solution**:
```bash
# Configure Langflow authentication if enabled
LANGFLOW_SECRET_KEY=your-secret-key
LANGFLOW_SUPERUSER=admin@example.com

# Update ContextForge auth configuration
auth:
  type: "bearer"
  token: "${LANGFLOW_API_TOKEN}"
```

### Performance Optimization

**Problem**: Slow workflow execution

**Solution**:

1. **Enable caching** for repetitive operations
2. **Optimize component configurations** (reduce model sizes, chunk sizes)
3. **Use streaming responses** for long workflows
4. **Implement async execution** for non-blocking operations

```python
# Performance optimization example
optimization_config = {
    "async_execution": True,
    "streaming_response": True,
    "component_caching": True,
    "parallel_processing": True
}
```

**Problem**: Memory issues with large documents

**Solution**:
```python
# Document processing optimization
document_config = {
    "chunk_size": 500,  # Smaller chunks
    "batch_processing": True,
    "lazy_loading": True,
    "memory_limit": "2GB"
}
```

### Common Error Codes and Solutions

| Error Code | Description | Solution |
|------------|-------------|----------|
| 400 | Invalid workflow input | Validate input parameters |
| 404 | Workflow not found | Check workflow ID and existence |
| 408 | Workflow timeout | Increase timeout or optimize workflow |
| 429 | Rate limit exceeded | Implement request throttling |
| 500 | Internal workflow error | Check Langflow logs and component configuration |

### Debug Mode Configuration

Enable detailed logging for troubleshooting:

```yaml
servers:

  - id: "langflow-server"
    settings:
      debug_mode: true
      log_level: "debug"
      log_requests: true
      log_responses: true
      workflow_tracing: true
```

---

## 🚀 Advanced Configuration

### Custom Workflow Adapters

Create custom adapters for specialized workflows:

```python
# custom_langflow_adapter.py
class LangflowMCPAdapter:
    def __init__(self, langflow_url, workflows_config):
        self.langflow_url = langflow_url
        self.workflows = workflows_config

    def convert_workflow_to_mcp_tool(self, workflow):
        return {
            "name": f"langflow_{workflow['id']}",
            "description": workflow['description'],
            "inputSchema": self.generate_input_schema(workflow),
            "outputSchema": self.generate_output_schema(workflow)
        }

    def execute_workflow(self, workflow_id, inputs):
        # Custom execution logic
        response = requests.post(
            f"{self.langflow_url}/api/v1/run/{workflow_id}",
            json=inputs
        )
        return self.format_response(response.json())
```

### Environment-Specific Configuration

#### Production Configuration
```yaml
# production.yaml
servers:

  - id: "langflow-production"
    name: "Langflow Production"
    transport:
      type: "https"
      endpoint: "https://langflow.company.com"
    auth:
      type: "bearer"
      token: "${LANGFLOW_PRODUCTION_TOKEN}"
    settings:
      timeout: 180
      retry_attempts: 3
      rate_limit_handling: true
      health_check_interval: 30
      connection_pool_size: 20
```

#### Development Configuration
```yaml
# development.yaml
servers:

  - id: "langflow-dev"
    name: "Langflow Development"
    transport:
      type: "http"
      endpoint: "http://localhost:7860"
    settings:
      timeout: 300
      debug_mode: true
      log_level: "debug"
      reload_on_change: true
```

### Workflow Version Management

```python
# workflow_versioning.py
workflow_versions = {
    "document-qa-workflow": {
        "v1.0": {"endpoint": "/api/v1/run/document-qa-v1"},
        "v1.1": {"endpoint": "/api/v1/run/document-qa-v1.1"},
        "latest": {"endpoint": "/api/v1/run/document-qa-latest"}
    }
}

def get_workflow_endpoint(workflow_id, version="latest"):
    return workflow_versions[workflow_id][version]["endpoint"]
```

---

## 📚 References and Additional Resources

### Official Langflow Documentation
- [Langflow MCP Server](https://docs.langflow.org/mcp-server) - **Official MCP implementation documentation**
- [Langflow GitHub](https://github.com/logspace-ai/langflow) - Official Langflow repository
- [Langflow Documentation](https://docs.langflow.org/) - Comprehensive documentation
- [Langflow API Reference](https://docs.langflow.org/api-reference) - REST API documentation
- [Langflow Components](https://docs.langflow.org/components) - Available workflow components

### Visual AI Workflow Best Practices
- [RAG Application Design](https://docs.langflow.org/tutorials/rag-applications) - Building RAG applications
- [Multi-Agent Systems](https://docs.langflow.org/tutorials/multi-agent) - Designing multi-agent workflows
- [Custom Components](https://docs.langflow.org/custom-components) - Creating custom workflow components

### Integration Resources
- [Langflow API Integration](https://docs.langflow.org/integration/api) - API integration guide
- [Deployment Strategies](https://docs.langflow.org/deployment) - Production deployment options
- [Authentication Setup](https://docs.langflow.org/configuration/authentication) - Security configuration

### ContextForge Documentation
- [ContextForge Integration](../../index.md) - Server integration overview
- [Virtual Server Composition](../../../manage/api-usage.md#virtual-server-management) - Combining multiple servers
- [Authentication Configuration](../../../manage/sso.md) - Gateway authentication setup

### Community and Support
- [Langflow Community](https://github.com/logspace-ai/langflow/discussions) - Community discussions
- [Langflow Discord](https://discord.gg/langflow) - Real-time community support
- [ContextForge Issues](https://github.com/IBM/mcp-context-forge/issues) - Report integration issues
