# OpenTelemetry Span Attributes in ContextForge

This document lists all span attributes created in the ContextForge codebase, organized by category with real-world code-level examples.

## **CUSTOMIZING SPAN ATTRIBUTES**

ContextForge provides the **SpanAttributeCustomizer** plugin to customize OpenTelemetry span attributes at runtime. This allows you to:

- **Add global attributes** to all spans (e.g., environment, region, team)
- **Override attributes per tool** for specific tools
- **Transform attribute values** (hash for PII, uppercase, lowercase, truncate)
- **Add conditional attributes** based on tool name or context
- **Remove sensitive attributes** for privacy/compliance

### Setup

1. Enable the plugin in `plugins/config.yaml`:

```yaml
plugins:
  - name: "SpanAttributeCustomizer"
    kind: "plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch"]
    mode: "permissive"
    priority: 10
    config:
      global_attributes:
        environment: "production"
        region: "us-east-1"
        team: "platform"
      tool_overrides:
        weather_api:
          attributes:
            service: "weather"
            cost_center: "engineering"
      transformations:
        - field: "user.email"
          operation: "hash"
      conditions:
        - when: "tool.name == \"sensitive_operation\""
          add:
            audit_required: true
            compliance_level: "high"
      remove_attributes:
        - "internal_debug_info"
```

2. Enable plugins in `.env`:

```bash
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

3. Restart the gateway

For detailed configuration options, see `plugins/span_attribute_customizer/README.md`.

---

## **TOOL INVOCATION ATTRIBUTES**

### Core Tool Attributes

| Attribute               | Example Value                            | Description                        |
| ----------------------- | ---------------------------------------- | ---------------------------------- |
| `tool.name`             | `"get_weather"`                          | Tool name being invoked            |
| `tool.id`               | `"550e8400-e29b-41d4-a716-446655440000"` | UUID of the tool                   |
| `tool.integration_type` | `"MCP"`, `"REST"`, `"A2A"`               | Integration type                   |
| `tool.gateway_id`       | `"7c9e6679-7425-40de-944b-e07fc1f90ae7"` | Gateway UUID if federated          |
| `arguments_count`       | `3`                                      | Number of arguments passed         |
| `has_headers`           | `true`                                   | Whether headers were provided      |
| `success`               | `true`                                   | Whether invocation succeeded       |
| `duration.ms`           | `245.67`                                 | Execution duration in milliseconds |

### Tool Lookup Attributes

| Attribute               | Example Value     | Description          |
| ----------------------- | ----------------- | -------------------- |
| `tool.name`             | `"calculate_sum"` | Tool being looked up |
| `tool.id`               | `"abc-123-def"`   | Tool identifier      |
| `tool.integration_type` | `"REST"`          | Integration type     |

### Tool Gateway Call Attributes

| Attribute               | Example Value              | Description      |
| ----------------------- | -------------------------- | ---------------- |
| `tool.name`             | `"fetch_data"`             | Tool name        |
| `tool.id`               | `"tool-uuid-123"`          | Tool UUID        |
| `tool.integration_type` | `"REST"`, `"MCP"`, `"A2A"` | Integration type |

### Tool Post-Process Attributes

| Attribute   | Example Value      | Description |
| ----------- | ------------------ | ----------- |
| `tool.name` | `"process_result"` | Tool name   |
| `tool.id`   | `"uuid-456"`       | Tool UUID   |

---

## **MCP CLIENT ATTRIBUTES**

### MCP Client Call Attributes

| Attribute                 | Example Value                        | Description            |
| ------------------------- | ------------------------------------ | ---------------------- |
| `mcp.tool.name`           | `"echo_text"`                        | Original MCP tool name |
| `contextforge.tool.id`    | `"tool-789"`                         | ContextForge tool ID   |
| `contextforge.gateway_id` | `"gateway-abc"`                      | Gateway identifier     |
| `contextforge.runtime`    | `"python"`                           | Runtime environment    |
| `contextforge.transport`  | `"sse"`, `"streamablehttp"`          | MCP transport type     |
| `network.protocol.name`   | `"mcp"`                              | Protocol name          |
| `server.address`          | `"mcp.example.com"`                  | Server hostname        |
| `server.port`             | `8080`                               | Server port            |
| `url.path`                | `"/mcp"`                             | URL path               |
| `url.full`                | `"https://mcp.example.com:8080/mcp"` | Full sanitized URL     |

### MCP Client Initialize Attributes

| Attribute                | Example Value               | Description         |
| ------------------------ | --------------------------- | ------------------- |
| `contextforge.transport` | `"sse"`, `"streamablehttp"` | Transport type      |
| `contextforge.runtime`   | `"python"`                  | Runtime environment |

### MCP Client Request Attributes

| Attribute                 | Example Value    | Description     |
| ------------------------- | ---------------- | --------------- |
| `mcp.tool.name`           | `"get_time"`     | MCP tool name   |
| `contextforge.tool.id`    | `"time-tool-id"` | Tool identifier |
| `contextforge.gateway_id` | `"gw-123"`       | Gateway ID      |
| `contextforge.runtime`    | `"python"`       | Runtime         |

### MCP Client Response Attributes

| Attribute                   | Example Value    | Description                |
| --------------------------- | ---------------- | -------------------------- |
| `mcp.tool.name`             | `"get_time"`     | Tool name                  |
| `contextforge.tool.id`      | `"time-tool-id"` | Tool ID                    |
| `contextforge.gateway_id`   | `"gw-123"`       | Gateway ID                 |
| `contextforge.runtime`      | `"python"`       | Runtime                    |
| `upstream.response.success` | `true`           | Whether upstream succeeded |

---

## **PLUGIN FRAMEWORK ATTRIBUTES**

### Plugin Chain Attributes

| Attribute                 | Example Value      | Description                |
| ------------------------- | ------------------ | -------------------------- |
| `plugin.chain.stopped`    | `true`             | Whether chain was stopped  |
| `plugin.chain.stopped_by` | `"DenyListPlugin"` | Plugin that stopped chain  |
| `plugin.executed_count`   | `5`                | Number of plugins executed |
| `plugin.skipped_count`    | `2`                | Number of plugins skipped  |

### Plugin Execution Attributes

| Attribute                    | Example Value | Description                     |
| ---------------------------- | ------------- | ------------------------------- |
| `plugin.had_violation`       | `true`        | Whether plugin raised violation |
| `plugin.modified_payload`    | `true`        | Whether payload was modified    |
| `plugin.continue_processing` | `false`       | Whether to continue processing  |
| `plugin.stopped_chain`       | `true`        | Whether plugin stopped chain    |

### Plugin Hook Attributes

| Attribute            | Example Value              | Description                        |
| -------------------- | -------------------------- | ---------------------------------- |
| `plugin.hook.invoke` | `"plugin.hook.invoke"`     | Plugin hook invocation marker      |
| `plugin.hook.type`   | `"TOOL_PRE_INVOKE"`        | Type of hook being executed        |
| `plugin.name`        | `"RetryWithBackoffPlugin"` | Name of the plugin                 |
| `plugin.mode`        | `"enforce"`                | Plugin execution mode              |
| `plugin.priority`    | `100`                      | Plugin priority (lower runs first) |

---

## **PROMPT ATTRIBUTES**

### Prompt Render Attributes

| Attribute                             | Example Value         | Description                        |
| ------------------------------------- | --------------------- | ---------------------------------- |
| `prompt.id`                           | `"prompt-123"`        | Prompt identifier                  |
| `arguments_count`                     | `2`                   | Number of arguments provided       |
| `user`                                | `"user@example.com"`  | User rendering the prompt          |
| `server_id`                           | `"virtual-server-1"`  | Virtual server ID                  |
| `tenant_id`                           | `"tenant-abc"`        | Tenant identifier                  |
| `request_id`                          | `"req-xyz-789"`       | Request identifier                 |
| `success`                             | `true`                | Whether rendering succeeded        |
| `duration.ms`                         | `123.45`              | Rendering duration in milliseconds |
| `langfuse.observation.prompt.name`    | `"greeting_template"` | Prompt name for Langfuse           |
| `langfuse.observation.prompt.version` | `3`                   | Prompt version number              |
| `messages.count`                      | `5`                   | Number of messages in result       |

---

## **RESOURCE ATTRIBUTES**

### Resource Invocation Attributes

| Attribute           | Example Value                   | Description            |
| ------------------- | ------------------------------- | ---------------------- |
| `resource.name`     | `"config_file"`                 | Resource name          |
| `resource.id`       | `"res-456"`                     | Resource identifier    |
| `resource.uri`      | `"file:///config.json"`         | Resource URI           |
| `gateway.transport` | `"sse"`                         | Gateway transport type |
| `gateway.url`       | `"https://gateway.example.com"` | Gateway URL            |

### Resource Read Attributes

| Attribute       | Example Value                    | Description               |
| --------------- | -------------------------------- | ------------------------- |
| `resource.uri`  | `"https://api.example.com/data"` | Resource URI being read   |
| `user`          | `"user@example.com"`             | User reading the resource |
| `server_id`     | `"virtual-server-1"`             | Virtual server ID         |
| `request_id`    | `"req-abc-123"`                  | Request identifier        |
| `http.url`      | `"https://api.example.com/data"` | HTTP URL (if applicable)  |
| `resource.type` | `"template"`, `"static"`         | Resource type             |

### Resource Get Attributes

| Attribute          | Example Value | Description                           |
| ------------------ | ------------- | ------------------------------------- |
| `resource.id`      | `"res-789"`   | Resource identifier                   |
| `include_inactive` | `false`       | Whether to include inactive resources |

---

## **GATEWAY ATTRIBUTES**

### Gateway Health Check Attributes

| Attribute           | Example Value | Description                              |
| ------------------- | ------------- | ---------------------------------------- |
| `gateway.count`     | `15`          | Number of gateways being checked         |
| `check.type`        | `"health"`    | Type of check being performed            |
| `check.duration_ms` | `2345`        | Duration of health check in milliseconds |
| `check.completed`   | `true`        | Whether check completed successfully     |

---

## **A2A (AGENT-TO-AGENT) ATTRIBUTES**

### A2A Invocation Attributes

| Attribute              | Example Value                     | Description                    |
| ---------------------- | --------------------------------- | ------------------------------ |
| `a2a.agent.name`       | `"WeatherAgent"`                  | Agent name                     |
| `a2a.agent.id`         | `"agent-123"`                     | Agent identifier               |
| `a2a.agent.url`        | `"https://agent.example.com/api"` | Agent endpoint URL (sanitized) |
| `a2a.agent.type`       | `"jsonrpc"`, `"generic"`          | Agent type                     |
| `a2a.interaction_type` | `"query"`, `"command"`            | Type of interaction            |

---

## **LLM PROXY ATTRIBUTES**

### LLM Request Attributes

| Attribute                   | Example Value             | Description                   |
| --------------------------- | ------------------------- | ----------------------------- |
| `langfuse.observation.type` | `"generation"`            | Observation type for Langfuse |
| `gen_ai.system`             | `"openai"`, `"anthropic"` | AI system/provider            |
| `gen_ai.request.model`      | `"gpt-4"`                 | Model being requested         |
| `gen_ai.response.model`     | `"gpt-4-0613"`            | Actual model that responded   |
| `llm.provider.id`           | `"provider-456"`          | LLM provider identifier       |
| `llm.provider.type`         | `"openai"`                | Provider type                 |
| `llm.model.id`              | `"model-789"`             | Model identifier              |
| `llm.stream`                | `true`                    | Whether streaming is enabled  |

### LLM Usage Attributes

| Attribute                    | Example Value | Description             |
| ---------------------------- | ------------- | ----------------------- |
| `gen_ai.usage.input_tokens`  | `150`         | Number of input tokens  |
| `gen_ai.usage.output_tokens` | `75`          | Number of output tokens |
| `gen_ai.usage.total_tokens`  | `225`         | Total tokens used       |

---

## **ROOT SERVICE ATTRIBUTES**

### Root List Attributes

| Attribute    | Example Value | Description            |
| ------------ | ------------- | ---------------------- |
| `root.count` | `3`           | Number of root entries |

---

## **USER & TEAM CONTEXT ATTRIBUTES**

### Identity Attributes

| Attribute       | Example Value                 | Description                  |
| --------------- | ----------------------------- | ---------------------------- |
| `user.email`    | `"user@example.com"`          | User email address           |
| `user.is_admin` | `true`                        | Whether user is admin        |
| `team.scope`    | `"team1,team2"` or `"public"` | Team scope (comma-separated) |
| `team.name`     | `"Engineering"`               | Team name                    |

### Authentication Attributes

| Attribute     | Example Value                 | Description                |
| ------------- | ----------------------------- | -------------------------- |
| `auth.method` | `"jwt"`, `"oauth"`, `"basic"` | Authentication method used |

---

## **LANGFUSE-SPECIFIC ATTRIBUTES**

### Langfuse Identity Attributes

| Attribute              | Example Value               | Description              |
| ---------------------- | --------------------------- | ------------------------ |
| `langfuse.user.id`     | `"user@example.com"`        | Langfuse user identifier |
| `langfuse.session.id`  | `"session-abc-123"`         | Session identifier       |
| `langfuse.environment` | `"production"`, `"staging"` | Deployment environment   |

### Langfuse Trace Attributes

| Attribute                             | Example Value                            | Description               |
| ------------------------------------- | ---------------------------------------- | ------------------------- |
| `langfuse.trace.tags`                 | `["team:engineering", "env:production"]` | Trace tags array          |
| `langfuse.trace.name`                 | `"Tool: get_weather"`                    | Human-readable trace name |
| `langfuse.observation.level`          | `"DEFAULT"`, `"ERROR"`                   | Observation level         |
| `langfuse.observation.status_message` | `"Request completed successfully"`       | Status message            |

### Langfuse Input/Output Attributes

| Attribute                     | Example Value                                 | Description               |
| ----------------------------- | --------------------------------------------- | ------------------------- |
| `langfuse.observation.input`  | `{"city": "London", "units": "metric"}`       | Serialized input payload  |
| `langfuse.observation.output` | `{"temperature": 15, "conditions": "cloudy"}` | Serialized output payload |

---

## **REQUEST CONTEXT ATTRIBUTES**

### Correlation & Request Attributes

| Attribute        | Example Value           | Description                                 |
| ---------------- | ----------------------- | ------------------------------------------- |
| `correlation_id` | `"req-abc-123-def-456"` | Request correlation ID                      |
| `request_id`     | `"req-abc-123-def-456"` | Request identifier (same as correlation_id) |
| `server_id`      | `"virtual-server-1"`    | Virtual server ID                           |
| `tenant_id`      | `"tenant-xyz"`          | Tenant identifier                           |

### Baggage Attributes

| Attribute       | Example Value               | Description                |
| --------------- | --------------------------- | -------------------------- |
| `baggage.{key}` | `baggage.trace_id="abc123"` | Baggage entries (prefixed) |

---

## **HTTP REQUEST ATTRIBUTES** (ObservabilityMiddleware)

### HTTP Request Attributes

| Attribute                  | Example Value                                 | Description                |
| -------------------------- | --------------------------------------------- | -------------------------- |
| `http.request.method`      | `"POST"`                                      | HTTP method                |
| `http.route`               | `"/tools/invoke"`                             | Route path                 |
| `url.path`                 | `"/tools/invoke"`                             | URL path                   |
| `url.query`                | `"filter=active&limit=10"`                    | Sanitized query string     |
| `network.protocol.version` | `"1.1"`                                       | HTTP version               |
| `server.address`           | `"api.example.com"`                           | Server address             |
| `server.port`              | `443`                                         | Server port                |
| `client.address`           | `"192.168.1.100"`                             | Client IP address          |
| `client.port`              | `54321`                                       | Client port                |
| `user_agent.original`      | `"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"` | User agent string          |
| `correlation_id`           | `"req-xyz-789"`                               | Correlation ID from header |

### HTTP Response Attributes

| Attribute                   | Example Value | Description         |
| --------------------------- | ------------- | ------------------- |
| `http.response.status_code` | `200`         | HTTP status code    |
| `http.status_code`          | `200`         | HTTP status (alias) |

---

## **ERROR ATTRIBUTES**

### Error Attributes

| Attribute       | Example Value               | Description               |
| --------------- | --------------------------- | ------------------------- |
| `error`         | `true`                      | Whether an error occurred |
| `error.type`    | `"ValueError"`              | Exception class name      |
| `error.message` | `"Invalid input parameter"` | Sanitized error message   |

---

## **SUMMARY BY CATEGORY**

### Tool Invocation (12 attributes)

- Core: `tool.name`, `tool.id`, `tool.integration_type`, `tool.gateway_id`, `arguments_count`, `has_headers`, `success`, `duration.ms`
- Lookup: `tool.name`, `tool.id`, `tool.integration_type`
- Gateway Call: `tool.name`, `tool.id`, `tool.integration_type`

### MCP Protocol (15 attributes)

- Call: `mcp.tool.name`, `contextforge.tool.id`, `contextforge.gateway_id`, `contextforge.runtime`, `contextforge.transport`, `network.protocol.name`, `server.address`, `server.port`, `url.path`, `url.full`
- Initialize: `contextforge.transport`, `contextforge.runtime`
- Request: `mcp.tool.name`, `contextforge.tool.id`, `contextforge.gateway_id`, `contextforge.runtime`
- Response: `mcp.tool.name`, `contextforge.tool.id`, `contextforge.gateway_id`, `contextforge.runtime`, `upstream.response.success`

### Plugin Framework (13 attributes)

- Chain: `plugin.chain.stopped`, `plugin.chain.stopped_by`, `plugin.executed_count`, `plugin.skipped_count`
- Execution: `plugin.had_violation`, `plugin.modified_payload`, `plugin.continue_processing`, `plugin.stopped_chain`
- Hook: `plugin.hook.invoke`, `plugin.hook.type`, `plugin.name`, `plugin.mode`, `plugin.priority`

### Prompt (11 attributes)

- `prompt.id`, `arguments_count`, `user`, `server_id`, `tenant_id`, `request_id`, `success`, `duration.ms`, `langfuse.observation.prompt.name`, `langfuse.observation.prompt.version`, `messages.count`

### Resource (11 attributes)

- Invocation: `resource.name`, `resource.id`, `resource.uri`, `gateway.transport`, `gateway.url`
- Read: `resource.uri`, `user`, `server_id`, `request_id`, `http.url`, `resource.type`
- Get: `resource.id`, `include_inactive`

### Gateway (4 attributes)

- `gateway.count`, `check.type`, `check.duration_ms`, `check.completed`

### A2A (5 attributes)

- `a2a.agent.name`, `a2a.agent.id`, `a2a.agent.url`, `a2a.agent.type`, `a2a.interaction_type`

### LLM Proxy (11 attributes)

- Request: `langfuse.observation.type`, `gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`, `llm.provider.id`, `llm.provider.type`, `llm.model.id`, `llm.stream`
- Usage: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`

### Root Service (1 attribute)

- `root.count`

### User & Team Context (5 attributes)

- Identity: `user.email`, `user.is_admin`, `team.scope`, `team.name`
- Auth: `auth.method` <!-- pragma: allowlist secret -->

### Langfuse Integration (9 attributes)

- Identity: `langfuse.user.id`, `langfuse.session.id`, `langfuse.environment`
- Trace: `langfuse.trace.tags`, `langfuse.trace.name`, `langfuse.observation.level`, `langfuse.observation.status_message` <!-- pragma: allowlist secret -->
- I/O: `langfuse.observation.input`, `langfuse.observation.output` <!-- pragma: allowlist secret -->

### Request Context (5 attributes)

- `correlation_id`, `request_id`, `server_id`, `tenant_id`, `baggage.{key}`

### HTTP (11 attributes)

- Request: `http.request.method`, `http.route`, `url.path`, `url.query`, `network.protocol.version`, `server.address`, `server.port`, `client.address`, `client.port`, `user_agent.original`, `correlation_id`
- Response: `http.response.status_code`, `http.status_code`

### Error Handling (3 attributes)

- `error`, `error.type`, `error.message`

**Total: 116 unique span attributes across all categories**
