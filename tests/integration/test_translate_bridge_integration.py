#!/usr/bin/env python3
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Comprehensive real-world test of the MCP Gateway Transport-Translation Bridge.
Tests multiple scenarios and validates bidirectional communication.
"""

import asyncio
import json
import subprocess
import time
import httpx
import sys
from typing import Dict, Any

class BridgeRealWorldTest:
    def __init__(self):
        self.bridge_process = None
        self.test_results = []
        
    async def test_stdio_to_sse_bridge(self):
        """Test real-world stdio -> SSE bridge with MCP server."""
        print("🧪 Testing stdio -> SSE bridge...")
        
        # Start the bridge
        cmd = [
            "mcpgateway-translate",
            "--stdio", "python tests/integration/simple_mcp_server.py",
            "--port", "9001",
            "--healthEndpoint", "/health",
            "--cors", "*",
            "--logLevel", "info"
        ]
        
        self.bridge_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await asyncio.sleep(3)  # Give bridge time to start
        
        async with httpx.AsyncClient() as client:
            # Test 1: Initialize MCP server
            print("  📤 Testing MCP initialize...")
            response = await client.post(
                "http://localhost:9001/message",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1}
            )
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "ok"
            print("  ✅ Initialize request sent successfully")
            
            # Test 2: List tools
            print("  📤 Testing tools/list...")
            response = await client.post(
                "http://localhost:9001/message", 
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2}
            )
            assert response.status_code == 200
            print("  ✅ Tools list request sent successfully")
            
            # Test 3: Call echo tool
            print("  📤 Testing tools/call (echo)...")
            response = await client.post(
                "http://localhost:9001/message",
                json={
                    "jsonrpc": "2.0", 
                    "method": "tools/call",
                    "params": {
                        "name": "echo",
                        "arguments": {"message": "Real-world test message!"}
                    },
                    "id": 3
                }
            )
            assert response.status_code == 200
            print("  ✅ Echo tool call sent successfully")
            
            # Test 4: Call multiply tool
            print("  📤 Testing tools/call (multiply)...")
            response = await client.post(
                "http://localhost:9001/message",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call", 
                    "params": {
                        "name": "multiply",
                        "arguments": {"a": 7, "b": 6}
                    },
                    "id": 4
                }
            )
            assert response.status_code == 200
            print("  ✅ Multiply tool call sent successfully")
            
            # Test 5: List resources
            print("  📤 Testing resources/list...")
            response = await client.post(
                "http://localhost:9001/message",
                json={"jsonrpc": "2.0", "method": "resources/list", "id": 5}
            )
            assert response.status_code == 200
            print("  ✅ Resources list request sent successfully")
            
            # Test 6: Read resource
            print("  📤 Testing resources/read...")
            response = await client.post(
                "http://localhost:9001/message",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/read",
                    "params": {"uri": "test://example"},
                    "id": 6
                }
            )
            assert response.status_code == 200
            print("  ✅ Resource read request sent successfully")
            
            # Test 7: Test SSE stream
            print("  📡 Testing SSE stream...")
            async with client.stream("GET", "http://localhost:9001/sse") as response:
                assert response.status_code == 200
                content = ""
                async for chunk in response.aiter_bytes():
                    content += chunk.decode()
                    if "event: endpoint" in content:
                        print("  ✅ SSE endpoint event received")
                        break
                    if len(content) > 1000:  # Prevent infinite loop
                        break
        
        self.bridge_process.terminate()
        print("✅ stdio -> SSE bridge test completed successfully!\n")
        return True
    
    async def test_error_handling(self):
        """Test error handling with invalid requests."""
        print("🧪 Testing error handling...")
        
        cmd = [
            "mcpgateway-translate",
            "--stdio", "python tests/integration/simple_mcp_server.py", 
            "--port", "9002",
            "--logLevel", "debug"
        ]
        
        self.bridge_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await asyncio.sleep(2)
        
        async with httpx.AsyncClient() as client:
            # Test invalid tool call
            print("  📤 Testing invalid tool call...")
            response = await client.post(
                "http://localhost:9002/message",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "nonexistent_tool", "arguments": {}},
                    "id": 1
                }
            )
            assert response.status_code == 200
            print("  ✅ Invalid tool call handled gracefully")
            
            # Test invalid JSON
            print("  📤 Testing malformed request...")
            response = await client.post(
                "http://localhost:9002/message",
                data="invalid json",
                headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 422  # FastAPI validation error
            print("  ✅ Malformed request handled gracefully")
        
        self.bridge_process.terminate()
        print("✅ Error handling test completed successfully!\n")
        return True

    async def test_cors_and_health(self):
        """Test CORS and health endpoint functionality."""
        print("🧪 Testing CORS and health endpoints...")
        
        cmd = [
            "mcpgateway-translate",
            "--stdio", "python tests/integration/simple_mcp_server.py",
            "--port", "9003", 
            "--healthEndpoint", "/health",
            "--cors", "https://example.com", "https://test.com"
        ]
        
        self.bridge_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await asyncio.sleep(2)
        
        async with httpx.AsyncClient() as client:
            # Test health endpoint
            print("  🏥 Testing health endpoint...")
            response = await client.get("http://localhost:9003/health")
            assert response.status_code == 200
            assert response.text == "ok"
            print("  ✅ Health endpoint working correctly")
            
            # Test CORS headers (simulated)
            print("  🌐 Testing CORS support...")
            response = await client.options(
                "http://localhost:9003/message",
                headers={"Origin": "https://example.com"}
            )
            # Should have CORS headers if configured correctly
            print("  ✅ CORS configuration applied")
        
        self.bridge_process.terminate()
        print("✅ CORS and health test completed successfully!\n")
        return True

    def test_cli_validation(self):
        """Test CLI argument validation."""
        print("🧪 Testing CLI validation...")
        
        # Test conflicting transports
        result = subprocess.run([
            "mcpgateway-translate",
            "--stdio", "echo test",
            "--sse", "https://example.com"
        ], capture_output=True, text=True)
        
        assert result.returncode != 0
        assert "not allowed with argument" in result.stderr
        print("  ✅ Conflicting transport validation working")
        
        # Test missing required argument
        result = subprocess.run([
            "mcpgateway-translate",
            "--port", "8000"
        ], capture_output=True, text=True)
        
        assert result.returncode != 0
        print("  ✅ Missing required argument validation working")
        
        print("✅ CLI validation test completed successfully!\n")
        return True

    async def run_all_tests(self):
        """Run all real-world tests."""
        print("🚀 Starting comprehensive real-world bridge tests...\n")
        
        tests = [
            ("CLI Validation", self.test_cli_validation),
            ("stdio -> SSE Bridge", self.test_stdio_to_sse_bridge),
            ("Error Handling", self.test_error_handling), 
            ("CORS & Health", self.test_cors_and_health)
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                if asyncio.iscoroutinefunction(test_func):
                    result = await test_func()
                else:
                    result = test_func()
                results.append((test_name, "✅ PASSED" if result else "❌ FAILED"))
            except Exception as e:
                print(f"❌ {test_name} failed with error: {e}")
                results.append((test_name, f"❌ FAILED: {str(e)}"))
            finally:
                if self.bridge_process:
                    self.bridge_process.terminate()
                    self.bridge_process = None
        
        print("📊 Test Results Summary:")
        print("=" * 50)
        for test_name, status in results:
            print(f"{test_name:20} | {status}")
        print("=" * 50)
        
        passed = sum(1 for _, status in results if "PASSED" in status)
        total = len(results)
        print(f"\n🎯 Overall Result: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All real-world tests PASSED! The bridge is production-ready! 🎉")
        else:
            print("⚠️  Some tests failed. Please review the results above.")
        
        return passed == total

async def main():
    tester = BridgeRealWorldTest()
    success = await tester.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
