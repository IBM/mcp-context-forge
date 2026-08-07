# -*- coding: utf-8 -*-
"""Echo MCP server for Vault plugin E2E testing.

Simple SSE-based MCP server that echoes requests back and logs received headers.
Used to verify that the Vault plugin correctly injects Bearer tokens and strips
the X-Vault-Tokens header on the MCP tool invocation path.

Location: ./plugins/vault/echo_mcp.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Third-Party
from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_http_headers

mcp = FastMCP("Demo 🚀")


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of a and b
    """
    headers = get_http_headers(include_all=True)
    print(f"headers: {headers} message: {a} + {b} ")  # print headers out
    return a + b


@mcp.tool
def hello(ctx: Context):
    """Simple hello tool for testing.

    Args:
        ctx: FastMCP context

    Returns:
        Hello response dict
    """
    ctx.info("in Hello!")
    return {"Respone": "Hello!"}


@mcp.tool
def echo(message: str) -> str:
    """Echo tool that reflects message and logs headers.

    Primary test tool - logs all received headers to stdout for E2E verification.

    Args:
        message: Message to echo back

    Returns:
        The same message
    """
    headers = get_http_headers(include_all=True)
    print(f"headers: {headers} message: {message} ")  # print headers out
    return message


# Static resource
@mcp.resource("config://version")
def get_version(ctx: Context):
    """Return version resource.

    Args:
        ctx: FastMCP context

    Returns:
        Version string
    """
    ctx.info("Sono in get_version!")
    return "2.0.1"


if __name__ == "__main__":
    mcp.run(transport="sse", port=8001)
