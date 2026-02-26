# Plugin Configuration Reference

This page documents plugin-framework configuration (the settings owned by
`mcpgateway.plugins.framework.settings`).

For core gateway/app configuration, see [Configuration Reference](configuration.md).

---

## Plugin Framework Settings

The plugin framework uses its own `PluginsSettings` class (via
`pydantic-settings`) with the `PLUGINS_` env var prefix. When used standalone
(for example via `mcpplugins` CLI or as a library), only these
`PLUGINS_`-prefixed variables are required.

Inside the gateway, plugin settings are exposed under `settings.plugins`.

### Core Settings

| Setting                        | Description                                      | Default               | Options |
| ------------------------------ | ------------------------------------------------ | --------------------- | ------- |
| `PLUGINS_ENABLED`             | Enable the plugin framework                      | `false`               | bool    |
| `PLUGINS_CONFIG_FILE`         | Path to plugin configuration file                | `plugins/config.yaml` | string  |
| `PLUGINS_PLUGIN_TIMEOUT`      | Plugin execution timeout (seconds)               | `30`                  | int     |
| `PLUGINS_LOG_LEVEL`           | Plugin framework log level                       | `INFO`                | string  |
| `PLUGINS_SKIP_SSL_VERIFY`     | Skip TLS verification for plugin HTTP requests   | `false`               | bool    |

### HTTP Client Settings

| Setting                                   | Description                                      | Default | Options |
| ----------------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_HTTPX_MAX_CONNECTIONS`           | Max total concurrent HTTP connections            | `200`   | int     |
| `PLUGINS_HTTPX_MAX_KEEPALIVE_CONNECTIONS` | Max idle keepalive connections to retain         | `100`   | int     |
| `PLUGINS_HTTPX_KEEPALIVE_EXPIRY`          | Idle keepalive connection expiry (seconds)       | `30.0`  | float   |
| `PLUGINS_HTTPX_CONNECT_TIMEOUT`           | TCP connect timeout (seconds)                    | `5.0`   | float   |
| `PLUGINS_HTTPX_READ_TIMEOUT`              | Read timeout (seconds)                           | `120.0` | float   |
| `PLUGINS_HTTPX_WRITE_TIMEOUT`             | Write timeout (seconds)                          | `30.0`  | float   |
| `PLUGINS_HTTPX_POOL_TIMEOUT`              | Connection pool timeout (seconds)                | `10.0`  | float   |

### CLI Settings

| Setting                    | Description                                          | Default | Options |
| -------------------------- | ---------------------------------------------------- | ------- | ------- |
| `PLUGINS_CLI_COMPLETION`   | Enable shell auto-completion for `mcpplugins` CLI   | `false` | bool    |
| `PLUGINS_CLI_MARKUP_MODE`  | Markup renderer for CLI output                       | (none)  | `rich`, `markdown`, `disabled` |

### MCP Client mTLS Settings

| Setting                                 | Description                                      | Default | Options |
| --------------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_CLIENT_MTLS_CERTFILE`          | Path to PEM client certificate for mTLS          | (none)  | string  |
| `PLUGINS_CLIENT_MTLS_KEYFILE`           | Path to PEM client private key for mTLS          | (none)  | string  |
| `PLUGINS_CLIENT_MTLS_CA_BUNDLE`         | Path to CA bundle for client cert verification   | (none)  | string  |
| `PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD`  | Password for encrypted client private key        | (none)  | string  |
| `PLUGINS_CLIENT_MTLS_VERIFY`            | Verify upstream server certificate               | (none)  | bool    |
| `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME`    | Enable hostname verification                     | (none)  | bool    |

### MCP Server SSL Settings

| Setting                                 | Description                                      | Default | Options |
| --------------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_SERVER_SSL_KEYFILE`            | Path to PEM server private key                   | (none)  | string  |
| `PLUGINS_SERVER_SSL_CERTFILE`           | Path to PEM server certificate                   | (none)  | string  |
| `PLUGINS_SERVER_SSL_CA_CERTS`           | Path to CA certs for client verification         | (none)  | string  |
| `PLUGINS_SERVER_SSL_KEYFILE_PASSWORD`   | Password for encrypted server private key        | (none)  | string  |
| `PLUGINS_SERVER_SSL_CERT_REQS`          | Client certificate requirement                   | (none)  | `0`, `1`, `2` |

### MCP Server Settings

| Setting                        | Description                                      | Default | Options |
| ------------------------------ | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_SERVER_HOST`          | MCP server host to bind to                       | (none)  | string  |
| `PLUGINS_SERVER_PORT`          | MCP server port to bind to                       | (none)  | int     |
| `PLUGINS_SERVER_UDS`           | UDS path for MCP streamable HTTP                 | (none)  | string  |
| `PLUGINS_SERVER_SSL_ENABLED`   | Enable SSL/TLS for MCP server                    | (none)  | bool    |

### MCP Runtime Settings

| Setting                        | Description                                      | Default | Options |
| ------------------------------ | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_CONFIG_PATH`          | Path to plugin config file for external servers  | (none)  | string  |
| `PLUGINS_TRANSPORT`            | Transport type for external MCP server           | (none)  | `http`, `stdio` |

### gRPC Client mTLS Settings

| Setting                                      | Description                                      | Default | Options |
| -------------------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_GRPC_CLIENT_MTLS_CERTFILE`          | Path to PEM client cert for gRPC mTLS            | (none)  | string  |
| `PLUGINS_GRPC_CLIENT_MTLS_KEYFILE`           | Path to PEM client key for gRPC mTLS             | (none)  | string  |
| `PLUGINS_GRPC_CLIENT_MTLS_CA_BUNDLE`         | Path to CA bundle for gRPC verification          | (none)  | string  |
| `PLUGINS_GRPC_CLIENT_MTLS_KEYFILE_PASSWORD`  | Password for encrypted gRPC client key           | (none)  | string  |
| `PLUGINS_GRPC_CLIENT_MTLS_VERIFY`            | Verify gRPC upstream cert                        | (none)  | bool    |

### gRPC Server SSL Settings

| Setting                                      | Description                                      | Default | Options |
| -------------------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_GRPC_SERVER_SSL_KEYFILE`            | Path to PEM gRPC server private key              | (none)  | string  |
| `PLUGINS_GRPC_SERVER_SSL_CERTFILE`           | Path to PEM gRPC server certificate              | (none)  | string  |
| `PLUGINS_GRPC_SERVER_SSL_CA_CERTS`           | Path to CA certs for gRPC client verification    | (none)  | string  |
| `PLUGINS_GRPC_SERVER_SSL_KEYFILE_PASSWORD`   | Password for encrypted gRPC server private key   | (none)  | string  |
| `PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH`        | gRPC client certificate requirement              | (none)  | `none`, `optional`, `require` |

### gRPC Server Settings

| Setting                            | Description                                      | Default | Options |
| ---------------------------------- | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_GRPC_SERVER_HOST`         | gRPC server host to bind to                      | (none)  | string  |
| `PLUGINS_GRPC_SERVER_PORT`         | gRPC server port to bind to                      | (none)  | int     |
| `PLUGINS_GRPC_SERVER_UDS`          | UDS path for gRPC server                         | (none)  | string  |
| `PLUGINS_GRPC_SERVER_SSL_ENABLED`  | Enable SSL/TLS for gRPC server                   | (none)  | bool    |

### Unix Socket Settings

| Setting                        | Description                                      | Default | Options |
| ------------------------------ | ------------------------------------------------ | ------- | ------- |
| `PLUGINS_UNIX_SOCKET_PATH`     | Path to Unix domain socket                       | (none)  | string  |

!!! note "Backwards Compatibility"
    `UNIX_SOCKET_PATH` is also accepted as an alias for
    `PLUGINS_UNIX_SOCKET_PATH`.
