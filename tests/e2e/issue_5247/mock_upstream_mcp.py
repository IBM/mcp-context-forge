"""Minimal real MCP server over SSE, used as the e2e 'authorized upstream' for issue #5247.

Requires a Bearer token matching E2E_EXPECTED_TOKEN on every request (mimicking an
OAuth-protected MCP server) so the e2e script can prove the gateway forwards the
resolved token, not just that it connects.
"""
import os

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

EXPECTED_TOKEN = os.environ["E2E_EXPECTED_TOKEN"]
PORT = int(os.environ["E2E_UPSTREAM_PORT"])

mcp = FastMCP("e2e-upstream")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text back. The one real tool this upstream exposes."""
    return text


app = mcp.sse_app()


class _AuthGate:
    """ASGI middleware rejecting any request without the expected bearer token."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth != f"Bearer {EXPECTED_TOKEN}":
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.inner(scope, receive, send)


app = _AuthGate(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
