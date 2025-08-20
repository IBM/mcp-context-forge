#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo script for MCP LangChain Agent.

This script demonstrates how to use the MCP LangChain Agent
both programmatically and via HTTP API calls.
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any

import httpx


async def test_agent_api(base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """Test the LangChain agent API endpoints.

    Args:
        base_url: Base URL of the agent

    Returns:
        Test results dictionary
    """
    results = {
        "health": False,
        "ready": False,
        "tools": 0,
        "chat": False,
        "a2a": False,
        "errors": []
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Test health endpoint
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                results["health"] = True
            else:
                results["errors"].append(f"Health check failed: {response.status_code}")

        except Exception as e:
            results["errors"].append(f"Health check error: {e}")

        try:
            # Test ready endpoint
            response = await client.get(f"{base_url}/ready")
            if response.status_code == 200:
                results["ready"] = True
            else:
                results["errors"].append(f"Ready check failed: {response.status_code}")

        except Exception as e:
            results["errors"].append(f"Ready check error: {e}")

        try:
            # Test tools endpoint
            response = await client.get(f"{base_url}/list_tools")
            if response.status_code == 200:
                data = response.json()
                results["tools"] = len(data.get("tools", []))
            else:
                results["errors"].append(f"Tools list failed: {response.status_code}")

        except Exception as e:
            results["errors"].append(f"Tools list error: {e}")

        try:
            # Test chat completion
            response = await client.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "user", "content": "Say hello briefly"}
                    ],
                    "max_tokens": 10
                }
            )
            if response.status_code == 200:
                results["chat"] = True
            else:
                results["errors"].append(f"Chat completion failed: {response.status_code}")

        except Exception as e:
            results["errors"].append(f"Chat completion error: {e}")

        try:
            # Test A2A endpoint
            response = await client.post(
                f"{base_url}/a2a",
                json={
                    "jsonrpc": "2.0",
                    "id": "demo-test",
                    "method": "list_tools",
                    "params": {}
                }
            )
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    results["a2a"] = True
                else:
                    results["errors"].append(f"A2A response missing result: {data}")
            else:
                results["errors"].append(f"A2A request failed: {response.status_code}")

        except Exception as e:
            results["errors"].append(f"A2A request error: {e}")

    return results


def print_results(results: Dict[str, Any]) -> None:
    """Print test results in a formatted way."""
    print("🎯 Test Results:")
    print("===============")
    print(f"Health Check: {'✅' if results['health'] else '❌'}")
    print(f"Ready Check: {'✅' if results['ready'] else '❌'}")
    print(f"Tools Available: {results['tools']}")
    print(f"Chat API: {'✅' if results['chat'] else '❌'}")
    print(f"A2A API: {'✅' if results['a2a'] else '❌'}")

    if results["errors"]:
        print("\n❌ Errors:")
        for error in results["errors"]:
            print(f"   {error}")

    # Overall status
    all_working = (
        results["health"] and
        results["ready"] and
        results["chat"] and
        results["a2a"]
    )

    print(f"\n🎉 Overall Status: {'✅ WORKING' if all_working else '❌ ISSUES'}")


async def main() -> None:
    """Main demo function."""
    print("🚀 MCP LangChain Agent Demo")
    print("===========================")
    print()

    # Check environment
    print("🔍 Environment Check:")
    openai_key = "✅ Set" if os.getenv("OPENAI_API_KEY") else "❌ Missing"
    gateway_token = "✅ Set" if os.getenv("GATEWAY_BEARER_TOKEN") else "❌ Missing"

    print(f"   OPENAI_API_KEY: {openai_key}")
    print(f"   GATEWAY_BEARER_TOKEN: {gateway_token}")
    print()

    # Test the agent
    print("🧪 Testing Agent Endpoints...")
    results = await test_agent_api()
    print()

    print_results(results)

    # Exit with appropriate code
    if results["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
