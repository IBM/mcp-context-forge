# IBM API Connect Federated API Management Plugin

> Author: Shankar N
> Version: 1.0.0

The IBM API Connect Federated API Management (FAM) Plugin serves as a MCP ContextForge agent that connects ContextForge's MCP runtime infrastructure with IBM API Connect's Federated API Management platform. It enables automated, resilient, and observable synchronization of MCP servers, tools, and runtime metadata from ContextForge into FAM's centralized governance platform.

## Features

### Automated Synchronization
- **Runtime Registration**: Automatic registration with FAM on startup
- **Server Sync**: Continuous synchronization of MCP virtual servers
- **Tool Sync**: Real-time updates of tool definitions and metadata
- **Metrics Collection**: Periodic metrics aggregation and reporting

### Observability
- **Per-Activity Statistics**: Detailed tracking of each sync operation
- **Health Monitoring**: Real-time health status and failure detection
- **Audit Trail**: Complete tracking of all synchronization operations



## Architecture


```
plugins/apiconnect_fam/
├── __init__.py                      # Package initialization
├── apiconnect_fam.py                # Main plugin class (orchestration)
├── activity_orchestrator.py         # Activity scheduling and execution
├── circuit_breaker.py               # Circuit breaker implementation
├── models.py                        # Data models and schemas
├── plugin-manifest.yaml             # Plugin configuration schema
├── activities/                      # Activity implementations
│   ├── base.py                      # Base activity class
│   ├── register_runtime.py          # Runtime registration
│   ├── send_heartbeat.py            # Heartbeat monitoring
│   ├── send_metrics.py              # Metrics collection
│   ├── sync_servers.py              # Server synchronization
│   ├── sync_tools.py                # Tool synchronization
│   └── state_tracker.py             # State tracking and recovery
├── fam/                             # FAM API client
│   ├── client.py                    # HTTP client implementation
│   ├── endpoints.py                 # API endpoint definitions
│   └── payloads/                    # Request/response payloads
│       ├── runtime.py               # Runtime payloads
│       ├── server.py                # Server payloads
│       ├── tool.py                  # Tool payloads
│       └── metrics.py               # Metrics payloads
└──  utils/                           # Utility modules
    ├── errors.py                    # Error definitions
    └── retry.py                     # Retry logic
```

## Quick Start

### 1. Enable Plugins

Edit your `.env` file:

```bash
# Enable plugin system
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml

# Set log level to see plugin output
LOG_LEVEL=INFO
```

### 2. Configure the Plugin

The plugin is pre-configured in `plugins/config.yaml`. Update the FAM settings:

```yaml
plugins:
  - name: "APIConnectFAM"
    kind: "plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin"
    mode: "permissive"
    priority: 1000
    config:
      # Core settings
      interval_seconds: 60
      log_details: true
      
      # FAM integration (REQUIRED)
      fam_enabled: true
      fam_base_url: "https://fam.example.com"
      fam_runtime_id: "your-runtime-id"  # REQUIRED
      
      # Authentication - choose one method:
      # Option 1: Basic Authentication (default)
      fam_auth_type: "basic"
      fam_username: "admin"
      fam_password: "changeme"
      
      # Option 2: API Key Authentication
      # fam_auth_type: "apikey"
      # fam_api_key: "your-api-key-here"
      # fam_client_id: "your-client-id-here"
      
      fam_timeout: 30
      fam_verify_ssl: true
      
      # Synchronization intervals
      fam_asset_sync_enabled: true
      fam_asset_sync_interval: 60
      metrics_sync_enabled: true
      metrics_sync_interval: 300
      
      # Circuit breaker
      circuit_breaker_enabled: true
      circuit_breaker_failure_threshold: 5
      circuit_breaker_recovery_timeout: 60.0
```

### Authentication Methods

The plugin supports two authentication methods:

#### Basic Authentication (Default)
Uses HTTPs Basic Authentication with username and password:

```yaml
fam_auth_type: "basic"
fam_username: "admin"
fam_password: "changeme"
```

#### API Key Authentication
Uses API key and client ID to obtain a bearer token:

```yaml
fam_auth_type: "apikey"
fam_api_key: "your-api-key-here"
fam_client_id: "your-client-id-here"
```


## Configuration Reference

### Core Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interval_seconds` | int | 60 | Base interval for background operations |
| `log_details` | bool | true | Enable detailed logging |

### FAM Integration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fam_enabled` | bool | false | Enable FAM synchronization |
| `fam_base_url` | string | - | FAM API base URL (REQUIRED) |
| `fam_runtime_id` | string | - | Runtime identifier (REQUIRED) |
| `fam_auth_type` | string | "basic" | Authentication type: "basic" or "apikey" |
| `fam_username` | string | - | Basic auth username (required if auth_type=basic) |
| `fam_password` | string | - | Basic auth password (required if auth_type=basic) |
| `fam_api_key` | string | - | API key (required if auth_type=apikey) |
| `fam_client_id` | string | - | Client ID (required if auth_type=apikey) |
| `fam_timeout` | int | 30 | HTTP request timeout (seconds) |
| `fam_verify_ssl` | bool | true | Verify SSL certificates |

### Synchronization

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fam_asset_sync_enabled` | bool | true | Enable server/tool sync |
| `fam_asset_sync_interval` | int | 60 | Asset sync interval (seconds) |
| `metrics_sync_enabled` | bool | false | Enable metrics sync |
| `metrics_sync_interval` | int | 300 | Metrics sync interval (seconds) |

### Resilience

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `circuit_breaker_enabled` | bool | true | Enable circuit breaker |
| `circuit_breaker_failure_threshold` | int | 5 | Failures before opening circuit |
| `circuit_breaker_recovery_timeout` | float | 60.0 | Recovery timeout (seconds) |

### Runtime Metadata

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fam_runtime_name` | string | "ContextForge Gateway" | Display name |
| `fam_runtime_description` | string | - | Runtime description |
| `fam_runtime_deployment_type` | string | "ON_PREMISE" | Deployment type |
| `fam_runtime_region` | string | null | Region identifier |
| `fam_runtime_location` | string | null | Location description |
| `fam_runtime_host` | string | null | Host identifier |
| `fam_runtime_tags` | list | ["contextforge", "mcp"] | Runtime tags |

## Troubleshooting

### Plugin Not Loading

1. Check `PLUGINS_ENABLED=true` in `.env`
2. Verify `PLUGINS_CONFIG_FILE=plugins/config.yaml`
3. Check for syntax errors in `plugins/config.yaml`
4. Look for error messages in logs

### FAM Connection Issues

1. **401 Unauthorized**:
   - For Basic Auth: Check username/password
   - For API Key Auth: Verify api_key and client_id are correct
   - Check that the authentication method matches FAM server configuration
2. **404 Not Found**: Verify `fam_base_url` and `fam_runtime_id`
3. **Connection Timeout**: Check network connectivity and `fam_timeout`
4. **SSL Errors**: Set `fam_verify_ssl: false` for self-signed certs
5. **Token Fetch Failures** (API Key Auth):
   - Check that API key and client ID have proper permissions
   - Review logs for detailed error messages with status codes

### Circuit Breaker Opened

1. Check FAM service availability
2. Review failure logs for root cause
3. Wait for recovery timeout (default 60s)
4. Verify network connectivity

### Missing Synchronization

1. Check `fam_asset_sync_enabled: true`
2. Verify sync intervals are appropriate
3. Review logs for sync errors
4. Check circuit breaker state

For detailed troubleshooting, see [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Development

### Running Tests

```bash
# Run plugin tests
pytest tests/unit/mcpgateway/plugins/apiconnect_fam/ -v

# Run with coverage
pytest tests/unit/mcpgateway/plugins/apiconnect_fam/ --cov=plugins/apiconnect_fam
```

### Debug Logging

Enable debug logging in `.env`:

```bash
LOG_LEVEL=DEBUG
```