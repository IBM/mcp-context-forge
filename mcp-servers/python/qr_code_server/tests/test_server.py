import logging
import types
import pytest
from fastmcp.client import Client
from qr_code_server.server import mcp


logger = logging.getLogger("qr_code_server")


def test_qr_code_tool_schema_importable():
    mod = __import__('qr_code_server.server', fromlist=['server'])
    assert isinstance(mod, types.ModuleType)


@pytest.mark.asyncio
async def test_tool_registration():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "generate_qr_code" in names
