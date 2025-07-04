# MCP Gateway StdIO to SSE Bridge (`mcpgateway.translate`)

`mcpgateway.translate` is a lightweight bridge that connects a JSON-RPC server
running over StdIO to an HTTP/SSE interface, or consumes a remote SSE stream
and forwards messages to a local StdIO process.

Supported modes:

1. StdIO to SSE – serve a local subprocess over HTTP with SSE output
2. SSE to StdIO – subscribe to a remote SSE stream and forward messages to a local process

---

## Features

| Feature | Description |
|---------|-------------|
| Bidirectional bridging | Supports both StdIO to SSE and SSE to StdIO |
| Keep-alive frames | Emits `keepalive` events every 30 seconds |
| Endpoint bootstrapping | Sends a unique message POST endpoint per client session |
| CORS support | Configure allowed origins via `--cors` |
| OAuth2 support | Use `--oauth2Bearer` to authorize remote SSE connections |
| Health check | Provides a `/healthz` endpoint for liveness probes |
| Logging control | Adjustable log verbosity with `--logLevel` |
| Graceful shutdown | Cleans up subprocess and server on termination signals |

---

## Quick Start

### Expose a local StdIO server over SSE

```bash
python3 -m mcpgateway.translate \
  --stdio "uvenv run mcp-server-git" \
  --port 9000
```

Access the SSE stream at:

```
http://localhost:9000/sse
```

### Bridge a remote SSE endpoint to a local process

```bash
python3 -m mcpgateway.translate \
  --sse "https://corp.example.com/mcp" \
  --oauth2Bearer "your-token"
```

---

## Command-Line Options

```
python3 -m mcpgateway.translate [--stdio CMD | --sse URL | --streamableHttp URL] [options]
```

### Required (one of)

* `--stdio <command>`
  Start a local process whose stdout will be streamed as SSE and stdin will receive backchannel messages.

* `--sse <url>`
  Connect to a remote SSE stream and forward messages to a local subprocess.

* `--streamableHttp <url>`
  Not implemented in this build. Raises an error.

### Optional

* `--port <number>`
  HTTP server port when using --stdio mode (default: 8000)

* `--cors <origins>`
  One or more allowed origins for CORS (space-separated)

* `--oauth2Bearer <token>`
  Bearer token to include in Authorization header when connecting to remote SSE

* `--logLevel <level>`
  Logging level (default: info). Options: debug, info, warning, error, critical

---

## HTTP API (when using --stdio)

### GET /sse

Streams JSON-RPC responses as SSE. Each connection receives:

* `event: endpoint` – the URL for backchannel POST
* `event: keepalive` – periodic keepalive signal
* `event: message` – forwarded output from subprocess

### POST /message

Send a JSON-RPC message to the subprocess. Returns HTTP 202 on success, or 400 for invalid JSON.

### GET /healthz

Health check endpoint. Always responds with `ok`.

---

## Example Use Cases

### 1. Browser integration

```bash
python3 -m mcpgateway.translate \
  --stdio "uvenv run mcp-server-git" \
  --port 9000 \
  --cors "https://myapp.com"
```

Then connect the frontend to:

```
http://localhost:9000/sse
```

### 2. Connect remote server to local CLI tools

```bash
python3 -m mcpgateway.translate \
  --sse "https://corp.example.com/mcp" \
  --oauth2Bearer "$TOKEN" \
  --logLevel debug
```

---

## Notes

* Only StdIO to SSE and SSE to StdIO bridging are implemented.
* Any use of `--streamableHttp` will raise a NotImplementedError.
