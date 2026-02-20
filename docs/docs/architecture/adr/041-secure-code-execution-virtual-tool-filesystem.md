# ADR-0041: Secure Code Execution and Virtual Tool Filesystem (MCP Code Mode)

- **Status:** Accepted
- **Date:** 2026-02-16
- **Deciders:** ContextForge Core Maintainers
- **Technical Story:** [#2952](https://github.com/IBM/mcp-context-forge/issues/2952)

## Context

ContextForge needed a production-grade way to run model-generated code without granting broad host access.

Existing approaches (direct local execution, broad subprocess wrappers, or external ad-hoc sandboxes) were insufficient for multi-tenant and policy-controlled MCP operations because they lacked:

- A first-class MCP server mode dedicated to controlled code execution
- Policy-driven virtual filesystem and mounted-tool controls
- Configurable runtime/resource/network guardrails with secure defaults
- Governance for reusable skills (including optional approval workflows)
- Operational observability for runs, sessions, and security events

The design also needed to integrate with existing token scoping, RBAC, plugin hooks, and deployment configuration layers (`config.py`, `.env.example`, Helm, Compose, docs schema).

## Decision

We adopted a dedicated `code_execution` server type with a virtual tool filesystem and policy-enforced runtime execution.

### 1) Server Type and Meta-Tools

- Added `server_type: code_execution` (API alias `type=code_execution`)
- Added synthetic meta-tools per server:
  - `shell_exec`: execute sandboxed code or constrained shell commands
  - `fs_browse`: inspect virtual filesystem state safely
- Kept feature-level controls:
  - `CODE_EXECUTION_ENABLED`
  - `CODE_EXECUTION_SHELL_EXEC_ENABLED`
  - `CODE_EXECUTION_FS_BROWSE_ENABLED`
  - `CODE_EXECUTION_REPLAY_ENABLED`

### 2) Virtual Tool Filesystem

For each active session, expose isolated virtual paths:

- `/tools`: generated stubs + catalog for mounted tools
- `/skills`: approved reusable skills for the server/runtime
- `/scratch`: writable working area
- `/results`: writable output area

Mounting is filtered by declarative mount rules (`include_tags`, `exclude_tags`, `include_servers`, `exclude_servers`, `include_tools`, `exclude_tools`).

### 3) Sandbox Policy and Limits

Implemented runtime and limits policy with defaults and per-server override support:

- Runtime: `deno` or `python`
- Time, memory, CPU, file-size, total-disk, and rate limits
- Network policy (`allow_raw_http`, max connections)
- Tool-call permissions with allow/deny patterns
- Filesystem read/write/deny globs

Dangerous-pattern validation blocks risky code signatures for Python and TypeScript before execution.

### 4) Tokenization Policy

Implemented optional bidirectional tokenization for configured PII types, controlled by server policy and global defaults.

### 5) Skills Governance and Scope

Implemented skill lifecycle and visibility controls:

- Skill create/list/revoke endpoints
- Optional approval workflow (`skills_require_approval`)
- Scope targeting via `skills_scope` (for example `team:<team-id>`, `user:<email>`)

### 6) Observability and Replay

Persisted run metadata and exposed APIs for:

- Run history
- Active sessions
- Structured security events
- Replay of prior runs (feature-flag controlled)

### 7) Configurability and Rollout

Made the feature configurable across all supported operator surfaces:

- `mcpgateway/config.py`
- `.env.example`
- `charts/` values + schema
- `docker-compose.yml`
- `docs/docs/config.schema.json`
- `docs/docs/manage/configuration.md`

## Consequences

### Positive

- Secure-by-default code execution mode with explicit guardrails
- Strong operator control through feature flags and policy defaults
- Better tenant/team governance for shared skills and mounted capabilities
- Auditable execution outcomes with replay and security-event visibility
- Consistent integration with existing MCP transports and auth model

### Negative

- Increased configuration surface area and operational complexity
- Additional runtime dependencies (Deno/Python availability based on policy/runtime choice)
- More moving parts in UI/API workflows for advanced use cases

### Risks and Mitigations

- **Risk:** Misconfigured permissive policies
  - **Mitigation:** Safe defaults (no raw HTTP by default, constrained filesystem, deny patterns)
- **Risk:** Runtime availability differences across environments
  - **Mitigation:** Explicit runtime policy + health checks + Python fallback flag
- **Risk:** Cross-tenant leakage via mounts/skills
  - **Mitigation:** Token scoping + mount rules + skills scope + approval workflow

## Alternatives Considered

1. **Only external sandbox service (no native server type):** Rejected for higher integration and operations overhead.
2. **Single runtime only (Deno or Python):** Rejected to preserve flexibility for existing Python-heavy and TypeScript-heavy workflows.
3. **No virtual filesystem abstraction:** Rejected because direct host paths/tool calls are harder to reason about and secure.

## Related

- Architecture overview: [`docs/docs/architecture/code-execution-virtual-tool-filesystem.md`](../code-execution-virtual-tool-filesystem.md)
- Usage guide: [`docs/docs/using/code-execution-virtual-server.md`](../../using/code-execution-virtual-server.md)
- Configuration reference: [`docs/docs/manage/configuration.md`](../../manage/configuration.md#code-execution-mcp-code-mode)
