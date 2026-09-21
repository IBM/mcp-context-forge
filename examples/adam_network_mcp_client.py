"""Adam Network Model Context Protocol (MCP) integration for IBM/mcp-context-forge.

Connects to Adam Network remote MCP server (SSE / Streamable HTTP) or stdio.
Hosted SSE Endpoint: https://adam-network.up.railway.app/mcp/sse
"""

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

async def main():
    mcp_url = "https://adam-network.up.railway.app/mcp/sse"
    print(f"Connecting to Adam Network MCP at {mcp_url}...")

    client = MultiServerMCPClient({
        "adam_network": {
            "transport": "sse",
            "url": mcp_url,
        }
    })

    tools = await client.get_tools()
    print(f"Loaded {len(tools)} MCP tools from Adam Network:")
    for tool in tools:
        print(f" - {getattr(tool, 'name', 'unnamed')}: {getattr(tool, 'description', '')[:60]}...")

if __name__ == "__main__":
    asyncio.run(main())
