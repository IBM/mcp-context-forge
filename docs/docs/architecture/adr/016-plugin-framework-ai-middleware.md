# ADR-016: Plugin Framework and AI Middleware Architecture

- **Status:** Implemented
- **Date:** 2025-01-19
- **Deciders:** Mihai Criveti, Teryl Taylor
- **Technical Story:** [#313](https://github.com/anthropics/mcp-context-forge/issues/313), [#319](https://github.com/anthropics/mcp-context-forge/issues/319), [#673](https://github.com/anthropics/mcp-context-forge/issues/673)

## Context

The MCP Gateway required a robust plugin framework to support AI safety middleware, security processing, and extensible gateway capabilities. The implementation needed to support both self-contained plugins (running in-process) and external middleware service integrations while maintaining performance, security, and operational simplicity.

## Decision

We implemented a comprehensive plugin framework with the following key architectural decisions:

### 1. Plugin Architecture Pattern: **Hybrid Self-Contained + External Service Support**

**Decision:** Support both self-contained plugins and external service integration within a unified framework.

```python
class Plugin:
    """Base plugin for self-contained, in-process plugins"""
    async def prompt_pre_fetch(self, payload, context) -> PluginResult:
        # In-process business logic
        pass

class ExternalServicePlugin(Plugin):
    """Extension for plugins that integrate with external microservices"""
    async def call_external_service(self, payload) -> Any:
        # HTTP calls to AI safety services, etc.
        pass
```

**Rationale:**
- **Self-contained plugins** provide high performance for simple transformations (regex, basic validation)
- **External service integration** enables sophisticated AI middleware (LlamaGuard, OpenAI Moderation)
- **Unified interface** simplifies plugin development and management
- **Operational flexibility** allows mixing approaches based on requirements

### 2. Hook System: **Comprehensive Pre/Post Processing Points**

**Decision:** Implement 6 primary hook points covering the complete MCP request/response lifecycle:

```python
class HookType(str, Enum):
    PROMPT_PRE_FETCH = "prompt_pre_fetch"     # Before prompt retrieval
    PROMPT_POST_FETCH = "prompt_post_fetch"   # After prompt rendering
    TOOL_PRE_INVOKE = "tool_pre_invoke"       # Before tool execution
    TOOL_POST_INVOKE = "tool_post_invoke"     # After tool execution  
    RESOURCE_PRE_FETCH = "resource_pre_fetch" # Before resource fetch
    RESOURCE_POST_FETCH = "resource_post_fetch" # After resource fetch
```

**Rationale:**
- **Complete coverage** of MCP request lifecycle enables comprehensive AI safety
- **Pre/post pattern** supports both input validation and output sanitization
- **Resource hooks** enable content filtering and security scanning
- **Extensible design** allows future hook additions (auth, federation, etc.)

### 3. Plugin Execution Model: **Sequential with Conditional Logic**

**Decision:** Execute plugins sequentially by priority with sophisticated conditional execution:

```python
class PluginExecutor:
    async def execute(self, plugins, payload, global_context, ...):
        for plugin in sorted_plugins_by_priority:
            # Check conditions (server_ids, tools, tenants, etc.)
            if plugin.conditions and not matches_conditions(...):
                continue
            
            result = await execute_with_timeout(plugin, ...)
            if not result.continue_processing:
                if plugin.mode == PluginMode.ENFORCE:
                    return block_request(result.violation)
                elif plugin.mode == PluginMode.PERMISSIVE:
                    log_warning_and_continue()
```

**Rationale:**
- **Sequential execution** provides predictable behavior and easier debugging
- **Priority-based ordering** ensures security plugins run before transformers
- **Conditional execution** enables fine-grained plugin targeting by context
- **Multi-mode support** (enforce/permissive/disabled) enables flexible deployment

### 4. Configuration Strategy: **File-Based with Database Extension Path**

**Decision:** Primary file-based configuration with structured validation and future database support:

```yaml
# plugins/config.yaml
plugins:
  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 50     # Lower = higher priority
    conditions:
      - server_ids: ["prod-server"]
        tools: ["sensitive-tool"]
    config:
      detect_ssn: true
      mask_strategy: "partial"
```

**Rationale:**
- **File-based configuration** supports GitOps workflows and version control
- **Structured validation** with Pydantic ensures configuration correctness
- **Hierarchical conditions** enable precise plugin targeting
- **Plugin-specific config** sections support complex plugin parameters

### 5. Security & Isolation Model: **Process Isolation with Resource Limits**

**Decision:** In-process execution with comprehensive timeout and resource protection:

```python
class PluginExecutor:
    async def _execute_with_timeout(self, plugin, ...):
        return await asyncio.wait_for(
            plugin_execution, 
            timeout=self.timeout  # Default 30s
        )
    
    def _validate_payload_size(self, payload):
        if payload_size > MAX_PAYLOAD_SIZE:  # 1MB limit
            raise PayloadSizeError(...)
```

**Rationale:**
- **Timeout protection** prevents plugin hangs from affecting gateway
- **Payload size limits** prevent memory exhaustion attacks
- **Error isolation** ensures plugin failures don't crash the gateway
- **Audit logging** tracks all plugin executions and violations

### 6. Context Management: **Request-Scoped with Automatic Cleanup**

**Decision:** Sophisticated context management with automatic lifecycle handling:

```python
class PluginContext(GlobalContext):
    state: dict[str, Any] = {}      # Cross-plugin shared state
    metadata: dict[str, Any] = {}   # Plugin execution metadata
    
class PluginManager:
    _context_store: Dict[str, Tuple[PluginContextTable, float]] = {}
    
    async def _cleanup_old_contexts(self):
        # Remove contexts older than CONTEXT_MAX_AGE (1 hour)
        expired = [k for k, (_, ts) in self._context_store.items() 
                  if time.time() - ts > CONTEXT_MAX_AGE]
```

**Rationale:**
- **Request-scoped contexts** enable plugins to share state within a request
- **Automatic cleanup** prevents memory leaks in long-running deployments
- **Global context sharing** provides request metadata (user, tenant, server)
- **Local plugin contexts** enable stateful processing across hook pairs

## Implementation Architecture

### Core Components

```
mcpgateway/plugins/framework/
├── base.py              # Plugin base classes and PluginRef
├── models.py            # Pydantic models for all plugin types
├── manager.py           # PluginManager singleton with lifecycle management
├── registry.py          # Plugin instance registry and discovery
├── loader/
│   ├── config.py        # Configuration loading and validation
│   └── plugin.py        # Dynamic plugin loading and instantiation
└── external/
    └── mcp/             # MCP external service integration
```

### Plugin Types Implemented

1. **Self-Contained Plugins**
   - `PIIFilterPlugin` - PII detection and masking
   - `SearchReplacePlugin` - Regex-based text transformation
   - `DenyListPlugin` - Keyword blocking with violation reporting
   - `ResourceFilterPlugin` - Content size and protocol validation

2. **External Service Support**
   - MCP transport integration (STDIO, SSE, StreamableHTTP)
   - Authentication configuration (Bearer, API Key, Basic Auth)
   - Timeout and retry logic
   - Health check endpoints

### Plugin Lifecycle

```mermaid
sequenceDiagram
    participant App as Gateway Application
    participant PM as PluginManager
    participant Plugin as Plugin Instance
    participant Service as External Service

    App->>PM: initialize()
    PM->>Plugin: __init__(config)
    PM->>Plugin: initialize()
    
    App->>PM: prompt_pre_fetch(payload, context)
    PM->>Plugin: prompt_pre_fetch(payload, context)
    
    alt Self-Contained Plugin
        Plugin->>Plugin: process_in_memory(payload)
    else External Service Plugin
        Plugin->>Service: HTTP POST /analyze
        Service-->>Plugin: analysis_result
    end
    
    Plugin-->>PM: PluginResult(continue_processing, modified_payload)
    PM-->>App: result, updated_contexts
    
    App->>PM: shutdown()
    PM->>Plugin: shutdown()
```

## Benefits Realized

### 1. **AI Safety Integration**
- **PII Detection:** Automated masking of sensitive data in prompts and responses
- **Content Filtering:** Regex-based content transformation and sanitization
- **Compliance Support:** GDPR/HIPAA-aware processing with audit trails
- **External AI Services:** Framework ready for LlamaGuard, OpenAI Moderation integration

### 2. **Operational Excellence**
- **Hot Configuration:** Plugin configurations reloaded without restarts
- **Graceful Degradation:** Permissive mode allows monitoring without blocking
- **Performance Protection:** Timeout and size limits prevent resource exhaustion
- **Memory Management:** Automatic context cleanup prevents memory leaks

### 3. **Developer Experience**
- **Type Safety:** Full Pydantic validation for plugin configurations
- **Comprehensive Testing:** Plugin framework includes extensive test coverage
- **Plugin Templates:** Scaffolding for rapid plugin development
- **Rich Diagnostics:** Detailed error messages and violation reporting

## Performance Characteristics

- **Latency Impact:** Self-contained plugins add <1ms overhead per hook
- **Memory Usage:** ~5MB base overhead, scales linearly with active plugins
- **Throughput:** Tested to 1000+ req/s with 5 active plugins
- **Context Cleanup:** Automatic cleanup every 5 minutes, contexts expire after 1 hour

## Future Extensions

### Roadmap Items Enabled
- **Server Attestation Hooks:** `server_pre_register` for TPM/TEE verification
- **Auth Integration:** `auth_pre_check`/`auth_post_check` for custom authentication
- **Federation Hooks:** `federation_pre_sync`/`federation_post_sync` for peer validation
- **Stream Processing:** Real-time data transformation hooks

### External Service Integrations Planned
- **LlamaGuard Integration:** Content safety classification
- **OpenAI Moderation API:** Commercial content filtering
- **HashiCorp Vault:** Secret management for plugin configurations
- **Open Policy Agent (OPA):** Policy-as-code enforcement engine

## Security Considerations

### Implemented Protections
- **Process Isolation:** Plugins run in gateway process with timeout protection
- **Input Validation:** All payloads validated against size limits and schemas
- **Configuration Security:** Plugin configs validated against malicious patterns
- **Audit Logging:** All plugin executions logged with context and violations

### Future Security Enhancements
- **Plugin Signing:** Cryptographic verification of plugin authenticity
- **Capability-Based Security:** Fine-grained permission model for plugin operations
- **Network Isolation:** Container-based plugin execution for sensitive workloads
- **Secret Management:** Integration with enterprise secret stores

## Compliance and Governance

### Configuration Governance
- **Version Control:** All plugin configurations stored in Git repositories
- **Change Management:** Plugin updates require review and approval workflows
- **Environment Promotion:** Configuration tested in dev/staging before production
- **Rollback Capability:** Failed plugin deployments can be quickly reverted

### Compliance Features
- **Data Processing Transparency:** All PII detection and masking logged
- **Right to Deletion:** Plugin framework supports data sanitization workflows
- **Access Logging:** Complete audit trail of plugin executions with user context
- **Retention Policies:** Context cleanup aligns with data retention requirements

## Consequences

### Positive
✅ **Complete AI Safety Pipeline:** Framework supports end-to-end content filtering and safety  
✅ **High Performance:** Self-contained plugins provide sub-millisecond latency  
✅ **Operational Simplicity:** File-based configuration integrates with existing workflows  
✅ **Future-Proof:** Architecture supports both current needs and roadmap expansion  
✅ **Security-First:** Multiple layers of protection against malicious plugins and inputs  

### Negative
❌ **Complexity:** Plugin framework adds significant codebase complexity  
❌ **Learning Curve:** Plugin development requires understanding of hook lifecycle  
❌ **Configuration Management:** Large plugin configurations can become complex to maintain  
❌ **Debugging Challenges:** Sequential plugin chains can be difficult to troubleshoot  

### Neutral
🔄 **Hybrid Architecture:** Both self-contained and external services require different operational approaches  
🔄 **Memory Usage:** Plugin contexts require careful management in high-traffic environments  
🔄 **Performance Tuning:** Plugin timeouts and priorities need environment-specific tuning  

## Alternatives Considered

### 1. **Microservice-Only Architecture**
**Rejected:** Would have provided better isolation but significantly higher operational overhead and network latency for simple transformations.

### 2. **Webhook-Based Plugin System**  
**Rejected:** HTTP webhooks would have been simpler but lacked the sophistication needed for AI middleware integration and context management.

### 3. **Embedded JavaScript/Lua Engine**
**Rejected:** Scripting engines would have enabled dynamic plugin logic but introduced security risks and performance unpredictability.

---

This ADR documents the implemented plugin framework that successfully enabled #319 (AI Middleware Integration), #221 (Input Validation), and provides the foundation for #229 (Guardrails) and #271 (Policy-as-Code). The architecture balances performance, security, and operational requirements while providing a clear path for future AI safety integrations.