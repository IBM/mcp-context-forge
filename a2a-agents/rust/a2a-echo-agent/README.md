# A2A Echo Agent (Rust)

Lightweight Rust A2A echo agent used for ContextForge compose, Langfuse,
load-test, and end-to-end A2A pipeline validation.

This is the active A2A echo agent implementation used by compose and container
validation.

## Endpoints

| Endpoint | Description |
| -------- | ----------- |
| `GET /health` | Health check. |
| `GET /.well-known/agent-card.json` | A2A agent card. |
| `GET /.well-known/agent.json` | Compatibility alias for the agent card. |
| `GET /extendedAgentCard` | Extended agent card. |
| `POST /` | JSON-RPC A2A endpoint. |
| `POST /run` | Compatibility helper for simple echo calls. |

## JSON-RPC Methods

- `SendMessage`
- `GetTask`
- `ListTasks`
- `CancelTask`
- `GetExtendedAgentCard`
- Compatibility aliases: `message/send`, `tasks/get`, `tasks/list`,
  `tasks/cancel`, `agent/getExtendedCard`.

Tasks complete immediately and are stored in memory for follow-up lookup.

## Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `A2A_ECHO_ADDR` | `0.0.0.0:9100` | Bind address. |
| `A2A_ECHO_NAME` | `a2a-echo-agent` | Agent name. |
| `A2A_ECHO_PROTOCOL_VERSION` | `1.0.0` | Protocol version advertised in the card. |
| `A2A_ECHO_FIXED_RESPONSE` | unset | Optional fixed response text. |
| `A2A_ECHO_PUBLIC_URL` | unset | Public URL advertised in the card. |
| `RUST_LOG` | `info` | Logging level. |

## Run

```bash
make run
```

## Example

```bash
curl -s http://localhost:9100/.well-known/agent-card.json
```

```bash
curl -s http://localhost:9100/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"role":"ROLE_USER","parts":[{"text":"hello"}]}}}'
```

## Validation

```bash
make test
make clippy
```
