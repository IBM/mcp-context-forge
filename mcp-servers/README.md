# MCP Servers

> Sample and test MCP servers for demonstration and integration testing with ContextForge.

## Security Warning

> **These are unsupported sample and test servers.** They do not go through the same
> review, testing, and security rigor as the core ContextForge codebase. They generally
> lack session management, persistent state, multi-tenancy, authentication, and other
> production concerns. **Do not run them in production.**
>
> **Never run untrusted MCP servers directly on your local filesystem.** Always use a
> sandbox, container, or microVM (e.g. Docker, Podman, gVisor, Firecracker) with
> restricted capabilities — limited network access, read-only filesystem mounts, memory
> and CPU bounds, and no access to host credentials or sensitive data.
>
> **Exercise caution when registering any remote MCP server**, including servers from
> public catalogs. Perform your own security evaluation before granting a server access
> to your gateway. Verify the server source, review its code and dependencies, and run
> it in an isolated environment with least-privilege permissions.

## Servers

### Python

| Server | Description |
|--------|-------------|
| `data_analysis_server` | Data analysis, statistics, and visualization |
| `graphviz_server` | Graphviz diagram generation |
| `mcp_eval_server` | AI evaluation with LLM-as-a-judge |
| `mcp-rss-search` | RSS feed parsing, searching, and analysis |
| `output_schema_test_server` | Output schema validation (test fixture) |
| `python_sandbox_server` | Sandboxed Python code execution |
| `qr_code_server` | QR code generation and decoding |
| `url_to_markdown_server` | URL and document to markdown conversion |

### Go

| Server | Description |
|--------|-------------|
| `benchmark-server` | Performance benchmarking |
| `fast-time-server` | Time and date operations |
| `slow-time-server` | Configurable-latency testing server |

### Rust

| Server | Description |
|--------|-------------|
| `fast-test-server` | Fast testing server |
| `filesystem-server` | Filesystem operations |

## Scaffolding New Servers

```bash
# Python
./mcp-servers/scaffold-python-server.sh my-server

# Go
./mcp-servers/scaffold-go-server.sh my-server
```

See templates in `templates/` for cookiecutter scaffolding.

## License

Apache-2.0
