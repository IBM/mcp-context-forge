# Gateway Administrative Hooks

This document details the administrative hook points in ContextForge Plugin Framework, covering gateway management operations including server registration, updates, federation, and entity lifecycle management.
## Administrative Hook Functions

The framework provides administrative hooks for gateway management operations:

| Hook Function | Description | When It Executes | Primary Use Cases |
|---------------|-------------|-------------------|-------------------|
| [`server_pre_register()`](#server-pre-register-hook) | Process server registration requests before creating server records | Before MCP server is registered in the gateway | Server validation, naming conventions, policy enforcement, auto-configuration |
| [`server_post_register()`](#server-post-register-hook) | Process server registration results after successful creation | After MCP server registration completes | Audit logging, notifications, external integrations, metrics collection |
| [`server_pre_update()`](#server-pre-update-hook) | Process server update requests before applying configuration changes | Before MCP server configuration is modified | Change validation, approval workflows, impact assessment, transformation |
| [`server_post_update()`](#server-post-update-hook) | Process server update results after successful modification | After MCP server updates complete | Change notifications, cache invalidation, discovery updates, audit logging |
| [`server_pre_delete()`](#server-pre-delete-hook) | Process server deletion requests before removing server records | Before MCP server is deleted from the gateway | Access control, dependency checks, data preservation, deletion confirmation |
| [`server_post_delete()`](#server-post-delete-hook) | Process server deletion results after successful removal | After MCP server deletion completes | Resource cleanup, notifications, audit logging, compliance archiving |
| [`server_pre_status_change()`](#server-pre-status-change-hook) | Process server status change requests before activation/deactivation | Before MCP server is activated or deactivated | Access control, dependency validation, impact assessment, quota enforcement |
| [`server_post_status_change()`](#server-post-status-change-hook) | Process server status change results after successful toggle | After MCP server status change completes | Monitoring setup/teardown, notifications, resource management, metrics tracking |
| [`gateway_pre_register()`](#gateway-pre-register-hook) | Process gateway registration requests before creating federation records | Before peer gateway is registered | Gateway validation, federation loop detection, security enforcement, auto-configuration |
| [`gateway_post_register()`](#gateway-post-register-hook) | Process gateway registration results after successful federation | After peer gateway registration completes | Health monitoring setup, federation handshake, discovery updates, capability detection |
| [`gateway_pre_update()`](#gateway-pre-update-hook) | Process gateway update requests before applying federation changes | Before peer gateway configuration is modified | Federation impact assessment, URL validation, authentication changes, confirmation workflows |
| [`gateway_post_update()`](#gateway-post-update-hook) | Process gateway update results after successful modification | After peer gateway updates complete | Federation connection refresh, capability updates, discovery synchronization, monitoring updates |
| [`gateway_pre_delete()`](#gateway-pre-delete-hook) | Process gateway deletion requests before removing federation records | Before peer gateway is removed from federation | Federation dependency checks, resource migration planning, graceful disconnection workflows |
| [`gateway_post_delete()`](#gateway-post-delete-hook) | Process gateway deletion results after successful removal | After peer gateway deletion completes | Federation cleanup, resource deregistration, monitoring teardown, cache invalidation |
| [`gateway_pre_status_change()`](#gateway-pre-status-change-hook) | Process gateway status change requests before enabling/disabling | Before peer gateway is enabled or disabled | Federation impact assessment, dependency validation, connection management |
| [`gateway_post_status_change()`](#gateway-post-status-change-hook) | Process gateway status change results after successful toggle | After peer gateway status change completes | Federation connection activation/deactivation, discovery updates, monitoring adjustments |
## Server Management Hooks

### Server Pre-Register Hook

**Function Signature**: `async def server_pre_register(self, payload: ServerPreOperationPayload, context: PluginContext) -> ServerPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_pre_register` | Hook identifier for configuration |
| **Execution Point** | Before server registration in gateway | When administrator or API client registers a new MCP server |
| **Purpose** | Server validation, policy enforcement, auto-configuration | Validate and transform server registration data before persistence |

**Payload Structure:**

```python
class ServerInfo(BaseModel):
    """Core server information - modifiable by plugins"""
    id: Optional[str] = Field(None, description="Server UUID identifier")
    name: str = Field(..., description="The server's name")
    description: Optional[str] = Field(None, description="Server description")
    icon: Optional[str] = Field(None, description="URL for the server's icon")
    tags: List[str] = Field(default_factory=list, description="Tags for categorizing the server")

    # Associated entities
    associated_tools: List[str] = Field(default_factory=list, description="Associated tool IDs")
    associated_resources: List[str] = Field(default_factory=list, description="Associated resource IDs")
    associated_prompts: List[str] = Field(default_factory=list, description="Associated prompt IDs")
    associated_a2a_agents: List[str] = Field(default_factory=list, description="Associated A2A agent IDs")

    # Team and organization
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the server owner")
    visibility: str = Field(default="private", description="Visibility level (private, team, public)")

class ServerAuditInfo(BaseModel):
    """Server audit/operational information - read-only across all server operations"""
    # Operation metadata
    operation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: Optional[str] = None                        # Unique request identifier

    # User and request info
    created_by: Optional[str] = None                        # User performing the operation
    created_from_ip: Optional[str] = None                   # Client IP address
    created_via: Optional[str] = None                       # Operation source ("api", "ui", "bulk_import", "federation")
    created_user_agent: Optional[str] = None                # Client user agent

    # Server state information
    server_id: Optional[str] = None                         # Target server ID (for updates/deletes)
    original_server_info: Optional[ServerInfo] = None       # Original state (for updates/deletes)

    # Database timestamps (populated in post-hooks)
    created_at: Optional[datetime] = None                   # Server creation timestamp
    updated_at: Optional[datetime] = None                   # Server last update timestamp

    # Team/tenant context
    team_id: Optional[str] = None                           # Team performing operation
    tenant_id: Optional[str] = None                         # Tenant context

class ServerPreOperationPayload(BaseModel):
    """Unified payload for server pre-operation hooks (register, update, etc.)"""
    server_info: ServerInfo                                 # Modifiable server information
    headers: HttpHeaderPayload = Field(default_factory=dict) # HTTP headers for passthrough

class ServerPostOperationPayload(BaseModel):
    """Unified payload for server post-operation hooks (register, update, etc.)"""
    server_info: Optional[ServerInfo] = None                # Complete server information (if successful)
    operation_success: bool                                 # Whether operation succeeded
    error_details: Optional[str] = None                     # Error details if operation failed
    headers: HttpHeaderPayload = Field(default_factory=dict) # HTTP headers for passthrough
```

**Payload Attributes (`ServerPreOperationPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` | Yes | Modifiable server information object | See ServerInfo structure above |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `created_by` | `str` | User performing the operation | `"admin@example.com"` |
| `created_from_ip` | `str` | Client IP address | `"192.168.1.100"` |
| `created_via` | `str` | Operation source | `"api"`, `"ui"`, `"bulk_import"`, `"federation"` |
| `created_user_agent` | `str` | Client user agent | `"curl/7.68.0"` |
| `request_id` | `str` | Unique request identifier | `"req-456"` |
| `operation_timestamp` | `datetime` | Operation timestamp | `"2025-01-15T10:30:00Z"` |
| `server_id` | `str` | Target server ID (for updates/deletes) | `"srv-123"` |
| `original_server_info` | `ServerInfo` | Original state (for updates/deletes) | Previous server configuration |
| `team_id` | `str` | Team performing operation | `"team-456"` |

**Return Type (`ServerPreOperationResult`)**:

- Extends `PluginResult[ServerPreOperationPayload]`
- Can modify all payload attributes before server creation
- Can block server registration with violation
- Can request client elicitation for additional information

**Example Use Cases**:

```python
# 1. Server naming convention enforcement
async def server_pre_register(self, payload: ServerPreOperationPayload,
                             context: PluginContext) -> ServerPreOperationResult:
    # Access audit information from context
    audit_info = context.server_audit_info

    # Enforce company naming convention
    if not payload.server_info.name.startswith("company-"):
        payload.server_info.name = f"company-{payload.server_info.name}"

    # Auto-generate description if missing
    if not payload.server_info.description:
        payload.server_info.description = f"Automatically registered server: {payload.server_info.name}"

    # Add mandatory tags based on team from server_info
    if payload.server_info.team_id:
        payload.server_info.tags.append(f"team-{payload.server_info.team_id}")

    # Add creator-based tag from audit info
    if audit_info.created_by:
        user_domain = audit_info.created_by.split("@")[1] if "@" in audit_info.created_by else "unknown"
        payload.server_info.tags.append(f"domain-{user_domain}")

    return ServerPreOperationResult(modified_payload=payload)

# 2. Server validation and security checks
async def server_pre_register(self, payload: ServerPreRegisterPayload,
                             context: PluginContext) -> ServerPreOperationResult:
    # Validate server name against blacklist
    blocked_names = ["admin", "system", "root", "test"]
    if payload.server_info.name.lower() in blocked_names:
        violation = PluginViolation(
            reason="Blocked server name",
            description=f"Server name '{payload.server_info.name}' is not allowed",
            code="BLOCKED_SERVER_NAME"
        )
        return ServerPreOperationResult(continue_processing=False, violation=violation)

    # Check if user has permission to register servers
    user_email = context.server_audit_info.created_by
    if not self._has_server_registration_permission(user_email):
        violation = PluginViolation(
            reason="Insufficient permissions",
            description=f"User {user_email} cannot register servers",
            code="INSUFFICIENT_PERMISSIONS"
        )
        return ServerPreOperationResult(continue_processing=False, violation=violation)

    # Check server registration quota
    current_count = await self._get_user_server_count(user_email)
    max_servers = self._get_user_server_limit(user_email)
    if current_count >= max_servers:
        violation = PluginViolation(
            reason="Server quota exceeded",
            description=f"User has reached maximum of {max_servers} servers",
            code="SERVER_QUOTA_EXCEEDED"
        )
        return ServerPreOperationResult(continue_processing=False, violation=violation)

    return ServerPreOperationResult()

# 3. Auto-configuration and enhancement
async def server_pre_register(self, payload: ServerPreRegisterPayload,
                             context: PluginContext) -> ServerPreOperationResult:
    # Auto-tag based on name patterns
    if "file" in payload.server_info.name.lower():
        payload.server_info.tags.extend(["files", "storage"])
    elif "api" in payload.server_info.name.lower():
        payload.server_info.tags.extend(["api", "integration"])
    elif "db" in payload.server_info.name.lower() or "database" in payload.server_info.name.lower():
        payload.server_info.tags.extend(["database", "data"])

    # Set default icon based on tags
    if not payload.server_info.icon:
        if "files" in payload.server_info.tags:
            payload.server_info.icon = "https://cdn.example.com/icons/file-server.png"
        elif "api" in payload.server_info.tags:
            payload.server_info.icon = "https://cdn.example.com/icons/api-server.png"

    # Add audit headers
    payload.headers["X-Registration-Source"] = context.server_audit_info.created_via
    payload.headers["X-Registration-User"] = context.server_audit_info.created_by

    return ServerPreOperationResult(modified_payload=payload)

# 4. User confirmation for sensitive operations
async def server_pre_register(self, payload: ServerPreRegisterPayload,
                             context: PluginContext) -> ServerPreOperationResult:
    # Check if this is a production-like server name
    production_patterns = ["prod", "production", "live", "main"]
    is_production = any(pattern in payload.server_info.name.lower() for pattern in production_patterns)

    if is_production and not context.elicitation_responses:
        # Request user confirmation for production server
        confirmation_schema = {
            "type": "object",
            "properties": {
                "confirm_production": {
                    "type": "boolean",
                    "description": "Confirm registration of production server"
                },
                "business_justification": {
                    "type": "string",
                    "description": "Business justification for production server",
                    "minLength": 10
                }
            },
            "required": ["confirm_production", "business_justification"]
        }

        elicitation_request = ElicitationRequest(
            message=f"You are registering a production server '{payload.server_info.name}'. Please confirm.",
            schema=confirmation_schema,
            timeout_seconds=300  # 5 minutes
        )

        return ServerPreOperationResult(
            continue_processing=False,
            elicitation_request=elicitation_request
        )

    # Process elicitation response
    if context.elicitation_responses and is_production:
        response = context.elicitation_responses[0]
        if response.action != "accept" or not response.data.get("confirm_production"):
            violation = PluginViolation(
                reason="Production server registration declined",
                description="User declined to register production server",
                code="PRODUCTION_REGISTRATION_DECLINED"
            )
            return ServerPreOperationResult(continue_processing=False, violation=violation)

        # Add justification to server description
        justification = response.data.get("business_justification", "")
        if justification:
            payload.server_info.description = f"{payload.server_info.description or ''}\n\nBusiness Justification: {justification}"

        # Add production tag
        payload.server_info.tags.append("production")

    return ServerPreOperationResult(modified_payload=payload)
```

### Server Post-Register Hook

**Function Signature**: `async def server_post_register(self, payload: ServerPostOperationPayload, context: PluginContext) -> ServerPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_post_register` | Hook identifier for configuration |
| **Execution Point** | After server registration completes | When MCP server has been successfully created in the gateway |
| **Purpose** | Audit logging, notifications, integrations, metrics | Process successful server registrations and handle follow-up actions |

**Payload Attributes (`ServerPostOperationPayload`)**:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` |  | Complete registered server information (if successful) | Contains all ServerInfo fields |
| `operation_success` | `bool` | Yes | Whether registration succeeded | `true` |
| `error_details` | `str` |  | Error details if registration failed | `"Duplicate server name"` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as pre-register hook, plus database timestamps
- Contains complete audit trail including `created_at` and `updated_at` timestamps

**Return Type (`ServerPostOperationResult`)**:

- Extends `PluginResult[ServerPostOperationPayload]`
- Cannot modify server data (read-only post-operation hook)
- Can trigger additional actions or external integrations
- Violations in post-hooks log errors but don't affect the operation

**Example Use Cases**:

```python
# 1. Audit logging and compliance
async def server_post_register(self, payload: ServerPostOperationPayload,
                              context: PluginContext) -> ServerPostOperationResult:
    # Access audit information from context
    audit_info = context.server_audit_info

    # Log comprehensive audit record
    audit_record = {
        "event_type": "server_registration",
        "success": payload.operation_success,
        "user": audit_info.created_by,
        "ip_address": audit_info.created_from_ip,
        "user_agent": audit_info.created_user_agent,
        "creation_method": audit_info.created_via,
        "timestamp": audit_info.created_at,
        "request_id": audit_info.request_id
    }

    if payload.operation_success and payload.server_info:
        audit_record.update({
            "server_id": payload.server_info.id,
            "server_name": payload.server_info.name,
            "team_id": payload.server_info.team_id,
            "tags": payload.server_info.tags
        })
    else:
        audit_record["error"] = payload.error_details

    # Send to audit logging system
    await self._send_audit_log(audit_record)

    # Update metrics
    if payload.operation_success:
        await self._increment_metric("servers_registered_total", {
            "method": context.server_audit_info.created_via,
            "team": context.server_audit_info.team_id or "none"
        })
    else:
        await self._increment_metric("server_registration_failures_total", {
            "error_type": "registration_error"
        })

    return ServerPostOperationResult()

# 2. Team notifications and integrations
async def server_post_register(self, payload: ServerPostOperationPayload,
                              context: PluginContext) -> ServerPostOperationResult:
    if payload.operation_success:
        # Send notification to team members
        team_id = context.server_audit_info.team_id
        if team_id:
            team_members = await self._get_team_members(team_id)
            notification = {
                "title": "New MCP Server Registered",
                "message": f"Server '{payload.server_info.name}' has been registered by {context.server_audit_info.created_by}",
                "server_id": payload.server_info.id,
                "registered_by": context.server_audit_info.created_by,
                "timestamp": context.server_audit_info.created_at.isoformat()
            }

            for member in team_members:
                await self._send_notification(member["email"], notification)

        # Integrate with external systems
        await self._sync_to_service_catalog({
            "id": payload.server_info.id,
            "name": payload.server_info.name,
            "owner": context.server_audit_info.created_by,
            "team": team_id,
            "status": "active"
        })

        # Trigger monitoring setup
        await self._setup_server_monitoring(payload.server_info.id, payload.server_info.name)

    return ServerPostOperationResult()

# 3. Error handling and recovery
async def server_post_register(self, payload: ServerPostOperationPayload,
                              context: PluginContext) -> ServerPostOperationResult:
    if not payload.operation_success:
        # Log detailed error for debugging
        error_context = {
            "server_name": payload.server_info.name if payload.server_info else "unknown",
            "error": payload.error_details,
            "user": context.server_audit_info.created_by,
            "request_data": {
                "team_id": context.server_audit_info.team_id,
                "creation_method": context.server_audit_info.created_via,
                "ip_address": context.server_audit_info.created_from_ip
            }
        }

        self.logger.error(f"Server registration failed: {payload.server_info.name if payload.server_info else 'unknown'}",
                         extra=error_context)

        # Send error notification to admin
        if "quota" in payload.error_details.lower():
            await self._notify_admin_quota_exceeded(
                context.server_audit_info.created_by,
                payload.error_details
            )
        elif "permission" in payload.error_details.lower():
            await self._notify_admin_permission_denied(
                context.server_audit_info.created_by,
                payload.server_info.name
            )

        # Update error metrics with classification
        error_type = self._classify_error(payload.error_details)
        await self._increment_metric("server_registration_failures_total", {
            "error_type": error_type,
            "creation_method": context.server_audit_info.created_via
        })

    return ServerPostOperationResult()

# 4. Automated follow-up actions
async def server_post_register(self, payload: ServerPostOperationPayload,
                              context: PluginContext) -> ServerPostOperationResult:
    if payload.operation_success:
        # Auto-create default resources for certain server types
        server_name_lower = payload.server_info.name.lower()

        if "api" in server_name_lower:
            # Create API documentation resource
            await self._create_api_doc_resource(payload.server_info.id, payload.server_info.name)

        elif "database" in server_name_lower or "db" in server_name_lower:
            # Create database schema resource
            await self._create_db_schema_resource(payload.server_info.id, payload.server_info.name)

        elif "file" in server_name_lower:
            # Create file system browser resource
            await self._create_file_browser_resource(payload.server_info.id, payload.server_info.name)

        # Schedule health check for new server
        await self._schedule_server_health_check(payload.server_info.id, delay_minutes=5)

        # Add to server discovery index
        await self._add_to_discovery_index({
            "server_id": payload.server_info.id,
            "name": payload.server_info.name,
            "team": context.server_audit_info.team_id,
            "registered_at": context.server_audit_info.created_at
        })

    return ServerPostOperationResult()
```

### Server Pre-Update Hook

**Function Signature**: `async def server_pre_update(self, payload: ServerPreOperationPayload, context: PluginContext) -> ServerPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_pre_update` | Hook identifier for configuration |
| **Execution Point** | Before server update applies | When MCP server configuration is being modified |
| **Purpose** | Validation, transformation, access control | Enforce update policies and modify update data |

**Payload Attributes (`ServerPreOperationPayload`)** - Same as pre-register:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` | Yes | Updated server information object | Contains modified server fields |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as register hooks, **plus**:

  - `server_id` - ID of server being updated
  - `original_server_info` - Server state before the update

**Return Type (`ServerPreOperationResult`)**:

- Extends `PluginResult[ServerPreOperationPayload]`
- Can modify server update data before application
- Can block server updates with violation
- Can request client elicitation for change approval

**Example Use Cases**:

```python
# 1. Change validation and approval workflow
async def server_pre_update(self, payload: ServerPreOperationPayload,
                           context: PluginContext) -> ServerPreOperationResult:
    original = context.server_audit_info.original_server_info
    current = payload.server_info

    # Detect critical changes requiring approval
    critical_changes = []
    if original.uri != current.uri:
        critical_changes.append("URI endpoint")
    if original.visibility != current.visibility and current.visibility == "public":
        critical_changes.append("visibility to public")
    if "production" in current.tags and "production" not in original.tags:
        critical_changes.append("production classification")

    # Request approval for critical changes
    if critical_changes and not context.elicitation_responses:
        approval_schema = {
            "type": "object",
            "properties": {
                "approve_changes": {
                    "type": "boolean",
                    "description": f"Approve these critical changes: {', '.join(critical_changes)}"
                },
                "change_justification": {
                    "type": "string",
                    "description": "Business justification for these changes",
                    "minLength": 20
                }
            },
            "required": ["approve_changes", "change_justification"]
        }

        return ServerPreOperationResult(
            continue_processing=False,
            elicitation_request=ElicitationRequest(
                message=f"Critical changes detected for server '{current.name}': {', '.join(critical_changes)}",
                schema=approval_schema,
                timeout_seconds=600
            )
        )

    # Process approval response
    if context.elicitation_responses:
        response = context.elicitation_responses[0]
        if not response.data.get("approve_changes"):
            return ServerPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Server update declined",
                    description="Critical changes not approved by user",
                    code="UPDATE_NOT_APPROVED"
                )
            )

        # Add justification to update audit
        justification = response.data.get("change_justification", "")
        payload.headers["X-Change-Justification"] = justification

    return ServerPreOperationResult(modified_payload=payload)
```

### Server Post-Update Hook

**Function Signature**: `async def server_post_update(self, payload: ServerPostOperationPayload, context: PluginContext) -> ServerPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_post_update` | Hook identifier for configuration |
| **Execution Point** | After server update completes | When MCP server has been successfully updated |
| **Purpose** | Audit logging, notifications, cache invalidation | Process successful updates and handle follow-up actions |

**Payload Attributes (`ServerPostOperationPayload`)** - Same as post-register:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` |  | Updated server information (if successful) | Contains all updated ServerInfo fields |
| `operation_success` | `bool` | Yes | Whether update succeeded | `true` |
| `error_details` | `str` |  | Error details if update failed | `"Validation error: Invalid URI"` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as register hooks, **plus**:

  - `server_id` - ID of server that was updated
  - `original_server_info` - Server state before the update
  - `updated_at` - Database timestamp of the update

**Return Type (`ServerPostOperationResult`)**:

- Extends `PluginResult[ServerPostOperationPayload]`
- Cannot modify server data (read-only post-operation hook)
- Can trigger cache invalidation, notifications, and integrations
- Violations in post-hooks log errors but don't affect the operation

**Example Use Cases**:

```python
# 1. Change notification and cache invalidation
async def server_post_update(self, payload: ServerPostOperationPayload,
                            context: PluginContext) -> ServerPostOperationResult:
    if not payload.operation_success:
        # Log update failure
        self.logger.error(f"Server update failed: {payload.server_info.name if payload.server_info else 'unknown'}",
                         extra={
                             "error": payload.error_details,
                             "user": context.server_audit_info.created_by,
                             "server_id": context.server_audit_info.server_id
                         })
        return ServerPostOperationResult()

    # Calculate changes
    original = context.server_audit_info.original_server_info
    updated = payload.server_info
    changes = []

    if original.name != updated.name:
        changes.append(f"name: '{original.name}' → '{updated.name}'")
    if original.uri != updated.uri:
        changes.append(f"uri: '{original.uri}' → '{updated.uri}'")
    if original.visibility != updated.visibility:
        changes.append(f"visibility: '{original.visibility}' → '{updated.visibility}'")
    if set(original.tags) != set(updated.tags):
        changes.append(f"tags: {original.tags} → {updated.tags}")

    # Send change notifications
    if changes:
        await self._notify_server_changes({
            "server_id": updated.id,
            "server_name": updated.name,
            "changes": changes,
            "updated_by": context.server_audit_info.created_by,
            "timestamp": context.server_audit_info.operation_timestamp.isoformat()
        })

    # Invalidate caches
    await self._invalidate_server_cache(updated.id)

    # Update discovery index
    if original.visibility != updated.visibility or original.tags != updated.tags:
        await self._update_discovery_index({
            "server_id": updated.id,
            "name": updated.name,
            "visibility": updated.visibility,
            "tags": updated.tags
        })

    return ServerPostOperationResult()
```

### Server Pre-Delete Hook

**Function Signature**: `async def server_pre_delete(self, payload: ServerPreOperationPayload, context: PluginContext) -> ServerPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_pre_delete` | Hook identifier for configuration |
| **Execution Point** | Before server deletion | When MCP server is about to be removed from the gateway |
| **Purpose** | Access control, dependency checks, data preservation | Validate deletion permissions and handle cleanup preparation |

**Payload Attributes (`ServerPreOperationPayload`)** - Same structure as other pre-hooks:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` | Yes | Server information being deleted | Contains server to be removed |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as other operations, **plus**:

  - `server_id` - ID of server being deleted
  - `original_server_info` - Complete server state before deletion (same as `payload.server_info`)

**Return Type (`ServerPreOperationResult`)**:

- Extends `PluginResult[ServerPreOperationPayload]`
- Can modify deletion behavior (e.g., soft delete vs hard delete)
- Can block server deletion with violation
- Can request client elicitation for deletion confirmation

**Example Use Cases**:

```python
# 1. Deletion protection and confirmation
async def server_pre_delete(self, payload: ServerPreOperationPayload,
                           context: PluginContext) -> ServerPreOperationResult:
    server = payload.server_info

    # Protect production servers
    if "production" in server.tags:
        if not context.elicitation_responses:
            confirmation_schema = {
                "type": "object",
                "properties": {
                    "confirm_production_delete": {
                        "type": "boolean",
                        "description": f"Confirm deletion of PRODUCTION server '{server.name}'"
                    },
                    "deletion_reason": {
                        "type": "string",
                        "description": "Reason for deleting this production server",
                        "minLength": 10
                    },
                    "backup_confirmation": {
                        "type": "boolean",
                        "description": "Confirm that data backups have been created"
                    }
                },
                "required": ["confirm_production_delete", "deletion_reason", "backup_confirmation"]
            }

            return ServerPreOperationResult(
                continue_processing=False,
                elicitation_request=ElicitationRequest(
                    message=f"⚠️  PRODUCTION SERVER DELETION\n\nYou are about to delete production server '{server.name}'.\nThis action cannot be undone.",
                    schema=confirmation_schema,
                    timeout_seconds=300
                )
            )

        # Process confirmation response
        response = context.elicitation_responses[0]
        if not response.data.get("confirm_production_delete") or not response.data.get("backup_confirmation"):
            return ServerPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Production server deletion cancelled",
                    description="User cancelled production server deletion",
                    code="PRODUCTION_DELETE_CANCELLED"
                )
            )

        # Add deletion audit info
        payload.headers["X-Deletion-Reason"] = response.data.get("deletion_reason", "")
        payload.headers["X-Deletion-Confirmed"] = "true"

    # Check for active connections
    active_connections = await self._get_active_connections(server.id)
    if active_connections > 0:
        return ServerPreOperationResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Server has active connections",
                description=f"Cannot delete server with {active_connections} active connections",
                code="ACTIVE_CONNECTIONS_EXIST"
            )
        )

    return ServerPreOperationResult(modified_payload=payload)

# 2. Dependency validation
async def server_pre_delete(self, payload: ServerPreOperationPayload,
                           context: PluginContext) -> ServerPreOperationResult:
    server = payload.server_info

    # Check for dependent virtual servers
    dependent_servers = await self._find_dependent_servers(server.id)
    if dependent_servers:
        dependent_names = [s.name for s in dependent_servers]
        return ServerPreOperationResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Server has dependencies",
                description=f"Cannot delete server '{server.name}' - it's used by: {', '.join(dependent_names)}",
                code="DEPENDENCY_VIOLATION"
            )
        )

    # Check for referenced resources
    referenced_resources = await self._find_referencing_resources(server.id)
    if referenced_resources:
        return ServerPreOperationResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Server has resource dependencies",
                description=f"Server '{server.name}' is referenced by {len(referenced_resources)} resources",
                code="RESOURCE_DEPENDENCY_VIOLATION"
            )
        )

    return ServerPreOperationResult()
```

### Server Post-Delete Hook

**Function Signature**: `async def server_post_delete(self, payload: ServerPostOperationPayload, context: PluginContext) -> ServerPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_post_delete` | Hook identifier for configuration |
| **Execution Point** | After server deletion completes | When MCP server has been successfully removed |
| **Purpose** | Cleanup, notifications, audit logging | Handle post-deletion cleanup and notifications |

**Payload Attributes (`ServerPostOperationPayload`)** - Same structure as other post-hooks:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` |  | Deleted server information (if successful) | Contains information of deleted server |
| `operation_success` | `bool` | Yes | Whether deletion succeeded | `true` |
| `error_details` | `str` |  | Error details if deletion failed | `"Foreign key constraint violation"` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as other operations, **plus**:

  - `server_id` - ID of server that was deleted
  - `original_server_info` - Complete server state before deletion
  - Database timestamps reflect the deletion operation

**Return Type (`ServerPostOperationResult`)**:

- Extends `PluginResult[ServerPostOperationPayload]`
- Cannot modify server data (server is already deleted)
- Can trigger cleanup, notifications, and external integrations
- Violations in post-hooks log errors but don't affect the operation

**Example Use Cases**:

```python
# 1. Cleanup and notifications
async def server_post_delete(self, payload: ServerPostOperationPayload,
                            context: PluginContext) -> ServerPostOperationResult:
    if not payload.operation_success:
        # Log deletion failure
        self.logger.error(f"Server deletion failed: {context.server_audit_info.original_server_info.name}",
                         extra={
                             "error": payload.error_details,
                             "user": context.server_audit_info.created_by,
                             "server_id": context.server_audit_info.server_id
                         })
        return ServerPostOperationResult()

    deleted_server = context.server_audit_info.original_server_info

    # Clean up external resources
    await self._cleanup_server_resources(deleted_server.id)

    # Remove from discovery index
    await self._remove_from_discovery_index(deleted_server.id)

    # Invalidate all caches
    await self._invalidate_server_cache(deleted_server.id)
    await self._invalidate_tool_cache(deleted_server.id)
    await self._invalidate_resource_cache(deleted_server.id)

    # Send deletion notifications
    await self._notify_server_deletion({
        "server_id": deleted_server.id,
        "server_name": deleted_server.name,
        "deleted_by": context.server_audit_info.created_by,
        "deletion_reason": payload.headers.get("X-Deletion-Reason", ""),
        "timestamp": context.server_audit_info.operation_timestamp.isoformat()
    })

    # Archive server data for compliance
    if "production" in deleted_server.tags:
        await self._archive_server_data({
            "server_info": deleted_server.model_dump(),
            "deletion_audit": context.server_audit_info.model_dump(),
            "archived_at": context.server_audit_info.operation_timestamp
        })

    return ServerPostOperationResult()

# 2. Team and access management cleanup
async def server_post_delete(self, payload: ServerPostOperationPayload,
                            context: PluginContext) -> ServerPostOperationResult:
    if payload.operation_success and payload.server_info:
        deleted_server = payload.server_info

        # Remove team access permissions
        if context.server_audit_info.team_id:
            await self._revoke_team_access(deleted_server.id, context.server_audit_info.team_id)

        # Clean up user bookmarks/favorites
        await self._remove_user_bookmarks(deleted_server.id)

        # Update team server quotas
        await self._update_team_quota(context.server_audit_info.team_id, delta=-1)

        # Log compliance record
        self.logger.info(f"Server deleted: {deleted_server.name}",
                        extra={
                            "server_id": deleted_server.id,
                            "team_id": context.server_audit_info.team_id,
                            "deleted_by": context.server_audit_info.created_by,
                            "compliance_audit": True
                        })

    return ServerPostOperationResult()
```

### Server Pre-Status-Change Hook

**Function Signature**: `async def server_pre_status_change(self, payload: ServerPreOperationPayload, context: PluginContext) -> ServerPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_pre_status_change` | Hook identifier for configuration |
| **Execution Point** | Before server status toggle | When MCP server is about to be activated or deactivated |
| **Purpose** | Access control, dependency validation, impact assessment | Validate status change permissions and assess operational impact |

**Payload Attributes (`ServerPreOperationPayload`)** - Same structure as other pre-hooks:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` | Yes | Server information with target status | Contains server with desired `is_active` state |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as other operations, **plus**:

  - `server_id` - ID of server whose status is changing
  - `original_server_info` - Server state before status change (with current `is_active` value)

**Special Context Fields for Status Change:**

- `payload.server_info.is_active` - Target status (true = activating, false = deactivating)
- `context.server_audit_info.original_server_info.is_active` - Current status

**Return Type (`ServerPreOperationResult`)**:

- Extends `PluginResult[ServerPreOperationPayload]`
- Can modify status change behavior or add metadata
- Can block status changes with violation
- Can request client elicitation for impact confirmation

**Example Use Cases**:

```python
# 1. Production server deactivation protection
async def server_pre_status_change(self, payload: ServerPreOperationPayload,
                                  context: PluginContext) -> ServerPreOperationResult:
    server = payload.server_info
    original = context.server_audit_info.original_server_info

    # Determine the operation type
    is_activating = server.is_active and not original.is_active
    is_deactivating = not server.is_active and original.is_active

    # Protect production servers from deactivation
    if is_deactivating and "production" in server.tags:
        if not context.elicitation_responses:
            impact_schema = {
                "type": "object",
                "properties": {
                    "confirm_production_deactivation": {
                        "type": "boolean",
                        "description": f"Confirm deactivation of PRODUCTION server '{server.name}'"
                    },
                    "maintenance_window": {
                        "type": "string",
                        "description": "Scheduled maintenance window (if applicable)",
                        "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$"
                    },
                    "impact_assessment": {
                        "type": "string",
                        "description": "Impact assessment and mitigation plan",
                        "minLength": 20
                    }
                },
                "required": ["confirm_production_deactivation", "impact_assessment"]
            }

            return ServerPreOperationResult(
                continue_processing=False,
                elicitation_request=ElicitationRequest(
                    message=f"⚠️  PRODUCTION SERVER DEACTIVATION\n\nYou are about to deactivate production server '{server.name}'.\nThis may impact active users and integrations.",
                    schema=impact_schema,
                    timeout_seconds=300
                )
            )

        # Process confirmation
        response = context.elicitation_responses[0]
        if not response.data.get("confirm_production_deactivation"):
            return ServerPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Production deactivation cancelled",
                    description="User cancelled production server deactivation",
                    code="PRODUCTION_DEACTIVATION_CANCELLED"
                )
            )

        # Add impact assessment to audit
        payload.headers["X-Impact-Assessment"] = response.data.get("impact_assessment", "")
        payload.headers["X-Maintenance-Window"] = response.data.get("maintenance_window", "")

    # Check for dependent services during deactivation
    if is_deactivating:
        dependent_servers = await self._find_dependent_servers(server.id)
        if dependent_servers:
            dependent_names = [s.name for s in dependent_servers]
            return ServerPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Server has active dependencies",
                    description=f"Cannot deactivate '{server.name}' - it's required by: {', '.join(dependent_names)}",
                    code="DEPENDENCY_VIOLATION"
                )
            )

    return ServerPreOperationResult(modified_payload=payload)

# 2. Capacity and resource validation
async def server_pre_status_change(self, payload: ServerPreOperationPayload,
                                  context: PluginContext) -> ServerPreOperationResult:
    server = payload.server_info
    original = context.server_audit_info.original_server_info

    is_activating = server.is_active and not original.is_active

    if is_activating:
        # Check team server quotas
        if context.server_audit_info.team_id:
            active_count = await self._get_team_active_server_count(context.server_audit_info.team_id)
            team_limit = await self._get_team_server_limit(context.server_audit_info.team_id)

            if active_count >= team_limit:
                return ServerPreOperationResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Team server limit exceeded",
                        description=f"Team has {active_count}/{team_limit} active servers",
                        code="TEAM_QUOTA_EXCEEDED"
                    )
                )

        # Validate server health before activation
        health_check = await self._validate_server_health(server.uri)
        if not health_check.healthy:
            return ServerPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Server health check failed",
                    description=f"Cannot activate unhealthy server: {health_check.error}",
                    code="HEALTH_CHECK_FAILED"
                )
            )

    return ServerPreOperationResult()
```

### Server Post-Status-Change Hook

**Function Signature**: `async def server_post_status_change(self, payload: ServerPostOperationPayload, context: PluginContext) -> ServerPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `server_post_status_change` | Hook identifier for configuration |
| **Execution Point** | After server status change completes | When MCP server has been successfully activated or deactivated |
| **Purpose** | Monitoring, notifications, resource management | Handle post-status-change monitoring and resource adjustments |

**Payload Attributes (`ServerPostOperationPayload`)** - Same structure as other post-hooks:

| Attribute | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `server_info` | `ServerInfo` |  | Server information after status change (if successful) | Contains server with new `is_active` state |
| `operation_success` | `bool` | Yes | Whether status change succeeded | `true` |
| `error_details` | `str` |  | Error details if status change failed | `"Server health check timeout"` |
| `headers` | `HttpHeaderPayload` |  | HTTP headers for passthrough | `{"Authorization": "Bearer token123"}` |

**Context Information (`ServerAuditInfo`)** - Available in `context.server_audit_info`:

- Same fields as other operations, **plus**:

  - `server_id` - ID of server whose status changed
  - `original_server_info` - Server state before status change
  - Database timestamps reflect the status change operation

**Return Type (`ServerPostOperationResult`)**:

- Extends `PluginResult[ServerPostOperationPayload]`
- Cannot modify server data (status change is complete)
- Can trigger monitoring setup/teardown, notifications, and resource adjustments
- Violations in post-hooks log errors but don't affect the operation

**Example Use Cases**:

```python
# 1. Monitoring and notification management
async def server_post_status_change(self, payload: ServerPostOperationPayload,
                                   context: PluginContext) -> ServerPostOperationResult:
    if not payload.operation_success:
        # Log status change failure
        original = context.server_audit_info.original_server_info
        target_status = "activated" if context.elicitation_responses else "deactivated"
        self.logger.error(f"Server status change failed: {original.name} -> {target_status}",
                         extra={
                             "error": payload.error_details,
                             "user": context.server_audit_info.created_by,
                             "server_id": context.server_audit_info.server_id
                         })
        return ServerPostOperationResult()

    server = payload.server_info
    original = context.server_audit_info.original_server_info

    # Determine operation type
    was_activated = server.is_active and not original.is_active
    was_deactivated = not server.is_active and original.is_active

    if was_activated:
        # Setup monitoring for newly activated server
        await self._setup_server_monitoring(server.id, {
            "health_checks": True,
            "performance_metrics": True,
            "error_alerting": True
        })

        # Add to load balancer pool
        await self._add_to_load_balancer(server.id, server.uri)

        # Update discovery index
        await self._update_discovery_index(server.id, {"is_active": True})

        # Send activation notifications
        await self._notify_server_activated({
            "server_id": server.id,
            "server_name": server.name,
            "activated_by": context.server_audit_info.created_by,
            "team_id": context.server_audit_info.team_id,
            "timestamp": context.server_audit_info.operation_timestamp.isoformat()
        })

    elif was_deactivated:
        # Remove monitoring for deactivated server
        await self._teardown_server_monitoring(server.id)

        # Remove from load balancer pool
        await self._remove_from_load_balancer(server.id)

        # Update discovery index
        await self._update_discovery_index(server.id, {"is_active": False})

        # Send deactivation notifications
        await self._notify_server_deactivated({
            "server_id": server.id,
            "server_name": server.name,
            "deactivated_by": context.server_audit_info.created_by,
            "impact_assessment": payload.headers.get("X-Impact-Assessment", ""),
            "maintenance_window": payload.headers.get("X-Maintenance-Window", ""),
            "timestamp": context.server_audit_info.operation_timestamp.isoformat()
        })

    return ServerPostOperationResult()

# 2. Resource and capacity management
async def server_post_status_change(self, payload: ServerPostOperationPayload,
                                   context: PluginContext) -> ServerPostOperationResult:
    if payload.operation_success and payload.server_info:
        server = payload.server_info
        original = context.server_audit_info.original_server_info

        was_activated = server.is_active and not original.is_active
        was_deactivated = not server.is_active and original.is_active

        # Update team quotas and usage tracking
        if context.server_audit_info.team_id:
            if was_activated:
                await self._update_team_active_count(context.server_audit_info.team_id, delta=1)
            elif was_deactivated:
                await self._update_team_active_count(context.server_audit_info.team_id, delta=-1)

        # Update server metrics and analytics
        await self._record_status_change_metric({
            "server_id": server.id,
            "previous_status": original.is_active,
            "new_status": server.is_active,
            "team_id": context.server_audit_info.team_id,
            "changed_by": context.server_audit_info.created_by,
            "timestamp": context.server_audit_info.operation_timestamp
        })

        # Cache invalidation based on status change
        if was_activated or was_deactivated:
            await self._invalidate_server_cache(server.id)
            await self._invalidate_discovery_cache()

            # Invalidate team server lists
            if context.server_audit_info.team_id:
                await self._invalidate_team_server_cache(context.server_audit_info.team_id)

    return ServerPostOperationResult()
```

## Gateway Management Hooks

Gateway management hooks follow the same unified patterns as server hooks, using similar payload and context structures but for gateway federation operations.

### Unified Gateway Models

```python
class GatewayInfo(BaseModel):
    """Core gateway information - modifiable by plugins"""
    id: Optional[str] = Field(None, description="Gateway UUID identifier")
    name: str = Field(..., description="The gateway's name")
    description: Optional[str] = Field(None, description="Gateway description")
    url: str = Field(..., description="Gateway endpoint URL")
    transport: str = Field(default="SSE", description="Transport protocol (SSE, STREAMABLEHTTP)")
    auth_type: Optional[str] = Field(None, description="Authentication type (basic, bearer, headers, oauth)")
    auth_value: Optional[str] = Field(None, description="Authentication credentials")
    enabled: bool = Field(default=True, description="Whether gateway is enabled")
    reachable: bool = Field(default=True, description="Whether gateway is reachable")
    tags: List[str] = Field(default_factory=list, description="Gateway tags for categorization")
    # Team/tenant fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    visibility: str = Field(default="private", description="Visibility level (private, team, public)")

class GatewayAuditInfo(BaseModel):
    """Gateway audit/operational information - read-only across all gateway operations"""
    # Operation metadata
    operation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: Optional[str] = None                        # Unique request identifier

    # User and request info
    created_by: Optional[str] = None                        # User performing the operation
    created_from_ip: Optional[str] = None                   # Client IP address
    created_via: Optional[str] = None                       # Operation source ("api", "ui", "bulk_import", "federation")
    created_user_agent: Optional[str] = None                # Client user agent

    # Gateway state information
    gateway_id: Optional[str] = None                        # Target gateway ID (for updates/deletes)
    original_gateway_info: Optional[GatewayInfo] = None     # Original state (for updates/deletes)

    # Database timestamps (populated in post-hooks)
    created_at: Optional[datetime] = None                   # Gateway creation timestamp
    updated_at: Optional[datetime] = None                   # Gateway last update timestamp

    # Team/tenant context
    team_id: Optional[str] = None                           # Team performing operation
    tenant_id: Optional[str] = None                         # Tenant context

class GatewayPreOperationPayload(BaseModel):
    """Unified payload for gateway pre-operation hooks (register, update, etc.)"""
    gateway_info: GatewayInfo                               # Modifiable gateway information
    headers: HttpHeaderPayload = Field(default_factory=dict) # HTTP headers for passthrough

class GatewayPostOperationPayload(BaseModel):
    """Unified payload for gateway post-operation hooks (register, update, etc.)"""
    gateway_info: Optional[GatewayInfo] = None              # Complete gateway information (if successful)
    operation_success: bool                                 # Whether operation succeeded
    error_details: Optional[str] = None                     # Error details if operation failed
    headers: HttpHeaderPayload = Field(default_factory=dict) # HTTP headers for passthrough
```

### Gateway Pre-Register Hook

**Function Signature**: `async def gateway_pre_register(self, payload: GatewayPreOperationPayload, context: PluginContext) -> GatewayPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_pre_register` | Hook identifier for configuration |
| **Execution Point** | Before gateway registration | When administrator registers a new peer gateway |
| **Purpose** | Gateway validation, policy enforcement, configuration | Validate and transform gateway registration data |

**Context Information (`GatewayAuditInfo`)** - Available in `context.gateway_audit_info`:

- Operation metadata and user information
- For register operations: `gateway_id` and `original_gateway_info` are None

**Example Use Cases**:

```python
# 1. Gateway URL validation and security
async def gateway_pre_register(self, payload: GatewayPreOperationPayload,
                              context: PluginContext) -> GatewayPreOperationResult:
    gateway = payload.gateway_info

    # Validate gateway URL security
    if not gateway.url.startswith(('https://', 'http://localhost', 'http://127.0.0.1')):
        return GatewayPreOperationResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Insecure gateway URL",
                description="Gateway URLs must use HTTPS or localhost",
                code="INSECURE_GATEWAY_URL"
            )
        )

    # Check for federation loops
    if await self._would_create_federation_loop(gateway.url):
        return GatewayPreOperationResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Federation loop detected",
                description=f"Registering '{gateway.url}' would create a circular dependency",
                code="FEDERATION_LOOP_DETECTED"
            )
        )

    # Auto-configure transport based on URL patterns
    if "/sse" in gateway.url or "/events" in gateway.url:
        gateway.transport = "SSE"
    elif "/rpc" in gateway.url or "/jsonrpc" in gateway.url:
        gateway.transport = "STREAMABLEHTTP"

    return GatewayPreOperationResult(modified_payload=payload)
```

### Gateway Post-Register Hook

**Function Signature**: `async def gateway_post_register(self, payload: GatewayPostOperationPayload, context: PluginContext) -> GatewayPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_post_register` | Hook identifier for configuration |
| **Execution Point** | After gateway registration completes | When peer gateway has been successfully registered |
| **Purpose** | Discovery updates, health checks, federation setup | Initialize gateway federation and monitoring |

**Example Use Cases**:

```python
# 1. Gateway health check and federation initialization
async def gateway_post_register(self, payload: GatewayPostOperationPayload,
                               context: PluginContext) -> GatewayPostOperationResult:
    if not payload.operation_success:
        return GatewayPostOperationResult()

    gateway = payload.gateway_info

    # Start health monitoring for new gateway
    await self._setup_gateway_monitoring(gateway.id, {
        "health_check_interval": 30,  # seconds
        "timeout": 10,
        "retry_count": 3
    })

    # Initialize federation handshake
    try:
        capabilities = await self._perform_federation_handshake(gateway.url, gateway.auth_type, gateway.auth_value)
        await self._store_gateway_capabilities(gateway.id, capabilities)
    except Exception as e:
        self.logger.warning(f"Initial handshake failed for gateway {gateway.name}: {e}")

    # Add to federation discovery
    await self._update_federation_discovery({
        "gateway_id": gateway.id,
        "name": gateway.name,
        "url": gateway.url,
        "transport": gateway.transport,
        "registered_by": context.gateway_audit_info.created_by
    })

    return GatewayPostOperationResult()
```

### Gateway Pre-Update Hook

**Function Signature**: `async def gateway_pre_update(self, payload: GatewayPreOperationPayload, context: PluginContext) -> GatewayPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_pre_update` | Hook identifier for configuration |
| **Execution Point** | Before gateway update applies | When peer gateway configuration is being modified |
| **Purpose** | Validation, federation impact assessment | Validate gateway updates and assess federation implications |

**Context Information (`GatewayAuditInfo`)** - Available in `context.gateway_audit_info`:

- Same fields as register hooks, **plus**:

  - `gateway_id` - ID of gateway being updated
  - `original_gateway_info` - Gateway state before the update

**Example Use Cases**:

```python
# 1. Federation impact assessment for URL changes
async def gateway_pre_update(self, payload: GatewayPreOperationPayload,
                            context: PluginContext) -> GatewayPreOperationResult:
    gateway = payload.gateway_info
    original = context.gateway_audit_info.original_gateway_info

    # Detect critical federation changes
    critical_changes = []
    if original.url != gateway.url:
        critical_changes.append("federation URL")
    if original.transport != gateway.transport:
        critical_changes.append("transport protocol")
    if original.auth_type != gateway.auth_type:
        critical_changes.append("authentication method")

    # Request confirmation for critical changes
    if critical_changes and not context.elicitation_responses:
        confirmation_schema = {
            "type": "object",
            "properties": {
                "confirm_federation_changes": {
                    "type": "boolean",
                    "description": f"Confirm changes to: {', '.join(critical_changes)}"
                },
                "federation_impact": {
                    "type": "string",
                    "description": "Expected impact on federation and dependent services",
                    "minLength": 10
                }
            },
            "required": ["confirm_federation_changes", "federation_impact"]
        }

        return GatewayPreOperationResult(
            continue_processing=False,
            elicitation_request=ElicitationRequest(
                message=f"Critical federation changes detected for gateway '{gateway.name}'",
                schema=confirmation_schema,
                timeout_seconds=300
            )
        )

    # Validate new federation URL won't create loops
    if original.url != gateway.url:
        if await self._would_create_federation_loop(gateway.url):
            return GatewayPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Federation loop detected",
                    description=f"New URL '{gateway.url}' would create circular dependency",
                    code="FEDERATION_LOOP_DETECTED"
                )
            )

    return GatewayPreOperationResult(modified_payload=payload)
```

### Gateway Post-Update Hook

**Function Signature**: `async def gateway_post_update(self, payload: GatewayPostOperationPayload, context: PluginContext) -> GatewayPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_post_update` | Hook identifier for configuration |
| **Execution Point** | After gateway update completes | When peer gateway has been successfully updated |
| **Purpose** | Federation refresh, monitoring updates | Refresh federation connections and update monitoring |

**Example Use Cases**:

```python
# 1. Federation connection refresh after updates
async def gateway_post_update(self, payload: GatewayPostOperationPayload,
                             context: PluginContext) -> GatewayPostOperationResult:
    if not payload.operation_success:
        return GatewayPostOperationResult()

    gateway = payload.gateway_info
    original = context.gateway_audit_info.original_gateway_info

    # Refresh federation connection if critical fields changed
    if (original.url != gateway.url or
        original.auth_type != gateway.auth_type or
        original.transport != gateway.transport):

        try:
            # Re-establish federation connection
            await self._refresh_federation_connection(gateway.id, gateway.url, gateway.auth_type, gateway.auth_value)

            # Update capabilities
            capabilities = await self._perform_federation_handshake(gateway.url, gateway.auth_type, gateway.auth_value)
            await self._store_gateway_capabilities(gateway.id, capabilities)

        except Exception as e:
            self.logger.error(f"Failed to refresh federation for {gateway.name}: {e}")

    # Update discovery index
    await self._update_federation_discovery({
        "gateway_id": gateway.id,
        "name": gateway.name,
        "url": gateway.url,
        "transport": gateway.transport,
        "updated_by": context.gateway_audit_info.created_by
    })

    return GatewayPostOperationResult()
```

### Gateway Pre-Delete Hook

**Function Signature**: `async def gateway_pre_delete(self, payload: GatewayPreOperationPayload, context: PluginContext) -> GatewayPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_pre_delete` | Hook identifier for configuration |
| **Execution Point** | Before gateway deletion | When peer gateway is about to be removed from federation |
| **Purpose** | Federation dependency checks, graceful disconnection | Validate safe removal from federation |

**Example Use Cases**:

```python
# 1. Federation dependency validation
async def gateway_pre_delete(self, payload: GatewayPreOperationPayload,
                            context: PluginContext) -> GatewayPreOperationResult:
    gateway = payload.gateway_info

    # Check for active federated tools/resources
    active_tools = await self._get_federated_tools(gateway.id)
    active_resources = await self._get_federated_resources(gateway.id)

    if active_tools or active_resources:
        if not context.elicitation_responses:
            dependency_schema = {
                "type": "object",
                "properties": {
                    "confirm_federation_removal": {
                        "type": "boolean",
                        "description": f"Remove gateway with {len(active_tools)} tools and {len(active_resources)} resources"
                    },
                    "migration_plan": {
                        "type": "string",
                        "description": "Plan for migrating dependent services",
                        "minLength": 20
                    }
                },
                "required": ["confirm_federation_removal", "migration_plan"]
            }

            return GatewayPreOperationResult(
                continue_processing=False,
                elicitation_request=ElicitationRequest(
                    message=f"Gateway '{gateway.name}' provides {len(active_tools)} tools and {len(active_resources)} resources to this federation",
                    schema=dependency_schema,
                    timeout_seconds=300
                )
            )

    return GatewayPreOperationResult(modified_payload=payload)
```

### Gateway Post-Delete Hook

**Function Signature**: `async def gateway_post_delete(self, payload: GatewayPostOperationPayload, context: PluginContext) -> GatewayPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_post_delete` | Hook identifier for configuration |
| **Execution Point** | After gateway deletion completes | When peer gateway has been successfully removed |
| **Purpose** | Federation cleanup, monitoring teardown | Clean up federation artifacts and monitoring |

**Example Use Cases**:

```python
# 1. Federation cleanup after gateway removal
async def gateway_post_delete(self, payload: GatewayPostOperationPayload,
                             context: PluginContext) -> GatewayPostOperationResult:
    if not payload.operation_success:
        return GatewayPostOperationResult()

    deleted_gateway = context.gateway_audit_info.original_gateway_info

    # Remove from federation discovery
    await self._remove_from_federation_discovery(deleted_gateway.id)

    # Clean up federated resources
    await self._cleanup_federated_tools(deleted_gateway.id)
    await self._cleanup_federated_resources(deleted_gateway.id)
    await self._cleanup_federated_prompts(deleted_gateway.id)

    # Teardown monitoring
    await self._teardown_gateway_monitoring(deleted_gateway.id)

    # Invalidate federation caches
    await self._invalidate_federation_cache()

    # Send federation removal notification
    await self._notify_federation_removal({
        "gateway_id": deleted_gateway.id,
        "gateway_name": deleted_gateway.name,
        "gateway_url": deleted_gateway.url,
        "removed_by": context.gateway_audit_info.created_by
    })

    return GatewayPostOperationResult()
```

### Gateway Pre-Status-Change Hook

**Function Signature**: `async def gateway_pre_status_change(self, payload: GatewayPreOperationPayload, context: PluginContext) -> GatewayPreOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_pre_status_change` | Hook identifier for configuration |
| **Execution Point** | Before gateway status toggle | When peer gateway is about to be enabled or disabled |
| **Purpose** | Federation impact assessment, dependency validation | Validate status changes and assess federation impact |

**Example Use Cases**:

```python
# 1. Federation impact assessment for status changes
async def gateway_pre_status_change(self, payload: GatewayPreOperationPayload,
                                   context: PluginContext) -> GatewayPreOperationResult:
    gateway = payload.gateway_info
    original = context.gateway_audit_info.original_gateway_info

    is_disabling = not gateway.enabled and original.enabled

    if is_disabling:
        # Check federation impact
        dependent_services = await self._get_federation_dependents(gateway.id)
        if dependent_services:
            service_names = [s.name for s in dependent_services]
            return GatewayPreOperationResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Gateway has federation dependencies",
                    description=f"Cannot disable gateway - required by: {', '.join(service_names)}",
                    code="FEDERATION_DEPENDENCY_VIOLATION"
                )
            )

    return GatewayPreOperationResult(modified_payload=payload)
```

### Gateway Post-Status-Change Hook

**Function Signature**: `async def gateway_post_status_change(self, payload: GatewayPostOperationPayload, context: PluginContext) -> GatewayPostOperationResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| **Hook Name** | `gateway_post_status_change` | Hook identifier for configuration |
| **Execution Point** | After gateway status change completes | When peer gateway has been successfully enabled or disabled |
| **Purpose** | Federation connection management, monitoring updates | Manage federation connections and update monitoring |

**Example Use Cases**:

```python
# 1. Federation connection management
async def gateway_post_status_change(self, payload: GatewayPostOperationPayload,
                                    context: PluginContext) -> GatewayPostOperationResult:
    if not payload.operation_success:
        return GatewayPostOperationResult()

    gateway = payload.gateway_info
    original = context.gateway_audit_info.original_gateway_info

    was_enabled = gateway.enabled and not original.enabled
    was_disabled = not gateway.enabled and original.enabled

    if was_enabled:
        # Re-establish federation connection
        await self._activate_federation_connection(gateway.id)

        # Update discovery index
        await self._update_federation_discovery(gateway.id, {"enabled": True})

    elif was_disabled:
        # Gracefully close federation connection
        await self._deactivate_federation_connection(gateway.id)

        # Update discovery index
        await self._update_federation_discovery(gateway.id, {"enabled": False})

    return GatewayPostOperationResult()
```

## Administrative Hook Categories

The gateway administrative hooks are organized into the following categories:

### Server Management Hooks
- `server_pre_register` - Before server registration
- `server_post_register` - After server registration
- `server_pre_update` - Before server configuration updates
- `server_post_update` - After server updates
- `server_pre_delete` - Before server deletion
- `server_post_delete` - After server removal
- `server_pre_status_change` - Before server activation/deactivation
- `server_post_status_change` - After server status changes

### Gateway Federation Hooks
- `gateway_pre_register` - Before peer gateway registration
- `gateway_post_register` - After peer gateway registration
- `gateway_pre_update` - Before gateway configuration updates
- `gateway_post_update` - After gateway updates
- `gateway_pre_delete` - Before peer gateway removal
- `gateway_post_delete` - After peer gateway removal
- `gateway_pre_status_change` - Before gateway activation/deactivation
- `gateway_post_status_change` - After gateway status changes

### A2A Agent Management Hooks *(Future)*
- `a2a_pre_register` - Before A2A agent registration
- `a2a_post_register` - After A2A agent registration
- `a2a_pre_invoke` - Before A2A agent invocation
- `a2a_post_invoke` - After A2A agent execution

### Entity Lifecycle Hooks *(Future)*
- `tool_pre_register` - Before tool catalog registration
- `tool_post_register` - After tool registration
- `resource_pre_register` - Before resource registration
- `resource_post_register` - After resource registration
- `prompt_pre_register` - Before prompt registration
- `prompt_post_register` - After prompt registration

## Performance Considerations

| Hook Category | Typical Latency | Performance Impact | Recommended Limits |
|---------------|----------------|-------------------|-------------------|
| Server Management | 1-5ms | Low | <10ms per hook |
| Gateway Federation | 10-100ms | Medium | Network dependent |
| Entity Registration | <1ms | Minimal | <5ms per hook |

**Best Practices**:

- Keep administrative hooks lightweight and fast
- Use async operations for external integrations
- Implement proper timeout handling for elicitations
- Cache frequently accessed data (permissions, quotas)
- Use background tasks for non-critical operations
