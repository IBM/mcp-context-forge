# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

E2E tests requiring a live ContextForge gateway (MCP transports / observability /
subprocess-driven flows):

* `test_mcp_protocol_e2e.py` — MCP protocol via FastMCP client (any transport)
* `test_mcp_rbac_transport.py` — RBAC + multi-transport (needs SSE registered)
* `test_mcp_plugin_parity.py` — Compose-backed plugin parity (needs MCP_PLUGIN_PARITY_EXPECTED_RUNTIME)
* `test_langfuse_traces.py` — Langfuse trace export (needs gateway + Langfuse on :3100)
* `test_translate_dynamic_env_e2e.py` — Dynamic env injection via spawned `mcpgateway.translate` subprocess

Excluded from the default `make test` run because they need a running
gateway (typically `make testing-up` or `docker compose up -d`). Invoke
explicitly via the dedicated make targets (`make test-mcp-protocol-e2e`,
`make test-mcp-rbac`, `make test-mcp-plugin-parity`) once the stack is
healthy.
"""
