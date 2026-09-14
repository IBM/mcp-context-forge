# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/reverse_proxy/helpers/auth_probe_server.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Minimal auth-aware MCP server for reverse-proxy live verification.
"""

from __future__ import annotations

import argparse
import os
from typing import Final

from fastmcp import FastMCP
from fastmcp.dependencies import CurrentHeaders

EXPECTED_AUTHORIZATION: Final = os.environ.get("T8_EXPECTED_AUTHORIZATION", "")
mcp = FastMCP(name="reverse-proxy-auth-probe", version="1.0.0")


@mcp.tool(description="Report whether the expected downstream authorization header arrived.")
def auth_probe(headers: dict[str, str] = CurrentHeaders()) -> str:
    """Return a non-sensitive authorization verdict."""
    return "authorized" if headers.get("authorization") == EXPECTED_AUTHORIZATION else "missing"


def main() -> None:
    """Run the Streamable HTTP probe server."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=19200)
    args = parser.parse_args()
    mcp.run(transport="http", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
