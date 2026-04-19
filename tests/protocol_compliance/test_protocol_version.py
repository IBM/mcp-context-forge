"""MCP protocol-version negotiation compliance tests."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_lifecycle]


async def test_initialize_negotiates_a_version(client) -> None:
    """The server must echo a protocol version it supports."""
    init = client.initialize_result
    assert init.protocolVersion, f"missing protocolVersion: {init}"
    # Version strings are YYYY-MM-DD per spec.
    assert len(init.protocolVersion) == len("2025-11-25")
    assert init.protocolVersion[4] == "-" and init.protocolVersion[7] == "-"


async def test_server_info_present(client) -> None:
    """serverInfo must carry a name; version is SHOULD but usually present."""
    info = client.initialize_result.serverInfo
    assert info.name, f"serverInfo.name missing: {info}"
