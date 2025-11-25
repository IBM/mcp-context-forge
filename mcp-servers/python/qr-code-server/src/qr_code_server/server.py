import asyncio
import json
import logging
import sys
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("qr_code_server")


server = Server("qr-code-server")


class QRCode:
    def __init__(self, config):
        self.config = config
        pass


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="Return the provided text.",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "echo":
        return [TextContent(type="text", text=json.dumps({"ok": True, "echo": arguments["text"]}))]
    return [TextContent(type="text", text=json.dumps({"ok": False, "error": f"unknown tool: {name}"}))]


async def main() -> None:
    log.info("Starting QR Code Server (stdio)...")
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="qr-code-server",
                server_version="0.1.0",
                capabilities={"tools": {}, "logging": {}},
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())

