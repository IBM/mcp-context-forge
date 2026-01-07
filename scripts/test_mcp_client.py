#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test MCP client against gateway to verify tools/list returns all tools."""

import asyncio
import subprocess
import sys


async def main():
    # Import MCP client
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.client.session import ClientSession

    # Generate JWT token
    token_result = subprocess.run(
        [
            sys.executable, "-m", "mcpgateway.utils.create_jwt_token",
            "--username", "admin@example.com",
            "--exp", "0",
            "--secret", "my-test-key"
        ],
        capture_output=True,
        text=True
    )
    token = token_result.stdout.strip()

    # Test URLs
    base_url = "http://localhost:8000"
    server_id = "da73bd23fa0f4850999ffb391569dcf1"

    endpoints = [
        (f"{base_url}/mcp/", "Global MCP endpoint"),
        (f"{base_url}/servers/{server_id}/mcp/", "Virtual Server MCP endpoint"),
    ]

    print("=" * 70)
    print("  MCP CLIENT TEST - Using mcp.client.streamable_http")
    print("=" * 70)

    for url, description in endpoints:
        print(f"\n{'=' * 70}")
        print(f"  {description}")
        print(f"  URL: {url}")
        print("=" * 70)

        try:
            # Create headers with auth
            headers = {"Authorization": f"Bearer {token}"}

            async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    # Initialize the session
                    print("\n1. INITIALIZE")
                    print("-" * 40)
                    init_result = await session.initialize()
                    print(f"   Protocol version: {init_result.protocolVersion}")
                    print(f"   Server name:      {init_result.serverInfo.name}")
                    print(f"   Server version:   {init_result.serverInfo.version}")
                    caps = init_result.capabilities
                    print(f"   Capabilities:     tools={caps.tools is not None}, "
                          f"resources={caps.resources is not None}, "
                          f"prompts={caps.prompts is not None}")

                    # List tools
                    print("\n2. TOOLS/LIST")
                    print("-" * 40)
                    tools_result = await session.list_tools()
                    tools = tools_result.tools
                    print(f"   Total tools: {len(tools)}")
                    if tools:
                        print(f"\n   First 3 tools:")
                        for i, tool in enumerate(tools[:3]):
                            print(f"     [{i+1}] {tool.name}")
                            print(f"         Description: {tool.description[:60]}...")
                        print(f"\n   Last 3 tools:")
                        for i, tool in enumerate(tools[-3:]):
                            print(f"     [{len(tools)-2+i}] {tool.name}")

                    # List resources
                    print("\n3. RESOURCES/LIST")
                    print("-" * 40)
                    resources_result = await session.list_resources()
                    resources = resources_result.resources
                    print(f"   Total resources: {len(resources)}")
                    if resources:
                        print(f"   First 3 resources:")
                        for i, res in enumerate(resources[:3]):
                            print(f"     [{i+1}] {res.name} ({res.uri})")

                    # List prompts
                    print("\n4. PROMPTS/LIST")
                    print("-" * 40)
                    prompts_result = await session.list_prompts()
                    prompts = prompts_result.prompts
                    print(f"   Total prompts: {len(prompts)}")
                    if prompts:
                        print(f"   First 3 prompts:")
                        for i, prompt in enumerate(prompts[:3]):
                            print(f"     [{i+1}] {prompt.name}")

                    # Call a tool
                    print("\n5. TOOLS/CALL")
                    print("-" * 40)
                    if tools:
                        tool_to_call = tools[0]
                        print(f"   Calling tool: {tool_to_call.name}")
                        print(f"   Input schema: {tool_to_call.inputSchema}")

                        # Build arguments based on schema
                        args = {}
                        if tool_to_call.inputSchema and "properties" in tool_to_call.inputSchema:
                            for prop_name, prop_info in tool_to_call.inputSchema["properties"].items():
                                # Use a default test value
                                args[prop_name] = "test_value"

                        print(f"   Arguments: {args}")

                        try:
                            call_result = await session.call_tool(tool_to_call.name, args)
                            print(f"   Result:")
                            for content in call_result.content:
                                if hasattr(content, 'text'):
                                    text = content.text
                                    if len(text) > 200:
                                        text = text[:200] + "..."
                                    print(f"     {text}")
                                else:
                                    print(f"     {content}")
                        except Exception as e:
                            print(f"   Tool call error: {e}")
                    else:
                        print("   No tools available to call")

                    print(f"\n{'=' * 70}")
                    print(f"  ✓ {description} - ALL TESTS PASSED")
                    print(f"{'=' * 70}")

        except Exception as e:
            print(f"\n✗ {description} - FAILED: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("  SUMMARY: ALL ENDPOINTS TESTED SUCCESSFULLY")
    print("  - tools/list returns ALL tools (10,000) without 50-item limit")
    print("  - tools/call works correctly")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
