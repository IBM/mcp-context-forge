# ADR-037: External Plugin STDIO Launch with Command/Env Overrides

- *Status:* Accepted
- *Date:* 2026-01-28
- *Deciders:* Platform Team

## Context

External plugins can run over MCP using HTTP or STDIO. STDIO is the easiest way to run an external MCP server without additional infrastructure, but the previous configuration only allowed a `script` path (with a `.py` restriction). This made it hard to:

- Run non-Python MCP servers (Go, Rust, Node, etc.).
- Provide per-plugin environment variables (e.g., `PLUGINS_CONFIG_PATH`) without wrapper scripts.
- Set a working directory for plugin servers started by the gateway.

These gaps limited deployment flexibility and made isolated plugin execution less ergonomic.

## Decision

We extend external plugin MCP configuration with STDIO process options:

- `cmd`: a command array (`["command", "arg1", ...]`) for starting an MCP server.
- `env`: environment variable overrides for the STDIO server process.
- `cwd`: working directory for the STDIO server process.

The gateway resolves STDIO launch as follows:

- If `cmd` is provided, use it as the command + args.
- Otherwise, use `script`:

  - `.py` runs via `python`.
  - `.sh` runs via `sh`.
  - Executables run directly.

Validation enforces transport-specific fields:

- `url` is only allowed for HTTP/SSE.
- `script`, `cmd`, `env`, and `cwd` are only allowed for STDIO.
- `script` and `cmd` are mutually exclusive.

This keeps STDIO isolation easy while preserving existing behavior for HTTP-based external plugins.

## Consequences

- **Pros:**

  - Run any MCP server (any language) with STDIO, no wrapper scripts required.
  - Per-plugin env and working directory are supported.
  - Backward compatible with existing `script` usage.

- **Cons:**

  - Larger configuration surface area.
  - More responsibility on operators to manage environment/cwd security and correctness.

## Alternatives Considered

- Require wrapper scripts for env/cwd: simpler code, but less ergonomic and more brittle.
- Add only `cmd` without `env/cwd`: improves language support but still requires wrapper scripts for config.
- Require HTTP transport for external plugins: increases operational complexity and infrastructure burden.
