# MCP Security Hooks

This document details the security-focused hook points in the MCP Gateway Plugin Framework, covering the complete MCP protocol request/response lifecycle.

## MCP Security Hook Functions

Legend: ✅ = Completed | 🚧 = In Progress | 📋 = Planned

The framework provides eight primary hook points covering the complete MCP request/response lifecycle:

| Hook Function | Description | When It Executes | Primary Use Cases | Status |
|---------------|-------------|-------------------|-------------------|--------|
| [`http_pre_forwarding_call()`](#http-pre-forwarding-hook) | Process HTTP headers before forwarding requests to tools/gateways | Before HTTP calls are made to external services | Authentication token injection, request labeling, session management, header validation | 🚧 |
| [`http_post_forwarding_call()`](#http-post-forwarding-hook) | Process HTTP headers after forwarding requests to tools/gateways | After HTTP responses are received from external services | Response header validation, data flow labeling, session tracking, compliance metadata | 🚧 |
| [`prompt_post_list()`](#) | Process a `prompts/list` request before the results are returned to the client. | After a `prompts/list` is returned from the server | Detection or [poisoning](#) threats. | 📋 |
| [`prompt_pre_fetch()`](#prompt-pre-fetch-hook) | Process prompt requests before template retrieval and rendering | Before prompt template is loaded and processed | Input validation, argument sanitization, access control, PII detection | ✅ |
| [`prompt_post_fetch()`](#prompt-post-fetch-hook) | Process prompt responses after template rendering into messages | After prompt template is rendered into final messages | Output filtering, content transformation, response validation, compliance checks | ✅ |
| [`tools_post_list()`](#) | Process a `tools/list` request before the results are returned to the client. | After a `tools/list` is returned from the server | Detection or [poisoning](#) threats. | 📋 |
| [`tool_pre_invoke()`](#tool-pre-invoke-hook) | Process tool calls before execution | Before tool is invoked with arguments | Parameter validation, security checks, rate limiting, access control, argument transformation | ✅ |
| [`tool_post_invoke()`](#tool-post-invoke-hook) | Process tool results after execution completes | After tool has finished processing and returned results | Result filtering, output validation, sensitive data redaction, response enhancement | ✅ |
| [`resource_post_list()`](#) | Process a `resources/list` request before the results are returned to the client. | After a `resources/list` is returned from the server | Detection or [poisoning](#) threats. | 📋 |
| [`resource_pre_fetch()`](#resource-pre-fetch-hook) | Process resource requests before fetching content | Before resource is retrieved from URI | URI validation, protocol restrictions, domain filtering, access control, request enhancement | ✅ |
| [`resource_post_fetch()`](#resource-post-fetch-hook) | Process resource content after successful retrieval | After resource content has been fetched and loaded | Content validation, size limits, content filtering, data transformation, format conversion | ✅ |
| [`roots_post_list()`](#) | Process a `roots/list` request before the results are returned to the client. | After a `roots/list` is returned from the server | Detection or [poisoning](#) threats. | 📋 |
| [`elicit_pre_create()`](#) | Process elicitation requests from MCP servers before sending to users | Before the elicitation request is sent to the MCP client | Access control, rerouting and processing elicitation requests | 📋 |
| [`elicit_post_response()`](#) | Process user responses to elicitation requests | After the elicitation response is returned by the client but before it is sent to the MCP server | Input sanitization, access control, PII and and DLP | 📋 |
| [`sampling_pre_create()`](#) | Process sampling requests sent to MCP host LLMs | Before the sampling request is returned to the MCP client | Prompt injection, goal manipulation, denial of wallet | 📋 |
| [`sampling_post_complete()`](#) | Process sampling requests returned from the LLM | Before returning the LLM response to the MCP server | Sensitive information leakage, prompt injection, tool poisoning, PII detection | 📋 |

## MCP Security Hook Reference

Each hook has specific function signatures, payloads, and use cases detailed below:

### HTTP Pre-Forwarding Hook

**Function Signature**: `async def http_pre_forwarding_call(self, payload: HttpHeaderPayload, context: PluginContext) -> HttpHeaderPayloadResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Payload** | `HttpHeaderPayload` | Dictionary of HTTP headers to be processed |
| **Context** | `PluginContext` | Plugin execution context with request metadata |
| **Return** | `HttpHeaderPayloadResult` | Modified headers and processing status |

**Payload Structure**: `HttpHeaderPayload` (dictionary of headers)
```python
# Example payload
headers = HttpHeaderPayload({
    "Authorization": "Bearer token123",
    "Content-Type": "application/json",
    "User-Agent": "MCP-Gateway/1.0",
    "X-Request-ID": "req-456"
})
```

**Common Use Cases and Examples**:

| Use Case | Example Implementation | Business Value |
|----------|----------------------|----------------|
| **Authentication Token Injection** | Add OAuth tokens or API keys to outbound requests | Secure service-to-service communication |
| **Request Data Labeling** | Add classification headers (`X-Data-Classification: sensitive`) | Compliance and data governance tracking |
| **Session Management** | Inject session tokens (`X-Session-ID: session123`) | Stateful request tracking across services |
| **Header Validation** | Block requests with malicious headers | Security and input validation |
| **Rate Limiting Headers** | Add rate limiting metadata (`X-Rate-Limit-Remaining: 100`) | API usage management |

```python
# Example: Authentication token injection plugin
async def http_pre_forwarding_call(self, payload: HttpHeaderPayload, context: PluginContext) -> HttpHeaderPayloadResult:
    # Inject authentication token based on user context
    modified_headers = dict(payload.root)

    if context.global_context.user:
        token = await self.get_user_token(context.global_context.user)
        modified_headers["Authorization"] = f"Bearer {token}"

    # Add data classification label
    modified_headers["X-Data-Classification"] = "internal"

    return HttpHeaderPayloadResult(
        continue_processing=True,
        modified_payload=HttpHeaderPayload(modified_headers),
        metadata={"plugin": "auth_injector", "action": "token_added"}
    )
```

### HTTP Post-Forwarding Hook

**Function Signature**: `async def http_post_forwarding_call(self, payload: HttpHeaderPayload, context: PluginContext) -> HttpHeaderPayloadResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Payload** | `HttpHeaderPayload` | Dictionary of HTTP headers from response |
| **Context** | `PluginContext` | Plugin execution context with request metadata |
| **Return** | `HttpHeaderPayloadResult` | Modified headers and processing status |

**Payload Structure**: `HttpHeaderPayload` (dictionary of response headers)
```python
# Example payload (response headers)
headers = HttpHeaderPayload({
    "Content-Type": "application/json",
    "X-Rate-Limit-Remaining": "99",
    "X-Response-Time": "150ms",
    "Cache-Control": "no-cache"
})
```

**Common Use Cases and Examples**:

| Use Case | Example Implementation | Business Value |
|----------|----------------------|----------------|
| **Response Header Validation** | Validate security headers are present | Ensure proper security controls |
| **Session Tracking** | Extract and store session state from response | Maintain stateful interactions |
| **Compliance Metadata** | Add audit headers (`X-Audit-ID: audit123`) | Regulatory compliance tracking |
| **Performance Monitoring** | Extract timing headers for metrics | Operational observability |
| **Data Flow Labeling** | Tag responses with data handling instructions | Data governance and compliance |

```python
# Example: Compliance metadata plugin
async def http_post_forwarding_call(self, payload: HttpHeaderPayload, context: PluginContext) -> HttpHeaderPayloadResult:
    modified_headers = dict(payload.root)

    # Add compliance audit trail
    modified_headers["X-Audit-Trail"] = f"processed-by-{context.global_context.request_id}"
    modified_headers["X-Processing-Timestamp"] = datetime.utcnow().isoformat()

    # Validate required security headers are present
    required_headers = ["Content-Security-Policy", "X-Frame-Options"]
    missing_headers = [h for h in required_headers if h not in payload.root]

    if missing_headers:
        return HttpHeaderPayloadResult(
            continue_processing=False,
            violation=PluginViolation(
                code="MISSING_SECURITY_HEADERS",
                reason="Required security headers missing",
                description=f"Missing headers: {missing_headers}"
            )
        )

    return HttpHeaderPayloadResult(
        continue_processing=True,
        modified_payload=HttpHeaderPayload(modified_headers),
        metadata={"plugin": "compliance_validator", "audit_added": True}
    )
```

### Prompt Pre-Fetch Hook

**Function Signature**: `async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `prompt_pre_fetch` | Hook identifier for configuration |
| **Execution Point** | Before prompt template retrieval and rendering | When MCP client requests a prompt template |
| **Purpose** | Input validation, access control, argument sanitization | Analyze and transform prompt requests before processing |

**Payload Attributes (`PromptPrehookPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `name` | `str` | Yes | Name of the prompt template being requested | `"greeting_prompt"` |
| `args` | `dict[str, str]` |  | Template arguments/parameters | `{"user": "Alice", "context": "morning"}` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Return Type (`PromptPrehookResult`)**:
- Extends `PluginResult[PromptPrehookPayload]`
- Can modify `payload.args` before template processing
- Can block request with violation

**Example Use Cases**:
```python
# 1. Input validation and sanitization
async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
    # Validate prompt arguments
    if "user_input" in payload.args:
        if len(payload.args["user_input"]) > MAX_INPUT_LENGTH:
            violation = PluginViolation(
                reason="Input too long",
                description=f"Input exceeds {MAX_INPUT_LENGTH} characters",
                code="INPUT_TOO_LONG"
            )
            return PromptPrehookResult(continue_processing=False, violation=violation)

    # Sanitize HTML/script content
    sanitized_args = {}
    for key, value in payload.args.items():
        sanitized_args[key] = html.escape(value)

    modified_payload = PromptPrehookPayload(name=payload.name, args=sanitized_args)
    return PromptPrehookResult(modified_payload=modified_payload)

# 2. Access control and authorization
async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
    # Check if user has permission to access this prompt
    user_id = context.global_context.user
    if not self._has_prompt_permission(user_id, payload.name):
        violation = PluginViolation(
            reason="Unauthorized prompt access",
            description=f"User {user_id} cannot access prompt {payload.name}",
            code="UNAUTHORIZED_PROMPT_ACCESS"
        )
        return PromptPrehookResult(continue_processing=False, violation=violation)

    return PromptPrehookResult()

# 3. PII detection and masking
async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
    modified_args = {}
    pii_detected = False

    for key, value in payload.args.items():
        # Detect and mask PII in prompt arguments
        masked_value, detected = self._mask_pii(value)
        modified_args[key] = masked_value
        if detected:
            pii_detected = True

    if pii_detected:
        context.metadata["pii_masked"] = True
        modified_payload = PromptPrehookPayload(name=payload.name, args=modified_args)
        return PromptPrehookResult(modified_payload=modified_payload)

    return PromptPrehookResult()
```

### Prompt Post-Fetch Hook

**Function Signature**: `async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `prompt_post_fetch` | Hook identifier for configuration |
| **Execution Point** | After prompt template is rendered into messages | When prompt template processing is complete |
| **Purpose** | Output filtering, content transformation, response validation | Process and validate rendered prompt content |

**Payload Attributes (`PromptPosthookPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `name` | `str` | Yes | Name of the prompt template | `"greeting_prompt"` |
| `result` | `PromptResult` | Yes | Rendered prompt result containing messages | `PromptResult(messages=[Message(...)])` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**PromptResult Structure**:
- `messages`: `list[Message]` - Rendered prompt messages
- Each `Message` has `role`, `content`, and optional metadata

**Return Type (`PromptPosthookResult`)**:
- Extends `PluginResult[PromptPosthookPayload]`
- Can modify `payload.result.messages` content
- Can block response with violation

**Example Use Cases**:
```python
# 1. Content filtering and safety
async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
    for message in payload.result.messages:
        if hasattr(message.content, 'text'):
            # Check for inappropriate content
            if self._contains_inappropriate_content(message.content.text):
                violation = PluginViolation(
                    reason="Inappropriate content detected",
                    description="Rendered prompt contains blocked content",
                    code="INAPPROPRIATE_CONTENT"
                )
                return PromptPosthookResult(continue_processing=False, violation=violation)

    return PromptPosthookResult()

# 2. Content transformation and enhancement
async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
    modified = False

    for message in payload.result.messages:
        if hasattr(message.content, 'text'):
            # Add context or modify content
            enhanced_text = self._add_context_information(message.content.text)
            if enhanced_text != message.content.text:
                message.content.text = enhanced_text
                modified = True

    if modified:
        return PromptPosthookResult(modified_payload=payload)

    return PromptPosthookResult()

# 3. Output validation and compliance
async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
    # Validate prompt output meets compliance requirements
    total_content_length = sum(
        len(msg.content.text) for msg in payload.result.messages
        if hasattr(msg.content, 'text')
    )

    if total_content_length > MAX_PROMPT_LENGTH:
        violation = PluginViolation(
            reason="Prompt too long",
            description=f"Rendered prompt exceeds {MAX_PROMPT_LENGTH} characters",
            code="PROMPT_TOO_LONG"
        )
        return PromptPosthookResult(continue_processing=False, violation=violation)

    context.metadata["prompt_validation"] = {"length": total_content_length}
    return PromptPosthookResult()
```

### Tool Pre-Invoke Hook

**Function Signature**: `async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `tool_pre_invoke` | Hook identifier for configuration |
| **Execution Point** | Before tool execution | When MCP client requests tool invocation |
| **Purpose** | Parameter validation, access control, argument transformation | Analyze and secure tool calls before execution |

**Payload Attributes (`ToolPreInvokePayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `name` | `str` | Yes | Name of the tool being invoked | `"file_reader"` |
| `args` | `dict[str, Any]` |  | Tool arguments/parameters | `{"path": "/etc/passwd", "encoding": "utf-8"}` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Return Type (`ToolPreInvokeResult`)**:
- Extends `PluginResult[ToolPreInvokePayload]`
- Can modify `payload.args` and `payload.headers`
- Can block tool execution with violation

**Example Use Cases**:
```python
# 1. Path traversal protection
async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
    if payload.name == "file_reader" and "path" in payload.args:
        file_path = payload.args["path"]

        # Prevent path traversal attacks
        if ".." in file_path or file_path.startswith("/"):
            violation = PluginViolation(
                reason="Unsafe file path",
                description=f"Path traversal attempt detected: {file_path}",
                code="PATH_TRAVERSAL_BLOCKED"
            )
            return ToolPreInvokeResult(continue_processing=False, violation=violation)

        # Normalize and sanitize path
        safe_path = os.path.normpath(file_path)
        payload.args["path"] = safe_path
        return ToolPreInvokeResult(modified_payload=payload)

    return ToolPreInvokeResult()

# 2. Rate limiting and access control
async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
    user_id = context.global_context.user
    tool_name = payload.name

    # Check rate limits
    if not self._check_rate_limit(user_id, tool_name):
        violation = PluginViolation(
            reason="Rate limit exceeded",
            description=f"User {user_id} exceeded rate limit for {tool_name}",
            code="RATE_LIMIT_EXCEEDED"
        )
        return ToolPreInvokeResult(continue_processing=False, violation=violation)

    # Check tool permissions
    if not self._has_tool_permission(user_id, tool_name):
        violation = PluginViolation(
            reason="Unauthorized tool access",
            description=f"User {user_id} not authorized for {tool_name}",
            code="UNAUTHORIZED_TOOL_ACCESS"
        )
        return ToolPreInvokeResult(continue_processing=False, violation=violation)

    return ToolPreInvokeResult()

# 3. Argument validation and sanitization
async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
    validated_args = {}

    # Validate and sanitize tool arguments
    for key, value in payload.args.items():
        if isinstance(value, str):
            # Remove potentially dangerous characters
            sanitized = re.sub(r'[<>"\']', '', value)
            # Limit string length
            if len(sanitized) > MAX_ARG_LENGTH:
                violation = PluginViolation(
                    reason="Argument too long",
                    description=f"Argument '{key}' exceeds {MAX_ARG_LENGTH} characters",
                    code="ARGUMENT_TOO_LONG"
                )
                return ToolPreInvokeResult(continue_processing=False, violation=violation)
            validated_args[key] = sanitized
        else:
            validated_args[key] = value

    # Check for required arguments based on tool
    required_args = self._get_required_args(payload.name)
    for req_arg in required_args:
        if req_arg not in validated_args:
            violation = PluginViolation(
                reason="Missing required argument",
                description=f"Tool {payload.name} requires argument '{req_arg}'",
                code="MISSING_REQUIRED_ARGUMENT"
            )
            return ToolPreInvokeResult(continue_processing=False, violation=violation)

    payload.args = validated_args
    return ToolPreInvokeResult(modified_payload=payload)
```

### Tool Post-Invoke Hook

**Function Signature**: `async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `tool_post_invoke` | Hook identifier for configuration |
| **Execution Point** | After tool execution completes | When tool has finished processing and returned results |
| **Purpose** | Result filtering, output validation, response transformation | Process and secure tool execution results |

**Payload Attributes (`ToolPostInvokePayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `name` | `str` | Yes | Name of the tool that was executed | `"file_reader"` |
| `result` | `Any` | Yes | Tool execution result (can be string, dict, list, etc.) | `{"content": "file contents...", "size": 1024}` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Return Type (`ToolPostInvokeResult`)**:
- Extends `PluginResult[ToolPostInvokePayload]`
- Can modify `payload.result` content
- Can block result with violation

**Example Use Cases**:
```python
# 1. Sensitive data filtering
async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
    result = payload.result

    if isinstance(result, str):
        # Scan for and redact sensitive patterns
        filtered_result = self._filter_sensitive_data(result)

        if filtered_result != result:
            payload.result = filtered_result
            context.metadata["sensitive_data_filtered"] = True
            return ToolPostInvokeResult(modified_payload=payload)

    elif isinstance(result, dict):
        # Recursively filter dictionary values
        filtered_result = self._filter_dict_values(result)

        if filtered_result != result:
            payload.result = filtered_result
            context.metadata["sensitive_data_filtered"] = True
            return ToolPostInvokeResult(modified_payload=payload)

    return ToolPostInvokeResult()

# 2. Output size limits and validation
async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
    result_size = len(str(payload.result))

    # Check result size limits
    if result_size > MAX_RESULT_SIZE:
        violation = PluginViolation(
            reason="Result too large",
            description=f"Tool result size {result_size} exceeds limit {MAX_RESULT_SIZE}",
            code="RESULT_TOO_LARGE"
        )
        return ToolPostInvokeResult(continue_processing=False, violation=violation)

    # Validate result structure for specific tools
    if payload.name == "json_parser" and not self._is_valid_json(payload.result):
        violation = PluginViolation(
            reason="Invalid result format",
            description="JSON parser returned invalid JSON",
            code="INVALID_RESULT_FORMAT"
        )
        return ToolPostInvokeResult(continue_processing=False, violation=violation)

    context.metadata["result_size"] = result_size
    return ToolPostInvokeResult()

# 3. Result transformation and enhancement
async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
    # Add metadata or transform results
    if isinstance(payload.result, dict):
        enhanced_result = payload.result.copy()
        enhanced_result["_metadata"] = {
            "processed_at": datetime.utcnow().isoformat(),
            "tool_name": payload.name,
            "request_id": context.global_context.request_id
        }

        # Add computed fields
        if "content" in enhanced_result:
            enhanced_result["content_length"] = len(enhanced_result["content"])
            enhanced_result["content_hash"] = hashlib.md5(
                enhanced_result["content"].encode()
            ).hexdigest()

        payload.result = enhanced_result
        return ToolPostInvokeResult(modified_payload=payload)

    return ToolPostInvokeResult()
```

### Resource Pre-Fetch Hook

**Function Signature**: `async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `resource_pre_fetch` | Hook identifier for configuration |
| **Execution Point** | Before resource is fetched from URI | When MCP client requests resource content |
| **Purpose** | URI validation, access control, protocol restrictions | Validate and secure resource access requests |

**Payload Attributes (`ResourcePreFetchPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `uri` | `str` | Yes | URI of the resource being requested | `"https://api.example.com/data.json"` |
| `metadata` | `dict[str, Any]` |  | Additional request metadata | `{"Accept": "application/json", "timeout": 30}` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Return Type (`ResourcePreFetchResult`)**:
- Extends `PluginResult[ResourcePreFetchPayload]`
- Can modify `payload.uri` and `payload.metadata`
- Can block resource access with violation

**Example Use Cases**:
```python
# 1. Protocol and domain validation
async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
    uri_parts = urlparse(payload.uri)

    # Check allowed protocols
    allowed_protocols = ["http", "https", "file"]
    if uri_parts.scheme not in allowed_protocols:
        violation = PluginViolation(
            reason="Blocked protocol",
            description=f"Protocol '{uri_parts.scheme}' not in allowed list",
            code="PROTOCOL_BLOCKED"
        )
        return ResourcePreFetchResult(continue_processing=False, violation=violation)

    # Check domain whitelist/blacklist
    blocked_domains = ["malicious.example.com", "blocked-site.org"]
    if uri_parts.netloc in blocked_domains:
        violation = PluginViolation(
            reason="Blocked domain",
            description=f"Domain '{uri_parts.netloc}' is blocked",
            code="DOMAIN_BLOCKED"
        )
        return ResourcePreFetchResult(continue_processing=False, violation=violation)

    # Validate file paths for file:// URIs
    if uri_parts.scheme == "file":
        path = uri_parts.path
        if ".." in path or not path.startswith("/allowed/"):
            violation = PluginViolation(
                reason="Unsafe file path",
                description=f"File path not allowed: {path}",
                code="UNSAFE_FILE_PATH"
            )
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

    return ResourcePreFetchResult()

# 2. Request metadata enhancement
async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
    # Add security headers or modify request
    enhanced_metadata = payload.metadata.copy() if payload.metadata else {}

    # Add authentication if needed
    if "Authorization" not in enhanced_metadata:
        api_key = self._get_api_key_for_domain(urlparse(payload.uri).netloc)
        if api_key:
            enhanced_metadata["Authorization"] = f"Bearer {api_key}"

    # Add request tracking
    enhanced_metadata["User-Agent"] = "MCPGateway/1.0"
    enhanced_metadata["X-Request-ID"] = context.global_context.request_id

    # Set timeout if not specified
    if "timeout" not in enhanced_metadata:
        enhanced_metadata["timeout"] = 30

    modified_payload = ResourcePreFetchPayload(
        uri=payload.uri,
        metadata=enhanced_metadata
    )
    return ResourcePreFetchResult(modified_payload=modified_payload)

# 3. Access control and rate limiting
async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
    user_id = context.global_context.user
    uri = payload.uri
    domain = urlparse(uri).netloc

    # Check per-user rate limits for domain
    if not self._check_domain_rate_limit(user_id, domain):
        violation = PluginViolation(
            reason="Rate limit exceeded",
            description=f"User {user_id} exceeded rate limit for domain {domain}",
            code="DOMAIN_RATE_LIMIT_EXCEEDED"
        )
        return ResourcePreFetchResult(continue_processing=False, violation=violation)

    # Check resource access permissions
    if not self._has_resource_permission(user_id, uri):
        violation = PluginViolation(
            reason="Unauthorized resource access",
            description=f"User {user_id} not authorized to access {uri}",
            code="UNAUTHORIZED_RESOURCE_ACCESS"
        )
        return ResourcePreFetchResult(continue_processing=False, violation=violation)

    return ResourcePreFetchResult()
```

### Resource Post-Fetch Hook

**Function Signature**: `async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `resource_post_fetch` | Hook identifier for configuration |
| **Execution Point** | After resource content is fetched and loaded | When resource has been successfully retrieved |
| **Purpose** | Content validation, filtering, transformation | Process and validate fetched resource content |

**Payload Attributes (`ResourcePostFetchPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `uri` | `str` | Yes | URI of the fetched resource | `"https://api.example.com/data.json"` |
| `content` | `Any` | Yes | Fetched resource content (ResourceContent object) | `ResourceContent(type="resource", uri="...", text="...")` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**ResourceContent Structure**:
- `type`: Content type identifier
- `uri`: Resource URI
- `text`: Text content (for text resources)
- `blob`: Binary content (for binary resources)
- Optional metadata fields

**Return Type (`ResourcePostFetchResult`)**:
- Extends `PluginResult[ResourcePostFetchPayload]`
- Can modify `payload.content` data
- Can block content with violation

**Example Use Cases**:
```python
# 1. Content size and type validation
async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
    content = payload.content

    # Check content size limits
    if hasattr(content, 'text') and content.text:
        content_size = len(content.text)
        if content_size > MAX_CONTENT_SIZE:
            violation = PluginViolation(
                reason="Content too large",
                description=f"Resource content size {content_size} exceeds limit {MAX_CONTENT_SIZE}",
                code="CONTENT_SIZE_EXCEEDED"
            )
            return ResourcePostFetchResult(continue_processing=False, violation=violation)

    # Validate content type
    expected_type = self._get_expected_content_type(payload.uri)
    if expected_type and not self._is_valid_content_type(content, expected_type):
        violation = PluginViolation(
            reason="Invalid content type",
            description=f"Resource content type doesn't match expected: {expected_type}",
            code="INVALID_CONTENT_TYPE"
        )
        return ResourcePostFetchResult(continue_processing=False, violation=violation)

    context.metadata["content_validation"] = {
        "size": content_size if hasattr(content, 'text') else 0,
        "type": content.type if hasattr(content, 'type') else "unknown"
    }
    return ResourcePostFetchResult()

# 2. Content filtering and sanitization
async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
    content = payload.content
    modified = False

    if hasattr(content, 'text') and content.text:
        original_text = content.text

        # Remove sensitive patterns
        filtered_text = self._filter_sensitive_patterns(original_text)

        # Apply content filters (remove scripts, etc.)
        sanitized_text = self._sanitize_content(filtered_text)

        if sanitized_text != original_text:
            content.text = sanitized_text
            modified = True
            context.metadata["content_filtered"] = True

    if modified:
        return ResourcePostFetchResult(modified_payload=payload)

    return ResourcePostFetchResult()

# 3. Content parsing and enhancement
async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
    content = payload.content

    # Parse JSON content and add metadata
    if hasattr(content, 'text') and payload.uri.endswith('.json'):
        try:
            parsed_data = json.loads(content.text)

            # Add parsing metadata
            enhanced_data = {
                "parsed_content": parsed_data,
                "metadata": {
                    "parsed_at": datetime.utcnow().isoformat(),
                    "source_uri": payload.uri,
                    "content_hash": hashlib.md5(content.text.encode()).hexdigest(),
                    "field_count": len(parsed_data) if isinstance(parsed_data, dict) else None,
                    "array_length": len(parsed_data) if isinstance(parsed_data, list) else None
                }
            }

            # Update content with enhanced data
            content.text = json.dumps(enhanced_data, indent=2)

            return ResourcePostFetchResult(modified_payload=payload)

        except json.JSONDecodeError as e:
            violation = PluginViolation(
                reason="Invalid JSON content",
                description=f"Failed to parse JSON from {payload.uri}: {str(e)}",
                code="INVALID_JSON_CONTENT"
            )
            return ResourcePostFetchResult(continue_processing=False, violation=violation)

    return ResourcePostFetchResult()
```

## Hook Execution Summary

| Hook | Timing | Primary Use Cases |
|------|--------|-------------------|
| `prompt_pre_fetch` | Before prompt template processing | Input validation, PII detection, access control |
| `prompt_post_fetch` | After prompt template rendering | Content filtering, output validation |
| `tool_pre_invoke` | Before tool execution | Parameter validation, security checks, rate limiting |
| `tool_post_invoke` | After tool execution | Result filtering, output validation, transformation |
| `resource_pre_fetch` | Before resource fetching | URI validation, access control, protocol checks |
| `resource_post_fetch` | After resource content loading | Content validation, filtering, enhancement |

**Performance Notes**:
- Native plugins have the lowest execution latency
- External plugins typically add 10-100ms depending on network and service
- Resource post-fetch may take longer due to content processing
- Plugin execution is sequential within priority bands
- Failed plugins don't affect other plugins (isolation)
