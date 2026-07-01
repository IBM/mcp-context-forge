"""Minimal stateful MCP counter (streamable HTTP) for the #4205 isolation repro.

State is kept PER MCP SESSION (keyed by the ServerSession object), so if the
gateway scatters a session's calls onto a second upstream connection, that new
connection sees a fresh counter -- which is exactly what the test detects.

Port is configurable via COUNTER_PORT (default 9400) so a second instance can
run on :9401 for the multi-upstream test.
"""

import os

from mcp.server.fastmcp import Context, FastMCP

PORT = int(os.environ.get("COUNTER_PORT", "9400"))

mcp = FastMCP("repro-counter", host="0.0.0.0", port=PORT)

# per-session counters, keyed by the upstream ServerSession identity
_counters: dict[int, int] = {}


@mcp.tool()
def increment(ctx: Context) -> int:
    """Increment this session's counter and return the new value."""
    key = id(ctx.session)
    _counters[key] = _counters.get(key, 0) + 1
    return _counters[key]


@mcp.tool()
def get_value(ctx: Context) -> int:
    """Return this session's current counter value."""
    return _counters.get(id(ctx.session), 0)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
