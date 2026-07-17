# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v0_3_0/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

A2A 0.3.0 compliance tests.
Test bodies for the A2A 0.3.0 (legacy) protocol surface. Driven by
the bundled ``a2a_echo_agent_v0_3_0`` compose service (port 9101,
``A2A_ECHO_PROTOCOL_VERSION=0.3.0``). The SDK's ``ClientFactory``
auto-routes via ``CompatJsonRpcTransport`` for v0.3.x cards, so the
same target ABC and (target, transport) matrix from the parent
conftest apply unchanged — only the base URL fixture is overridden
in ``v0_3_0/conftest.py``.
"""
