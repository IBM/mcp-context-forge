# streamablehttptransport.py

import logging
import contextlib
from collections.abc import AsyncIterator
import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send
from typing import Any, Dict, List, Optional, Union

from mcpgateway.services.tool_service import ToolService
from mcpgateway.db import SessionLocal


logger = logging.getLogger(__name__)

# This is the MCP configuration from your script's CLI options.
# You can get these from environment variables, a config file, or hardcode them.
JSON_RESPONSE_ENABLED = False


tool_service = ToolService()


# Initialize MCP app
mcp_app = Server("mcp-streamable-http-stateless-demo")

@mcp_app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
    with SessionLocal() as db:
        result = await tool_service.invoke_tool(db, name, arguments)
        
        tool_result =  [
            types.TextContent(
                type=result.content[0].type,
                text=(
                    result.content[0].text
                ),
            )
        ]
        return tool_result
    
@mcp_app.list_tools()
async def list_tools() -> list[types.Tool]:

    with SessionLocal() as db:
        tools = await tool_service.list_tools(db)
        listed_tools = []
        for tool in tools:
            listed_tools.append(types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema
            ))

        return listed_tools


# --- 2. Create and Configure MCP Session Manager ---
session_manager = StreamableHTTPSessionManager(
    app=mcp_app,
    event_store=None,
    json_response=JSON_RESPONSE_ENABLED,
    stateless=True,
)

# This is the handler that will process requests for the mounted path.
async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
    await session_manager.handle_request(scope, receive, send)

# --- 3. Lifespan Management to Start/Stop the Session Manager ---
# @contextlib.asynccontextmanager
# async def lifespan(app: FastAPI) -> AsyncIterator[None]:
#     """Manages the startup and shutdown of the MCP session manager."""
#     async with session_manager.run():
#         logger.info("Application starting with MCP StreamableHTTPSessionManager!")
#         yield
#     logger.info("Application shutting down...")

async def start_streamablehttp():
    # await session_manager.run()
    # session = await session_manager.run().__aenter__()
    # logger.info("Application starting with MCP StreamableHTTPSessionManager!")
    async with session_manager.run():
        logger.info("Application starting with MCP StreamableHTTPSessionManager!")
        # yield
    

async def stop_streamablehttp():
    # await session_manager.stop()
    # await session_manager.run().__aexit__(None, None, None)
    logger.info("StreamableHTTPSessionManager shutting down...")
