"""MCP pagination compliance tests — cursor-based iteration over long list responses.

The reference server registers 120 ``stub_NNN`` tools; any sensible default
page size is exceeded, so a compliant client that iterates to exhaustion
must see them all.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_utilities]


async def test_list_tools_returns_all_stubs(connect) -> None:
    """FastMCP's Client exhausts cursors internally; every stub must be present.

    GAP-007 (gateway tools/list page-size cap) was closed upstream; the xfail
    marker was removed after the matrix harness surfaced XPASS on every
    gateway row. The test is now a plain-pass assertion on all targets.
    """
    # Note: the gateway-prefixed names break the ``startswith('stub_')`` check —
    # accept either bare or slug-prefixed forms.
    async with connect() as client:
        tools = await client.list_tools()
    stub_names = [t.name for t in tools if t.name.startswith("stub_") or "-stub-" in t.name]
    assert len(stub_names) >= 120, f"expected >=120 stub tools exposed across pages, got {len(stub_names)}. " "This fails if the client or server truncates list pagination."


async def test_list_tools_stub_names_are_unique(connect) -> None:
    """Pagination must not double-count entries across page boundaries."""
    async with connect() as client:
        names = [t.name for t in await client.list_tools()]
    assert len(names) == len(set(names)), "duplicate tool names across paginated pages"
