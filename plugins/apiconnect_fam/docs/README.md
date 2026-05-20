# API Connect FAM Plugin

A ContextForge plugin that periodically monitors all virtual servers in the system and optionally syncs them to FAM (Federated API Management).

## Architecture

The plugin follows enterprise-level design patterns with clear separation of concerns:

```
plugins/apiconnect_fam/
├── __init__.py              # Package initialization
├── apiconnect_fam.py        # Main plugin class (orchestration)
├── fam_client.py           # FAM API client (business logic)
├── README.md               # This file
├── SETUP.md                # Setup instructions
└── TROUBLESHOOTING.md      # Troubleshooting guide
```

### Components

**APIConnectFAMPlugin** (`apiconnect_fam.py`)
- Orchestrates the monitoring and sync workflow
- Manages background task lifecycle
- Handles database queries
- Delegates FAM operations to client

**FAMAssetCatalogClient** (`fam_client.py`)
- Encapsulates FAM API communication
- Handles HTTP requests with proper error handling
- Implements retry logic and logging

**FAMServerPayload** (`fam_client.py`)
- Builds API payloads following OpenAPI spec
- Enforces data type constraints
- Maps ContextForge fields to FAM fields

**ServerStateTracker** (`fam_client.py`)
- Tracks server state using content hashing
- Detects changes for smart syncing
- Maintains cache of synced servers

## Features

- **Periodic Monitoring**: Runs in the background at configurable intervals
- **Detailed Logging**: Logs comprehensive server information including:
  - Server name, ID, and status (enabled/disabled)
  - Description and tags
  - Creation timestamp
  - Associated items count (tools, resources, prompts)
- **Summary Statistics**: Provides counts of total, enabled, and disabled servers
- **FAM Synchronization**: Automatically syncs servers to FAM API with:
  - Change detection using SHA-256 content hashing
  - Smart sync operations (POST for new, PUT for updates, DELETE for removed)
  - Local caching to minimize unnecessary API calls
  - Configurable FAM endpoint and authentication
  - Strict OpenAPI spec compliance
- **Enterprise-Grade**: Clean architecture, proper error handling, comprehensive logging

## Configuration

Add to `plugins/config.yaml`:

```yaml
plugins:
  - name: "APIConnectFAM"
    kind: "plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin"
    hooks: []  # No hooks, uses background task
    mode: "permissive"
    priority: 1000
    config:
      interval_seconds: 60  # How often to sync/log servers (in seconds)
      log_details: true     # Whether to log detailed server information
      # FAM sync configuration
      fam_enabled: false    # Enable FAM synchronization
      fam_base_url: "https://fam.example.com"
      fam_runtime_id: "your-runtime-id"
      fam_auth_token: "your-bearer-token"
      fam_timeout: 30       # HTTP request timeout in seconds
```

## Configuration Options

- `interval_seconds` (int, default: 60): How often to check and sync servers
- `log_details` (bool, default: true): Whether to include detailed information for each server
- `fam_enabled` (bool, default: false): Enable synchronization to FAM
- `fam_base_url` (str, optional): Base URL for FAM API (e.g., https://fam.example.com)
- `fam_runtime_id` (str, optional): Runtime ID to use when syncing to FAM
- `fam_auth_token` (str, optional): Bearer token for FAM API authentication
- `fam_timeout` (int, default: 30): HTTP request timeout in seconds

## Usage

### Basic Monitoring (No FAM Sync)

1. Enable the plugin in `plugins/config.yaml`
2. Set `PLUGINS_ENABLED=true` in your `.env` file
3. Start ContextForge with `make dev`
4. Monitor logs to see server information

### With FAM Synchronization

1. Configure FAM settings in `plugins/config.yaml`:
   ```yaml
   config:
     fam_enabled: true
     fam_base_url: "https://your-fam-instance.com"
     fam_runtime_id: "prod-runtime-001"
     fam_auth_token: "your-actual-bearer-token"
   ```
2. Enable the plugin and start ContextForge
3. The plugin will automatically:
   - Detect new servers and POST them to FAM
   - Detect changed servers and PUT updates to FAM
   - Detect deleted servers and DELETE them from FAM
   - Cache server state to minimize unnecessary API calls

## FAM Sync Behavior

The plugin maintains a local cache of server state and intelligently syncs changes:

- **New Servers**: When a server appears in the database that hasn't been synced, a POST request creates it in FAM
- **Updated Servers**: When a server's content changes (name, description, tags, etc.), a PUT request updates it in FAM
- **Deleted Servers**: When a server is removed from the database, a DELETE request removes it from FAM
- **No Change**: If a server hasn't changed since the last sync, no API call is made

### Server Hash Calculation

Changes are detected by computing a SHA-256 hash of:
- Server name
- Description
- Enabled status
- Tags (sorted)
- Tool count
- Resource count
- Prompt count

## Example Output

### Without FAM Sync
```
INFO: Initializing APIConnectFAMPlugin with interval=60s
INFO: Virtual Servers Summary: Total=3, Enabled=2, Disabled=1
INFO: ================================================================================
INFO:   [ENABLED] Production API (ID: abc123)
INFO:     Description: Main production API server
INFO:     Created: 2025-01-15 10:30:00
INFO:     Tags: production, api
INFO:     Items: 15 tools, 5 resources, 3 prompts
INFO: --------------------------------------------------------------------------------
INFO:   [ENABLED] Development Server (ID: def456)
INFO:     Description: Development environment
INFO:     Created: 2025-01-16 14:20:00
INFO:     Tags: development
INFO:     Items: 8 tools, 2 resources, 1 prompts
INFO: --------------------------------------------------------------------------------
INFO:   [DISABLED] Test Server (ID: ghi789)
INFO:     Created: 2025-01-17 09:15:00
INFO:     Items: 3 tools, 1 resources, 0 prompts
INFO: --------------------------------------------------------------------------------
INFO: ================================================================================
```

### With FAM Sync Enabled
```
INFO: Initializing APIConnectFAMPlugin with interval=60s
INFO: FAM sync enabled - HTTP client initialized
INFO: Created MCP Server abc123 in FAM
INFO: Updated MCP Server def456 in FAM
INFO: Virtual Servers Summary: Total=3, Enabled=2, Disabled=1
...
```

## FAM API Integration

The plugin uses the FAM Asset Catalog API v1 endpoints as defined in the OpenAPI specification:

- **POST** `/api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers` - Create new MCP Server
- **PUT** `/api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{id}` - Update MCP Server
- **DELETE** `/api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{id}` - Delete MCP Server

All requests include:
- `Authorization: Bearer {token}` header (JWT)
- `Content-Type: application/json` header

### MCP Server Create Payload (MCPServerCreate schema)

```json
{
  "mcpServerId": "server-abc123",
  "name": "Production MCP Server",
  "description": "Main production AI model server",
  "status": "ACTIVE",
  "capabilities": ["TOOLS", "RESOURCES", "PROMPTS"],
  "tags": ["production", "ai", "primary"]
}
```

### MCP Server Update Payload (MCPServerUpdate schema)

```json
{
  "name": "Updated Production MCP Server",
  "description": "Updated description",
  "status": "INACTIVE",
  "capabilities": ["TOOLS", "PROMPTS"],
  "tags": ["production", "ai", "updated"]
}
```

### Field Mappings

| ContextForge Field | FAM Field | Type | Constraints |
|-------------------|-----------|------|-------------|
| `server.id` | `mcpServerId` | string | Pattern: `^[a-zA-Z0-9_:-]+$`, 1-255 chars |
| `server.name` | `name` | string | 1-255 chars |
| `server.description` | `description` | string | Max 1000 chars |
| `server.enabled` | `status` | AssetStatus | ACTIVE/INACTIVE/DEPRECATED |
| `server.tags` | `tags` | string[] | Max 50 items |
| `server.tools` | `capabilities` | MCPCapability[] | Auto-detected |
| `server.resources` | `capabilities` | MCPCapability[] | Auto-detected |
| `server.prompts` | `capabilities` | MCPCapability[] | Auto-detected |

### Capabilities Detection

The plugin automatically determines MCP Server capabilities based on associated items:
- **TOOLS**: Added if server has tools
- **RESOURCES**: Added if server has resources  
- **PROMPTS**: Added if server has prompts

### Status Mapping

- ContextForge `enabled=true` → FAM `status="ACTIVE"`
- ContextForge `enabled=false` → FAM `status="INACTIVE"`

## Error Handling

The plugin implements comprehensive error handling:

- **HTTP Errors**: Logged with status code and response body
- **Connection Errors**: Logged with retry information
- **Validation Errors**: Caught during payload building
- **Database Errors**: Handled gracefully without crashing the plugin

All errors are logged but don't stop the monitoring loop.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and solutions.

### FAM Sync Issues

If FAM sync is not working:

1. **Check Configuration**: Ensure `fam_enabled: true` and all FAM settings are correct
2. **Verify Authentication**: Test your bearer token with a manual API call:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
        https://fam.example.com/api/assetcatalog/v1/runtimes/YOUR_RUNTIME_ID/mcp-servers
   ```
3. **Check Logs**: Look for FAM sync error messages in the logs
4. **Network Connectivity**: Ensure ContextForge can reach the FAM API endpoint
5. **API Compatibility**: Verify your FAM instance supports the Asset Catalog API v1

### Common Error Messages

- `FAM API error creating server X: status=401` - Invalid or expired bearer token
- `FAM API error updating server X: status=404` - Server doesn't exist in FAM (will retry as create)
- `HTTP error deleting server X from FAM` - Network connectivity issue
- `FAM sync enabled but configuration incomplete` - Missing required FAM configuration

## Development

### Code Structure

The plugin follows clean architecture principles:

1. **Separation of Concerns**: Plugin orchestration separate from API client logic
2. **Single Responsibility**: Each class has one clear purpose
3. **Dependency Injection**: FAM client injected into plugin
4. **Error Boundaries**: Errors contained and logged appropriately
5. **Type Safety**: Full type hints throughout
6. **Documentation**: Comprehensive docstrings and comments

### Testing

To test the plugin:

```bash
# Run with debug logging
LOG_LEVEL=DEBUG make dev

# Check plugin initialization
grep "APIConnectFAMPlugin" logs/mcpgateway.log

# Verify FAM sync (if enabled)
grep "FAM" logs/mcpgateway.log
```

## Notes

- The plugin uses a background asyncio task that runs independently
- Database queries are performed in a separate session to avoid blocking
- FAM sync operations are best-effort and don't block the monitoring loop
- Errors in the monitoring or sync loop are logged but don't crash the plugin
- The plugin gracefully shuts down when the server stops
- HTTP client is automatically closed on shutdown
- All data types strictly follow the OpenAPI specification