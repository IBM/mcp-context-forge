#!/usr/bin/env python3
"""
Manual test script for sessionless MCP protocol with Streamable HTTP transport.

This script demonstrates that the sessionless protocol (>= 2025-11-25) works
without requiring Mcp-Session-Id headers.

Usage:
    python test_sessionless_manual.py

Requirements:
    - ContextForge gateway running on http://localhost:8000
    - A test MCP server registered (or use the built-in test server)
"""

import asyncio
import httpx
import json
import sys
from typing import Optional


class SessionlessProtocolTester:
    """Test sessionless MCP protocol with Streamable HTTP transport."""

    def __init__(self, base_url: str = "http://localhost:8000", bearer_token: str = None):
        self.base_url = base_url
        headers = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self.client = httpx.AsyncClient(timeout=30.0, headers=headers)
        self.session_id: Optional[str] = None

    async def test_initialize_sessionless(self) -> bool:
        """Test initialize without session ID (sessionless protocol)."""
        print("\n" + "=" * 80)
        print("TEST 1: Initialize with sessionless protocol (>= 2025-11-25)")
        print("=" * 80)

        url = f"{self.base_url}/mcp/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # NO Mcp-Session-Id header - this is the key test
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",  # Sessionless protocol version
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {}
                },
                "clientInfo": {
                    "name": "sessionless-test-client",
                    "version": "1.0.0"
                }
            }
        }

        print(f"\nRequest URL: {url}")
        print(f"Request Headers: {json.dumps(headers, indent=2)}")
        print(f"Request Payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            print(f"\nResponse Status: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")

            if response.status_code == 200:
                result = response.json()
                print(f"Response Body: {json.dumps(result, indent=2)}")

                # Check if we got a session ID back (we shouldn't need it)
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    print(f"\n⚠️  Server returned session ID: {session_id}")
                    print("   (This is OK - server can return it, but client doesn't need to use it)")
                    self.session_id = session_id
                else:
                    print("\n✅ No session ID returned (fully sessionless)")

                print("\n✅ TEST PASSED: Initialize succeeded without session ID")
                return True
            else:
                print(f"\n❌ TEST FAILED: Expected 200, got {response.status_code}")
                print(f"Response: {response.text}")
                return False

        except Exception as e:
            print(f"\n❌ TEST FAILED: Exception occurred: {e}")
            return False

    async def test_list_tools_sessionless(self) -> bool:
        """Test tools/list without session ID."""
        print("\n" + "=" * 80)
        print("TEST 2: List tools without session ID")
        print("=" * 80)

        url = f"{self.base_url}/mcp/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # NO Mcp-Session-Id header
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }

        print(f"\nRequest URL: {url}")
        print(f"Request Headers: {json.dumps(headers, indent=2)}")
        print(f"Request Payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            print(f"\nResponse Status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"Response Body: {json.dumps(result, indent=2)}")
                print("\n✅ TEST PASSED: tools/list succeeded without session ID")
                return True
            else:
                print(f"\n❌ TEST FAILED: Expected 200, got {response.status_code}")
                print(f"Response: {response.text}")
                return False

        except Exception as e:
            print(f"\n❌ TEST FAILED: Exception occurred: {e}")
            return False

    async def test_list_prompts_sessionless(self) -> bool:
        """Test prompts/list without session ID."""
        print("\n" + "=" * 80)
        print("TEST 3: List prompts without session ID")
        print("=" * 80)

        url = f"{self.base_url}/mcp/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # NO Mcp-Session-Id header
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompts/list",
            "params": {}
        }

        print(f"\nRequest URL: {url}")
        print(f"Request Headers: {json.dumps(headers, indent=2)}")
        print(f"Request Payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            print(f"\nResponse Status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"Response Body: {json.dumps(result, indent=2)}")
                print("\n✅ TEST PASSED: prompts/list succeeded without session ID")
                return True
            else:
                print(f"\n❌ TEST FAILED: Expected 200, got {response.status_code}")
                print(f"Response: {response.text}")
                return False

        except Exception as e:
            print(f"\n❌ TEST FAILED: Exception occurred: {e}")
            return False

    async def test_list_resources_sessionless(self) -> bool:
        """Test resources/list without session ID."""
        print("\n" + "=" * 80)
        print("TEST 4: List resources without session ID")
        print("=" * 80)

        url = f"{self.base_url}/mcp/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # NO Mcp-Session-Id header
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/list",
            "params": {}
        }

        print(f"\nRequest URL: {url}")
        print(f"Request Headers: {json.dumps(headers, indent=2)}")
        print(f"Request Payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            print(f"\nResponse Status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"Response Body: {json.dumps(result, indent=2)}")
                print("\n✅ TEST PASSED: resources/list succeeded without session ID")
                return True
            else:
                print(f"\n❌ TEST FAILED: Expected 200, got {response.status_code}")
                print(f"Response: {response.text}")
                return False

        except Exception as e:
            print(f"\n❌ TEST FAILED: Exception occurred: {e}")
            return False

    async def test_legacy_sessionful_protocol(self) -> bool:
        """Test that legacy sessionful protocol still works."""
        print("\n" + "=" * 80)
        print("TEST 5: Initialize with legacy sessionful protocol (< 2025-11-25)")
        print("=" * 80)

        url = f"{self.base_url}/mcp/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",  # Legacy sessionful protocol
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {}
                },
                "clientInfo": {
                    "name": "legacy-test-client",
                    "version": "1.0.0"
                }
            }
        }

        print(f"\nRequest URL: {url}")
        print(f"Request Headers: {json.dumps(headers, indent=2)}")
        print(f"Request Payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            print(f"\nResponse Status: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")

            if response.status_code == 200:
                result = response.json()
                print(f"Response Body: {json.dumps(result, indent=2)}")

                # Legacy protocol should return a session ID
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    print(f"\n✅ Session ID returned: {session_id}")
                    print("   (Expected for legacy sessionful protocol)")
                else:
                    print("\n⚠️  No session ID returned (unexpected for legacy protocol)")

                print("\n✅ TEST PASSED: Legacy protocol still works")
                return True
            else:
                print(f"\n❌ TEST FAILED: Expected 200, got {response.status_code}")
                print(f"Response: {response.text}")
                return False

        except Exception as e:
            print(f"\n❌ TEST FAILED: Exception occurred: {e}")
            return False

    async def run_all_tests(self) -> bool:
        """Run all tests and return overall success."""
        print("\n" + "=" * 80)
        print("SESSIONLESS MCP PROTOCOL MANUAL TEST SUITE")
        print("=" * 80)
        print("\nThis test suite verifies that the sessionless MCP protocol")
        print("(>= 2025-11-25) works without requiring Mcp-Session-Id headers.")
        print("\nTarget: " + self.base_url)

        results = []

        # Test sessionless protocol
        results.append(await self.test_initialize_sessionless())
        results.append(await self.test_list_tools_sessionless())
        results.append(await self.test_list_prompts_sessionless())
        results.append(await self.test_list_resources_sessionless())

        # Test backward compatibility
        results.append(await self.test_legacy_sessionful_protocol())

        # Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        passed = sum(results)
        total = len(results)
        print(f"\nPassed: {passed}/{total}")

        if passed == total:
            print("\n✅ ALL TESTS PASSED")
            print("\nThe sessionless MCP protocol is working correctly!")
            print("- Initialize works without session ID")
            print("- List operations work without session ID")
            print("- Legacy sessionful protocol still works")
            return True
        else:
            print(f"\n❌ {total - passed} TEST(S) FAILED")
            print("\nPlease check the output above for details.")
            return False

    async def cleanup(self):
        """Cleanup resources."""
        await self.client.aclose()


async def main():
    """Main entry point."""
    # Get bearer token from environment
    import os
    bearer_token = os.environ.get("TOKEN") or os.environ.get("MCPGATEWAY_BEARER_TOKEN")

    if not bearer_token:
        print("ERROR: No bearer token found. Set TOKEN or MCPGATEWAY_BEARER_TOKEN environment variable.")
        sys.exit(1)

    tester = SessionlessProtocolTester(bearer_token=bearer_token)
    try:
        success = await tester.run_all_tests()
        sys.exit(0 if success else 1)
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
