# Benchmark Server (Rust)

Configurable MCP benchmark server for gateway scale, pagination, and load
testing.

The server dynamically generates arbitrary numbers of tools, resources, and
prompts. It can also launch multiple HTTP instances on sequential ports to
simulate federated MCP deployments.

## Run

```bash
make run
```

Default endpoint: `http://localhost:8080/mcp`.

## Options

Available options:

| Option | Default | Description |
| ------ | ------- | ----------- |
| `-listen=0.0.0.0` | `0.0.0.0` | Listen interface. |
| `-port=8080` | `8080` | Single-server port. |
| `-server-count=1` | `1` | Number of HTTP server instances. |
| `-start-port=8080` | `8080` | First port for multi-server mode. |
| `-tools=100` | `100` | Number of generated tools. |
| `-resources=100` | `100` | Number of generated resources. |
| `-prompts=100` | `100` | Number of generated prompts. |
| `-tool-size=1000` | `1000` | Tool response payload bytes. |
| `-resource-size=1000` | `1000` | Resource response payload bytes. |
| `-prompt-size=1000` | `1000` | Prompt response payload bytes. |
| `-payload-size=1000` | `1000` | Alias for `-tool-size`. |
| `-auth-token=TOKEN` | unset | Bearer token required for MCP requests. |

`AUTH_TOKEN` overrides `-auth-token` when set.

## Examples

```bash
cargo run --release -- -tools=1000 -resources=500 -prompts=250 -tool-size=2048
```

```bash
cargo run --release -- -server-count=10 -start-port=9000 -tools=50 -resources=20 -prompts=10
```

```bash
curl -s http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Endpoints

| Endpoint | Description |
| -------- | ----------- |
| `POST /mcp` | MCP JSON-RPC endpoint. |
| `GET /health` | Health check. |
| `GET /version` | Version and configured counts. |

## Validation

```bash
make test
make clippy
```
