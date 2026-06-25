# -*- coding: utf-8 -*-
"""A2A protocol compliance harness.

Location: ./tests/live_gateway/a2a_compliance/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Black-box A2A protocol tests driven by the official ``a2a-sdk`` client
(with raw httpx where wire-level precision matters). The same test
bodies run against multiple targets — reference (direct to the
``a2a_echo_agent``), gateway_proxy, gateway_virtual — so behavioral
drift surfaces as a concrete test failure rather than a manual log diff.

Mirrors the ``tests/live_gateway/protocol_compliance`` MCP harness in
shape, but with an A2A-specific target ABC because the SDK Client
returns ``a2a.client.Client`` (not ``fastmcp.client.Client``) and the
protocol surface differs.

Per-version test bodies live under ``v<X>_<Y>_<Z>/`` (e.g. ``v1_0_0/``).
Phase 1 covers A2A 1.0.0 only; the v0.3.0 overlay arrives in Phase 2.
"""
