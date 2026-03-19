# A2A Echo Agent (Go)

Lightweight, dependency-free (no LLM) **A2A** echo agent used for **docker-compose load testing** and end-to-end A2A pipeline validation.

This agent is intended to be run via the repo's `docker-compose.yml` `testing` profile, and auto-registered into the gateway as `a2a-echo-agent`.

## Protocol Support

- A2A **v0.3.x** Agent Card: `GET /.well-known/agent-card.json`
- A2A **JSON-RPC** methods (HTTP `POST /`):
  - `message/send`
  - `tasks/get`
  - `tasks/cancel`

The agent completes tasks immediately (echo response returned as a completed task).

## Endpoints

- `GET /health`
- `GET /.well-known/agent-card.json`
- `GET /.well-known/agent.json` (compat alias)
- `POST /` (JSON-RPC)
- `POST /run` (compat helper; not part of the A2A spec)

## Environment Variables

- `A2A_ECHO_ADDR` (default: `0.0.0.0:9100`)
- `A2A_ECHO_NAME` (default: `a2a-echo-agent`)
- `A2A_ECHO_PROTOCOL_VERSION` (default: `0.3.0`)
- `A2A_ECHO_FIXED_RESPONSE` (optional: always return this text instead of echoing)
- `A2A_ECHO_PUBLIC_URL` (optional: override the URL advertised in the agent card)

## Run With Docker Compose

```bash
make testing-up
```

This brings up:
- Gateway stack + nginx on `http://localhost:8080`
- Locust UI on `http://localhost:8089`
- A2A echo agent on `http://localhost:9100`

## Direct JSON-RPC Example

```bash
curl -s http://localhost:9100/.well-known/agent-card.json | jq .
```

```bash
curl -s http://localhost:9100/ \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"message/send",
    "params":{
      "message":{
        "kind":"message",
        "role":"user",
        "messageId":"00000000-0000-0000-0000-000000000000",
        "parts":[{"kind":"text","text":"hello"}]
      }
    }
  }' | jq .
```
