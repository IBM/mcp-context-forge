"""MCP lifecycle compliance tests.

The client fixture has already run the initialize handshake by the time a
test body executes; these probes confirm the session is live and responsive.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_lifecycle]


async def test_session_is_connected(client: Client) -> None:
    assert client.is_connected()


async def test_ping_roundtrip(client: Client) -> None:
    await client.ping()
