# QR Code Server

MCP server that provides QR code generation and decoding capabilities

## Quickstart

- Install (dev):
  - `python -m pip install -e .[dev]`
- Run (stdio):
  - `python -m qr_code_server.server`
- Test:
  - `pytest -v`
- Makefile targets:
  - `make dev` — runs stdio server
  - `make test` — pytest with coverage
  - `make format` / `make lint`
  - `make serve-http` — expose stdio server over HTTP via gateway translate
  - `make test-http` — quick HTTP checks

## MCP Client Snippet

Use this snippet in your MCP client configuration (e.g., Claude Desktop):

```json
{"command": "python", "args": ["-m", "qr_code_server.server"], "cwd": "."}
```

## Container

Build and run with a local container runtime (Docker/Podman):

```bash
# Build
podman build -f Containerfile -t qr-code-server:0.1.0 .
# Run
podman run --rm -it qr-code-server:0.1.0
```

## License

Apache-2.0

