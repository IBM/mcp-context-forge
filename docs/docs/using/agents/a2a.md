# A2A (Agent-to-Agent) Integration

The MCP Gateway supports A2A (Agent-to-Agent) integration, allowing you to register external AI agents and expose them as MCP tools for seamless integration with other agents and MCP clients.

## Overview

A2A integration enables you to:

- **Register external AI agents** (OpenAI, Anthropic, custom agents)
- **Expose agents as MCP tools** for universal discovery and access
- **Support multiple protocols** (JSONRPC, custom formats)
- **Manage agent lifecycle** through admin UI and APIs
- **Monitor performance** with comprehensive metrics
- **Configure authentication** with various auth methods

## Quick Start

### 1. Enable A2A Features

```bash
# In your .env file or environment variables
MCPGATEWAY_A2A_ENABLED=true
MCPGATEWAY_A2A_METRICS_ENABLED=true
```

### 2. Register an A2A Agent

**Via Admin UI:**

1. Go to `http://localhost:4444/admin`
2. Click the "A2A Agents" tab
3. Fill out the "Add New A2A Agent" form
4. Click "Add A2A Agent"

**Via REST API:**
```bash
curl -X POST "http://localhost:4444/a2a" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hello_world_agent",
    "endpoint_url": "http://localhost:9999/",
    "agent_type": "jsonrpc",
    "description": "External AI agent for hello world functionality",
    "auth_type": "api_key",
    "auth_value": "your-api-key",
    "tags": ["ai", "hello-world"]
  }'
```

### 3. Test the Agent

**Via Admin UI:**

- Click the blue "Test" button next to your agent
- See real-time test results

**Via API:**
```bash
curl -X POST "http://localhost:4444/a2a/hello_world_agent/invoke" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": {
      "method": "message/send",
      "params": {
        "message": {
          "messageId": "test-123",
          "role": "user",
          "parts": [{"type": "text", "text": "Hello!"}]
        }
      }
    },
    "interaction_type": "test"
  }'
```

### 4. Create Virtual Server with A2A Agent

```bash
curl -X POST "http://localhost:4444/servers" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI Assistant Server",
    "description": "Virtual server with AI agents",
    "associated_a2a_agents": ["agent-id-from-step-2"]
  }'
```

### 5. Use Agent via MCP Protocol

```bash
# A2A agents are now available as MCP tools
curl -X POST "http://localhost:4444/rpc" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "a2a_hello_world_agent",
      "arguments": {
        "method": "message/send",
        "params": {"message": {"messageId": "test", "role": "user", "parts": [{"type": "text", "text": "Hi!"}]}}
      }
    },
    "id": 1
  }'
```

## Agent Types

### Generic/JSONRPC Agents
For agents that expect standard JSONRPC format:
```json
{
  "agent_type": "jsonrpc",
  "endpoint_url": "http://your-agent/",
  "protocol_version": "1.0"
}
```

### OpenAI-compatible Agents
```json
{
  "agent_type": "openai",
  "endpoint_url": "https://api.openai.com/v1/chat/completions",
  "auth_type": "api_key",
  "auth_value": "your-openai-api-key"
}
```

### Anthropic-compatible Agents
```json
{
  "agent_type": "anthropic",
  "endpoint_url": "https://api.anthropic.com/v1/messages",
  "auth_type": "api_key",
  "auth_value": "your-anthropic-api-key"
}
```

### Custom Agents
```json
{
  "agent_type": "custom",
  "endpoint_url": "https://your-custom-agent.com/api",
  "auth_type": "bearer",
  "auth_value": "your-token",
  "capabilities": {"streaming": true, "functions": false},
  "config": {"max_tokens": 1000, "temperature": 0.7}
}
```

## Authentication Methods

| Auth Type | Description | Example |
|-----------|-------------|---------|
| `api_key` | API key in Authorization header | `Authorization: Bearer your-key` |
| `bearer` | Bearer token authentication | `Authorization: Bearer your-token` |
| `oauth` | OAuth 2.0 flow (stored tokens) | Handled automatically |
| `none` | No authentication required | - |

## Protocol Detection

The gateway automatically detects agent protocols:

- **JSONRPC Format**: For `agent_type: "jsonrpc"` or URLs ending with `/`
- **Custom A2A Format**: For other agent types

## Monitoring and Metrics

A2A agents provide comprehensive metrics:

- **Execution Count**: Total number of invocations
- **Success Rate**: Percentage of successful calls
- **Response Times**: Min/max/average response times
- **Last Interaction**: Timestamp of most recent call
- **Error Tracking**: Failed call details and error messages

## Virtual Server Integration

Associate A2A agents with virtual servers to:

- **Organize agents** by purpose or team
- **Control access** via server-specific endpoints
- **Group capabilities** for specific use cases
- **Enable MCP discovery** for client tools

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MCPGATEWAY_A2A_ENABLED` | Master toggle for A2A features | `true` |
| `MCPGATEWAY_A2A_MAX_AGENTS` | Maximum agents allowed | `100` |
| `MCPGATEWAY_A2A_DEFAULT_TIMEOUT` | HTTP timeout (seconds) | `30` |
| `MCPGATEWAY_A2A_MAX_RETRIES` | Retry attempts | `3` |
| `MCPGATEWAY_A2A_METRICS_ENABLED` | Enable metrics collection | `true` |

## Security Considerations

- **Encrypted Storage**: Agent credentials are encrypted in the database
- **Rate Limiting**: Configurable limits on agent invocations
- **Access Control**: Full authentication and authorization
- **Audit Logging**: All agent interactions are logged
- **Network Security**: HTTPS support and SSL verification

## Local Testing

### Demo A2A Agent

The repository includes a demo A2A agent with calculator and weather tools for local testing:

```bash
# Terminal 1: Start ContextForge
make dev

# Terminal 2: Start the demo agent (auto-registers with ContextForge)
uv run python scripts/demo_a2a_agent.py
```

The demo agent supports these query formats:

| Query | Example | Response |
|-------|---------|----------|
| Calculator | `calc: 7*8+2` | `58` |
| Weather | `weather: Dallas` | `The weather in Dallas is sunny, 25C` |

**Test via Admin UI:**

1. Go to `http://localhost:8000/admin`
2. Click the "A2A Agents" tab
3. Find "Demo Calculator Agent" and click **Test**
4. Enter a query like `calc: 100/4+25` in the modal
5. Click **Run Test** to see the result

**Test via API:**

```bash
# Get a token
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 --secret my-test-key)

# Invoke the agent
curl -X POST "http://localhost:8000/a2a/demo-calculator-agent/invoke" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "calc: 15*4+10"}'
```

### A2A SDK HelloWorld Sample

Test with the official A2A Python SDK sample:

```bash
# Clone and run the HelloWorld agent
git clone https://github.com/google/a2a-samples.git
cd a2a-samples/samples/python/agents/helloworld
uv run python __main__.py  # Starts on port 9999

# Register with ContextForge (in another terminal)
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 --secret my-test-key)

curl -X POST "http://localhost:8000/a2a" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": {
      "name": "Hello World Agent",
      "endpoint_url": "http://localhost:9999/",
      "agent_type": "jsonrpc",
      "description": "Official A2A SDK HelloWorld sample"
    },
    "visibility": "public"
  }'
```

### Admin UI Query Input

The Admin UI test button opens a modal where you can enter custom queries:

1. **Open Modal**: Click the blue **Test** button next to any A2A agent
2. **Enter Query**: Type your query in the textarea (e.g., `calc: 5*10+2`)
3. **Run Test**: Click **Run Test** to send the query to the agent
4. **View Response**: The agent's response appears in the modal

This allows testing A2A agents with real user queries instead of hardcoded test messages.

### Testing via MCP Tools

A2A agents are automatically exposed as MCP tools. After registration, invoke them via the MCP protocol:

```bash
curl -X POST "http://localhost:8000/rpc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "a2a_demo-calculator-agent",
      "arguments": {"query": "calc: 99+1"}
    },
    "id": 1
  }'
```

## Troubleshooting

### Agent Not Responding
1. Check agent status in Admin UI (should be "Active" and "Reachable")
2. Verify endpoint URL is correct and accessible
3. Test authentication credentials
4. Check agent logs for protocol format issues

### Protocol Format Issues
1. Verify agent expects JSONRPC format vs custom format
2. Check required fields in agent's API documentation
3. Use Admin UI test button to validate communication
4. Review gateway logs for request/response details

### Authentication Problems
1. Verify auth_type matches agent's expected authentication
2. Check auth_value is correct and not expired
3. Test direct agent communication outside gateway
4. Review agent's authentication documentation

---

For more information on MCP Gateway features and configuration, see the [main documentation](../../overview/index.md).
