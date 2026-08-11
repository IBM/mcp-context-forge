# ContextForge Roadmap

This page summarizes the major themes under active development. For detailed
tracking, see the linked GitHub epics and issues. Dates are targets, not
commitments; minor releases ship roughly every two weeks. For what has already
shipped, see the [Release History](releases.md).

## MCP Protocol Features (Q3 2026)

First-class support for MCP 2025-11-25 and 2026-07-28 protocol capabilities:

- **MCP Apps** — interactive UI elements (charts, forms, media) served as MCP
  resources and rendered securely in the agent client. Implementation supports
  both stateful and stateless MCP, with CSP, sandboxing, and permissions
  policy enforcement. Tracked in
  [#2527](https://github.com/IBM/mcp-context-forge/issues/2527) (Governed
  Extension Framework).
- **MCP Tasks** — asynchronous, long-running operations with polling,
  mid-flight input, and durable handles, delivered as the official
  `io.modelcontextprotocol/tasks` extension. Tracked in
  [#5677](https://github.com/IBM/mcp-context-forge/issues/5677) and
  [#5683](https://github.com/IBM/mcp-context-forge/issues/5683).
- **Elicitation, Pagination, Completion, and Cancellation** — tracked in
  [#5558](https://github.com/IBM/mcp-context-forge/issues/5558), with
  protocol-compliance verification in
  [#5557](https://github.com/IBM/mcp-context-forge/issues/5557).
- **Trusted Token Security Pattern** — authorize from properly signed tokens
  without local user storage. Tracked in
  [#5885](https://github.com/IBM/mcp-context-forge/issues/5885).

## ContextForge 2.0 (late Q3 2026)

- **MCP 2026-07-28 (stateless) protocol**, integrated with RBAC/ABAC role
  control, plugins, and the control plane — preview available now, GA targeted
  for late September. Tracked in
  [#5677](https://github.com/IBM/mcp-context-forge/issues/5677) and
  [#5679](https://github.com/IBM/mcp-context-forge/issues/5679).
- **New user experience** — a redesigned look and feel covering all core
  functions, replacing the HTMX frontend with a modern React application.
  Tracked in [#4093](https://github.com/IBM/mcp-context-forge/issues/4093).
- **Streamlined authentication, authorization, and access control.**

## Coming Q4 2026

- **Agent-to-Agent (A2A) v1.0.0 support** — the open standard for agent
  interoperability, integrated with RBAC/ABAC, the plugin framework, and the
  control plane. Tracked in
  [#5936](https://github.com/IBM/mcp-context-forge/issues/5936).
- **LLM Gateway Proxies** — provider-agnostic adapter for external LLM
  gateways (_e.g._ LiteLLM, Portkey, and a ContextForge-native lightweight
  option), with new providers added through configuration. Tracked in
  [#3131](https://github.com/IBM/mcp-context-forge/issues/3131).
- **UX Playground** — a chat interface to exercise and experiment with your
  current ContextForge configuration.
  ([#4927](https://github.com/IBM/mcp-context-forge/issues/4927))
- **ContextForge TUI and Skills** — a terminal UI with Skills available in
  both TUI and CLI modalities from the same binary. Tracked in
  [#5731](https://github.com/IBM/mcp-context-forge/issues/5731).

## Plugin Library Upgrades (Q3–Q4 2026)

Moving plugin detection logic onto maintained open-source libraries:

- **PII Filter → Presidio** —
  [#2553](https://github.com/IBM/mcp-context-forge/issues/2553)
- **SQL Injection → libinjection** —
  [#5937](https://github.com/IBM/mcp-context-forge/issues/5937)
- **Secret Detection → detect-secrets** —
  [#5938](https://github.com/IBM/mcp-context-forge/issues/5938)

## Runtimes and Code Mode (ongoing)

- **Secure runtimes** for remote server deployment and catalog integration —
  [#2110](https://github.com/IBM/mcp-context-forge/issues/2110)
- **MCP Code Mode** — secure code execution and a virtual tool filesystem —
  [#2952](https://github.com/IBM/mcp-context-forge/issues/2952)
