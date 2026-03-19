# Unix Socket External Plugin Tests

This directory contains tests for the Unix socket transport layer of the external plugin framework. Unix sockets provide high-performance local IPC using length-prefixed protobuf messages.

## Test Files

### `test_client.py` - Unit Tests (Mocked)

Unit tests for `UnixSocketExternalPlugin` client using mocks. No real server is started.

| Test | Description |
|------|-------------|
| **TestUnixSocketExternalPluginInit** | |
| `test_init_with_config` | Verifies plugin initializes with name and null reader/writer |
| `test_init_stores_socket_config` | Verifies socket path, timeout, retry settings are stored |
| `test_init_missing_unix_socket_config` | Raises `PluginError` when unix_socket config missing |
| **TestUnixSocketExternalPluginConnected** | |
| `test_connected_false_when_not_connected` | Returns False when `_connected` is False |
| `test_connected_false_when_writer_none` | Returns False when writer is None |
| `test_connected_false_when_writer_closing` | Returns False when writer.is_closing() is True |
| `test_connected_true_when_active` | Returns True when properly connected |
| **TestUnixSocketExternalPluginInitialize** | |
| `test_initialize_connects_to_socket` | Calls `open_unix_connection` with socket path |
| `test_initialize_connection_error` | Raises `PluginError` on connection failure |
| **TestUnixSocketExternalPluginInvokeHook** | |
| `test_invoke_hook_success` | Successfully invokes hook and returns result |
| `test_invoke_hook_not_connected` | Attempts reconnection when disconnected |
| `test_invoke_hook_error_response` | Handles error responses from server |
| `test_invoke_hook_timeout` | Raises `PluginError` on read timeout |
| `test_invoke_hook_unregistered_hook_type` | Raises error for unknown hook types |
| **TestUnixSocketExternalPluginShutdown** | |
| `test_shutdown_closes_connection` | Writer is closed and references cleared |
| `test_shutdown_no_connection` | Safe to call when not connected |
| `test_shutdown_idempotent` | Multiple shutdown calls don't raise errors |
| **TestUnixSocketExternalPluginReconnect** | |
| `test_reconnect_success_after_failure` | Retries and succeeds after initial failure |
| `test_reconnect_all_attempts_fail` | Raises after max retry attempts |

### `test_client_integration.py` - Integration Tests (Real Server)

Integration tests that spawn a real Unix socket server subprocess and test actual communication.

**Direct Plugin Tests:**

| Test | Description |
|------|-------------|
| `test_unix_client_invoke_hook` | Invokes `prompt_pre_fetch` hook, verifies word replacement ("crap" → "yikes") |
| `test_unix_client_post_hook` | Invokes `prompt_post_fetch` hook, verifies message text transformation |
| `test_unix_client_multiple_calls` | Makes 5 sequential calls to verify connection reuse |
| `test_unix_client_context_propagation` | Verifies request_id, server_id, user, tenant_id are passed through |
| `test_unix_client_high_throughput` | Makes 50 rapid calls, asserts >50 calls/sec throughput |

**PluginManager Tests:**

| Test | Description |
|------|-------------|
| `test_unix_plugin_manager_invoke_hook` | Tests PluginManager loading and invoking hooks through Unix socket external plugin |
| `test_unix_plugin_manager_multiple_hooks` | Tests PluginManager invoking both pre-fetch and post-fetch hooks |
| `test_unix_plugin_manager_context_persistence` | Tests context persistence across multiple PluginManager calls |

All integration tests are skipped on Windows (no Unix socket support).

### `test_server.py` - Server Unit Tests (Mocked)

Unit tests for `UnixSocketPluginServer` message handling.

| Test | Description |
|------|-------------|
| **TestUnixSocketPluginServerProperties** | |
| `test_socket_path` | Returns correct socket path |
| `test_running_initially_false` | Server not running before start() |
| **TestUnixSocketPluginServerHandleMessage** | |
| `test_handle_invoke_hook_request` | Parses and handles InvokeHookRequest |
| `test_handle_get_plugin_config_request_found` | Returns config when plugin exists |
| `test_handle_get_plugin_config_request_not_found` | Returns `found=False` when not exists |
| `test_handle_get_plugin_configs_request` | Returns all plugin configs |
| **TestUnixSocketPluginServerInvokeHook** | |
| `test_invoke_hook_success` | Returns successful result |
| `test_invoke_hook_with_error` | Returns error details in response |
| `test_invoke_hook_with_context_update` | Includes updated context in response |
| `test_invoke_hook_unexpected_error` | Handles unexpected exceptions |
| **TestUnixSocketPluginServerLifecycle** | |
| `test_start_creates_socket` | Socket file is created on start |
| `test_stop_cleans_up` | Socket file is removed on stop |
| `test_serve_forever_requires_start` | Raises RuntimeError if not started |

### `test_protocol.py` - Protocol Tests

Tests for the length-prefixed message framing protocol.

| Test | Description |
|------|-------------|
| **TestWriteMessage** | |
| `test_write_message_basic` | Writes 4-byte length prefix + payload |
| `test_write_message_empty` | Handles zero-length messages |
| `test_write_message_large` | Handles 100KB messages |
| **TestWriteMessageAsync** | |
| `test_write_message_async_basic` | Writes and drains asynchronously |
| **TestReadMessage** | |
| `test_read_message_basic` | Reads length prefix then payload |
| `test_read_message_with_timeout` | Honors timeout parameter |
| `test_read_message_timeout_error` | Raises TimeoutError on timeout |
| `test_read_message_incomplete_read` | Handles connection closed mid-read |
| `test_read_message_zero_length` | Handles zero-length messages |
| `test_read_message_large` | Handles 100KB messages |
| **TestProtocolError** | |
| `test_protocol_error_message` | Error has message attribute |
| `test_protocol_error_inheritance` | Inherits from Exception |
| **TestRoundTrip** | |
| `test_round_trip_basic` | Encode then decode returns original |
| `test_round_trip_protobuf` | Works with actual protobuf messages |

## Wire Protocol

The Unix socket transport uses length-prefixed protobuf messages:

```
[4-byte big-endian length][protobuf payload]
```

Messages use the same `plugin_service.proto` schema as gRPC (`InvokeHookRequest`, `InvokeHookResponse`, etc.).

## Running Tests

```bash
# Run all Unix socket tests
pytest tests/unit/mcpgateway/plugins/framework/external/unix/ -v

# Run only unit tests (fast, no subprocess)
pytest tests/unit/mcpgateway/plugins/framework/external/unix/test_client.py tests/unit/mcpgateway/plugins/framework/external/unix/test_server.py tests/unit/mcpgateway/plugins/framework/external/unix/test_protocol.py -v

# Run only integration tests (spawns real server)
pytest tests/unit/mcpgateway/plugins/framework/external/unix/test_client_integration.py -v
```

## Test Fixtures

- `unix_server_proc`: Starts Unix socket server in `/tmp` with unique path
- `mock_plugin_config`: Creates test PluginConfig with socket path
- `server`: Creates UnixSocketPluginServer with mock plugin server

## Platform Notes

- All integration tests are **skipped on Windows** (no Unix domain socket support)
- Socket paths use `/tmp` directly to avoid macOS path length limits (~104 chars)
