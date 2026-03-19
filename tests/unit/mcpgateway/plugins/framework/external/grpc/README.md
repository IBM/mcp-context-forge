# gRPC External Plugin Tests

This directory contains tests for the gRPC transport layer of the external plugin framework.

## Test Files

### `test_client.py` - Unit Tests (Mocked)

Unit tests for `GrpcExternalPlugin` client using mocks. No real server is started.

| Test | Description |
|------|-------------|
| **TestGrpcExternalPluginInit** | |
| `test_init_with_config` | Verifies plugin initializes with name and null channel/stub |
| `test_init_stores_config` | Verifies gRPC config (target address) is stored |
| **TestGrpcExternalPluginInitialize** | |
| `test_initialize_missing_grpc_config` | Raises `PluginError` when grpc config section is missing |
| `test_initialize_creates_channel` | Creates insecure gRPC channel and stub on init |
| `test_initialize_with_tls` | Creates secure channel when TLS config is present |
| `test_initialize_with_uds` | Uses `unix://` target format for Unix domain sockets |
| `test_initialize_config_retrieval_failure` | Raises `PluginError` when remote config not found |
| `test_initialize_connection_error` | Handles gRPC connection errors gracefully |
| **TestGrpcExternalPluginInvokeHook** | |
| `test_invoke_hook_success` | Successfully invokes hook and returns result |
| `test_invoke_hook_stub_not_initialized` | Raises error when stub not initialized |
| `test_invoke_hook_error_response` | Handles error responses from server |
| `test_invoke_hook_grpc_error` | Handles gRPC-level errors (network issues) |
| `test_invoke_hook_unregistered_hook_type` | Raises error for unknown hook types |
| `test_invoke_hook_updates_context` | Context state is updated from server response |
| **TestGrpcExternalPluginShutdown** | |
| `test_shutdown_closes_channel` | Channel is closed and references cleared |
| `test_shutdown_no_channel` | Safe to call when not connected |
| `test_shutdown_idempotent` | Multiple shutdown calls don't raise errors |
| **TestGrpcExternalPluginRetry** | |
| `test_get_plugin_config_with_retry_success` | Config retrieval succeeds on first attempt |
| `test_get_plugin_config_with_retry_eventual_success` | Retries and succeeds after failures |
| `test_get_plugin_config_with_retry_all_failures` | Raises after max retry attempts |

### `test_client_integration.py` - Integration Tests (Real Server)

Integration tests that spawn a real gRPC server subprocess and test actual communication.

**Direct Plugin Tests:**

| Test | Description |
|------|-------------|
| `test_grpc_client_invoke_hook` | Invokes `prompt_pre_fetch` hook over TCP, verifies word replacement ("crap" → "yikes") |
| `test_grpc_client_post_hook` | Invokes `prompt_post_fetch` hook, verifies message text transformation |
| `test_grpc_client_context_propagation` | Verifies request_id, server_id, user, tenant_id are passed through |
| `test_grpc_client_over_uds` | Tests gRPC communication over Unix domain socket (skipped on Windows) |

**PluginManager Tests:**

| Test | Description |
|------|-------------|
| `test_grpc_plugin_manager_invoke_hook` | Tests PluginManager loading and invoking hooks through gRPC external plugin |
| `test_grpc_plugin_manager_multiple_hooks` | Tests PluginManager invoking both pre-fetch and post-fetch hooks |
| `test_grpc_plugin_manager_context_persistence` | Tests context persistence across multiple PluginManager calls |

### `test_grpc_models.py` - Model Tests

Tests for gRPC-related Pydantic models (`GRPCClientConfig`, `GRPCServerConfig`, etc.).

### `test_tls_utils.py` - TLS Utility Tests

Tests for TLS certificate loading and credential creation utilities.

### `server/test_server.py` - Server Unit Tests (Mocked)

Unit tests for `GrpcPluginServicer` and `GrpcHealthServicer`.

| Test | Description |
|------|-------------|
| **TestGrpcPluginServicerGetPluginConfig** | |
| `test_get_plugin_config_found` | Returns config when plugin exists |
| `test_get_plugin_config_not_found` | Returns `found=False` when plugin doesn't exist |
| **TestGrpcPluginServicerGetPluginConfigs** | |
| `test_get_plugin_configs_empty` | Returns empty list when no plugins |
| `test_get_plugin_configs_multiple` | Returns all plugin configs |
| **TestGrpcPluginServicerInvokeHook** | |
| `test_invoke_hook_success` | Returns successful result with continue_processing |
| `test_invoke_hook_with_error` | Returns PluginError details in response |
| `test_invoke_hook_with_context_update` | Includes updated context in response |
| `test_invoke_hook_unexpected_error` | Handles unexpected exceptions gracefully |
| **TestGrpcHealthServicer** | |
| `test_check_serving` | Returns SERVING when plugins loaded |
| `test_check_always_serving` | Returns SERVING even with no plugins |
| `test_check_with_service_name` | Handles specific service name requests |
| **TestGrpcPluginServicerEdgeCases** | |
| `test_invoke_hook_with_violation` | Handles results containing policy violations |
| `test_invoke_hook_with_modified_payload` | Handles results with transformed payloads |

### `server/test_runtime.py` - Runtime Tests

Tests for the gRPC server runtime entry point and configuration.

## Running Tests

```bash
# Run all gRPC tests
pytest tests/unit/mcpgateway/plugins/framework/external/grpc/ -v

# Run only unit tests (fast, no subprocess)
pytest tests/unit/mcpgateway/plugins/framework/external/grpc/test_client.py -v

# Run only integration tests (spawns real server)
pytest tests/unit/mcpgateway/plugins/framework/external/grpc/test_client_integration.py -v
```

## Test Fixtures

- `grpc_server_proc`: Starts gRPC server on random TCP port
- `grpc_server_proc_uds`: Starts gRPC server on Unix domain socket
- `mock_plugin_config`: Creates test PluginConfig with gRPC target
- `mock_plugin_config_uds`: Creates test PluginConfig with UDS path
