# Docling MCP

[Docling MCP](https://github.com/docling-project/docling-mcp) exposes document conversion, generation,
and manipulation tools through the Model Context Protocol. ContextForge can federate these tools through
Docling MCP's Streamable HTTP endpoint.

Run Docling MCP as a separate service. Do not install it into the ContextForge Python environment.
Keep its dependencies isolated from ContextForge. The services communicate through the MCP wire protocol.

## Architecture

```text
MCP client
    |
    v
ContextForge
    |
    | Streamable HTTP
    v
Docling MCP :8000/mcp
    |
    +-- Local Docling conversion
    |
    +-- Remote Docling Serve API
```

ContextForge provides authentication, RBAC, visibility controls, observability, and tool federation.
Docling MCP performs the document operations and owns its conversion configuration and cache.

## Prerequisites

- A running ContextForge instance
- A ContextForge token with `gateways.create` permission
- [`uv`](https://docs.astral.sh/uv/) for `uvx`
- Python 3.10 or later for Docling MCP
- `jq` for the registration examples

Set the tested Docling MCP version explicitly. The examples below use `3.2.0`.

```bash
export DOCLING_MCP_VERSION=3.2.0
```

Check the [Docling MCP package](https://pypi.org/project/docling-mcp/) before updating this version.
Re-run the verification steps after each update.

## Choose a conversion mode

Docling MCP supports local conversion and remote conversion through Docling Serve.

### Local conversion

Local mode installs the Docling conversion dependencies in the `uvx` environment. It can download
models during initial use and requires more CPU, memory, disk space, and startup time.

Use a loopback bind when ContextForge runs directly on the same host:

```bash
export DOCLING_MCP_CONVERSION_MODE=local

uvx \
  --from "docling-mcp[local]==${DOCLING_MCP_VERSION}" \
  docling-mcp-server \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

Use `--host 0.0.0.0` only when a ContextForge container must reach the host process:

```bash
export DOCLING_MCP_CONVERSION_MODE=local

uvx \
  --from "docling-mcp[local]==${DOCLING_MCP_VERSION}" \
  docling-mcp-server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8000
```

Restrict port `8000` with a host firewall when you bind to `0.0.0.0`.

### Remote Docling Serve

Remote mode keeps the MCP process lightweight and delegates conversion to a
[Docling Serve](https://github.com/docling-project/docling-serve) deployment.

```bash
export DOCLING_MCP_CONVERSION_MODE=remote
export DOCLING_MCP_SERVICE_URL=https://docling.example.com
export DOCLING_MCP_SERVICE_API_KEY='<service-api-key>'

uvx \
  --from "docling-mcp==${DOCLING_MCP_VERSION}" \
  docling-mcp-server \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

Keep `DOCLING_MCP_SERVICE_API_KEY` in the Docling MCP environment. Do not put this key in the
ContextForge gateway registration payload.

See the upstream [environment variable reference](https://github.com/docling-project/docling-mcp/blob/main/.env.example)
for OCR, table detection, image export, retry, and timeout options.

## Register Docling MCP

The registration URL depends on where ContextForge runs.

### ContextForge on the host

```bash
export CONTEXTFORGE_URL=http://localhost:4444
export DOCLING_MCP_URL=http://127.0.0.1:8000/mcp
```

### ContextForge with Docker Compose

Start Docling MCP with `--host 0.0.0.0`, then use the host address visible from the gateway
container:

```bash
export CONTEXTFORGE_URL=http://localhost:8080
export DOCLING_MCP_URL=http://host.docker.internal:8000/mcp
```

Register the Streamable HTTP endpoint:

```bash
registration=$(curl -fsS -X POST "${CONTEXTFORGE_URL}/gateways" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"name\": \"docling\",
    \"description\": \"Document processing through Docling MCP\",
    \"url\": \"${DOCLING_MCP_URL}\",
    \"transport\": \"STREAMABLEHTTP\",
    \"visibility\": \"private\"
  }")

echo "${registration}" | jq .
export DOCLING_GATEWAY_ID=$(echo "${registration}" | jq -r .id)
```

Use `team` visibility when multiple team members need the tools. Use `public` visibility only when all
authenticated platform users can access the gateway. ContextForge does not use `public` to mean
internet-anonymous access.

## Verify the integration

Check the registered gateway:

```bash
curl -fsS \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  "${CONTEXTFORGE_URL}/gateways/${DOCLING_GATEWAY_ID}" | jq .
```

List the tools discovered from Docling MCP:

```bash
curl -fsS \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  "${CONTEXTFORGE_URL}/gateways/${DOCLING_GATEWAY_ID}/tools" | jq .
```

Then use the ContextForge Admin UI or an MCP client connected to ContextForge to perform these checks:

1. Create a Docling document.
2. Add a title and a paragraph.
3. Export the document to Markdown.
4. Convert a small document through the configured conversion mode.

Send these calls through ContextForge. Do not connect the test client directly to port `8000`.

## Filesystem and document access

A local path supplied to a Docling tool refers to the filesystem visible to the Docling MCP process.
It does not refer to the ContextForge filesystem or the MCP client's filesystem.

For a container deployment, mount only a dedicated document directory into the Docling MCP container.
Do not mount a home directory, the ContextForge repository, or a credential directory. Use read-only
mounts for input documents when the workflow does not require writes.

URL-based conversion gives Docling MCP outbound network access. Restrict egress to approved destinations
when documents can contain untrusted URLs.

## Security considerations

!!! warning
    Do not expose the Docling MCP port directly to untrusted networks. Put it on an internal network,
    or protect it with authentication and TLS.

- Use ContextForge RBAC and private or team visibility to control access.
- Keep the Docling Serve API key outside ContextForge registration data.
- Apply CPU, memory, document-size, and execution-time limits to Docling MCP.
- Treat every document and remote URL as untrusted input.
- Limit filesystem mounts and outbound network access.
- Do not use a shared Docling document cache as a tenant isolation boundary.
- Deploy separate Docling MCP instances when teams require isolated documents or service credentials.
- Review the Docling and model licenses required by the selected conversion pipeline.

Binding Docling MCP to `0.0.0.0` permits container and cluster connections. It also makes network-level
isolation important because the MCP SDK cannot apply a loopback-only host allowlist to that bind address.

## Troubleshooting

### ContextForge cannot connect

Confirm that Docling MCP uses Streamable HTTP and that the URL ends in `/mcp`.

```bash
curl -i http://127.0.0.1:8000/mcp
```

An HTTP response confirms that the port is reachable. A plain `GET` request does not perform an MCP
initialization and can return a method or session error.

When ContextForge runs in Docker Compose, start Docling MCP with `--host 0.0.0.0` and use
`host.docker.internal` instead of `localhost`.

### Registration is rejected with an SSRF error

Production deployments block private upstream networks by default. Add only the required private CIDR to
`SSRF_ALLOWED_NETWORKS`. Avoid enabling all private networks when a narrow allowlist is sufficient.

See [SSRF protection](../../../manage/configuration.md#ssrf-protection) for the available settings.

### Docling MCP returns HTTP 421

Use a Docling MCP release that includes the non-loopback bind fix. Start it with the required external
bind address before ContextForge connects.

### No Docling tools appear

Request an immediate catalog refresh:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  "${CONTEXTFORGE_URL}/gateways/${DOCLING_GATEWAY_ID}/tools/refresh?include_resources=true&include_prompts=true" \
  | jq .
```

Check both the ContextForge and Docling MCP logs if discovery still fails.

### Conversion times out

Large documents and first-use model downloads can exceed normal request deadlines. Confirm that Docling
MCP can convert the document directly, then adjust the Docling service timeout and the applicable
ContextForge upstream timeout. Keep the limits finite.

## References

- [Docling MCP repository](https://github.com/docling-project/docling-mcp)
- [Docling MCP configuration](https://github.com/docling-project/docling-mcp/blob/main/.env.example)
- [Docling documentation](https://docling-project.github.io/docling/)
- [ContextForge API usage](../../../manage/api-usage.md#register-a-new-gateway)
