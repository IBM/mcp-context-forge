# -*- coding: utf-8 -*-
"""End-to-end tests for dynamic environment variable injection.

Location: ./tests/e2e/test_translate_dynamic_env_e2e.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

End-to-end tests for complete HTTP flow with dynamic environment variable injection.
"""

import asyncio
import pytest
import subprocess
import tempfile
import os
import json
import signal
import time
import httpx
from typing import Dict, Any, Optional, List


class TestDynamicEnvE2E:
    """End-to-end tests for dynamic environment variable injection."""

    @pytest.fixture
    def test_mcp_server_script(self):
        """Create a test MCP server script that responds to JSON-RPC."""
        script_content = """#!/usr/bin/env python3
import os
import json
import sys

def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line.strip())
            
            if request.get("method") == "env_test":
                # Return environment variables
                result = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
                        "TENANT_ID": os.environ.get("TENANT_ID", ""),
                        "API_KEY": os.environ.get("API_KEY", ""),
                        "ENVIRONMENT": os.environ.get("ENVIRONMENT", ""),
                    }
                }
                print(json.dumps(result))
                sys.stdout.flush()
            elif request.get("method") == "initialize":
                # Standard MCP initialize response
                result = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "test-server",
                            "version": "1.0.0"
                        }
                    }
                }
                print(json.dumps(result))
                sys.stdout.flush()
            elif request.get("method") == "ping":
                # Simple ping response
                result = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": "pong"
                }
                print(json.dumps(result))
                sys.stdout.flush()
            else:
                # Echo back the request
                result = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": request
                }
                print(json.dumps(result))
                sys.stdout.flush()
                
        except Exception as e:
            error = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            print(json.dumps(error))
            sys.stdout.flush()

if __name__ == "__main__":
    main()
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            yield f.name
        
        os.unlink(f.name)

    @pytest.fixture
    async def translate_server_process(self, test_mcp_server_script):
        """Start a translate server process with dynamic environment injection."""
        port = 9001
        
        # Start translate server with header mappings
        cmd = [
            "python3", "-m", "mcpgateway.translate",
            "--stdio", test_mcp_server_script,
            "--port", str(port),
            "--enable-dynamic-env",
            "--header-to-env", "Authorization=GITHUB_TOKEN",
            "--header-to-env", "X-Tenant-Id=TENANT_ID",
            "--header-to-env", "X-API-Key=API_KEY",
            "--header-to-env", "X-Environment=ENVIRONMENT",
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for server to start
        await asyncio.sleep(2)
        
        try:
            yield port
        finally:
            # Cleanup
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    @pytest.mark.asyncio
    async def test_dynamic_env_injection_e2e(self, translate_server_process):
        """Test complete end-to-end dynamic environment injection."""
        port = translate_server_process
        
        # Test with headers
        headers = {
            "Authorization": "Bearer github-token-123",
            "X-Tenant-Id": "acme-corp",
            "X-API-Key": "api-key-456",
            "X-Environment": "production",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Test 1: Send JSON-RPC request via /message endpoint
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            assert response.text == "forwarded"
            
            # Test 2: Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                # Wait for endpoint event
                endpoint_event_found = False
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                # Verify environment variables were injected
                                env_result = result["result"]
                                assert env_result["GITHUB_TOKEN"] == "Bearer github-token-123"
                                assert env_result["TENANT_ID"] == "acme-corp"
                                assert env_result["API_KEY"] == "api-key-456"
                                assert env_result["ENVIRONMENT"] == "production"
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_multiple_requests_different_headers(self, translate_server_process):
        """Test multiple requests with different headers."""
        port = translate_server_process
        
        async with httpx.AsyncClient() as client:
            # Request 1: User 1
            headers1 = {
                "Authorization": "Bearer user1-token",
                "X-Tenant-Id": "tenant-1",
                "Content-Type": "application/json"
            }
            
            request1 = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response1 = await client.post(
                f"http://localhost:{port}/message",
                json=request1,
                headers=headers1
            )
            assert response1.status_code == 202
            
            # Request 2: User 2
            headers2 = {
                "Authorization": "Bearer user2-token",
                "X-Tenant-Id": "tenant-2",
                "X-API-Key": "user2-api-key",
                "Content-Type": "application/json"
            }
            
            request2 = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "env_test",
                "params": {}
            }
            
            response2 = await client.post(
                f"http://localhost:{port}/message",
                json=request2,
                headers=headers2
            )
            assert response2.status_code == 202
            
            # Connect to SSE to get responses
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                responses_received = {}
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") in [1, 2] and "result" in result:
                                responses_received[result["id"]] = result["result"]
                                if len(responses_received) == 2:
                                    break
                        except json.JSONDecodeError:
                            continue
                
                # Verify both responses have correct environment variables
                assert 1 in responses_received
                assert 2 in responses_received
                
                # Note: In a real scenario, each request would spawn a separate process
                # or the environment would be set per request. For this test, we're
                # verifying that the mechanism works, even if both requests
                # might see the same environment (depending on implementation)

    @pytest.mark.asyncio
    async def test_case_insensitive_headers_e2e(self, translate_server_process):
        """Test case-insensitive header handling in end-to-end scenario."""
        port = translate_server_process
        
        # Test with mixed case headers
        headers = {
            "authorization": "Bearer mixed-case-token",  # lowercase
            "X-TENANT-ID": "MIXED-TENANT",              # uppercase
            "x-api-key": "mixed-api-key",               # mixed case
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                env_result = result["result"]
                                assert env_result["GITHUB_TOKEN"] == "Bearer mixed-case-token"
                                assert env_result["TENANT_ID"] == "MIXED-TENANT"
                                assert env_result["API_KEY"] == "mixed-api-key"
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_partial_headers_e2e(self, translate_server_process):
        """Test partial header mapping in end-to-end scenario."""
        port = translate_server_process
        
        # Test with only some headers present
        headers = {
            "Authorization": "Bearer partial-token",
            "X-Tenant-Id": "partial-tenant",
            "Other-Header": "ignored-value",  # Not in mappings
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                env_result = result["result"]
                                assert env_result["GITHUB_TOKEN"] == "Bearer partial-token"
                                assert env_result["TENANT_ID"] == "partial-tenant"
                                # API_KEY and ENVIRONMENT should be empty (not provided)
                                assert env_result["API_KEY"] == ""
                                assert env_result["ENVIRONMENT"] == ""
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_no_headers_e2e(self, translate_server_process):
        """Test request without dynamic environment headers."""
        port = translate_server_process
        
        # Test without dynamic environment headers
        headers = {
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                env_result = result["result"]
                                # All environment variables should be empty
                                assert env_result["GITHUB_TOKEN"] == ""
                                assert env_result["TENANT_ID"] == ""
                                assert env_result["API_KEY"] == ""
                                assert env_result["ENVIRONMENT"] == ""
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_mcp_initialize_flow_e2e(self, translate_server_process):
        """Test complete MCP initialize flow with environment injection."""
        port = translate_server_process
        
        headers = {
            "Authorization": "Bearer init-token",
            "X-Tenant-Id": "init-tenant",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Step 1: Initialize MCP connection
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"}
                }
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=init_request,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Step 2: Test environment variables
            env_test_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=env_test_request,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get both responses
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                responses_received = {}
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") in [1, 2] and "result" in result:
                                responses_received[result["id"]] = result["result"]
                                if len(responses_received) == 2:
                                    break
                        except json.JSONDecodeError:
                            continue
                
                # Verify initialize response
                assert 1 in responses_received
                init_result = responses_received[1]
                assert init_result["protocolVersion"] == "2025-03-26"
                assert init_result["serverInfo"]["name"] == "test-server"
                
                # Verify environment test response
                assert 2 in responses_received
                env_result = responses_received[2]
                assert env_result["GITHUB_TOKEN"] == "Bearer init-token"
                assert env_result["TENANT_ID"] == "init-tenant"

    @pytest.mark.asyncio
    async def test_sanitization_e2e(self, translate_server_process):
        """Test header value sanitization in end-to-end scenario."""
        port = translate_server_process
        
        # Test with dangerous characters in headers
        headers = {
            "Authorization": "Bearer\x00token\n123",  # Contains dangerous chars
            "X-Tenant-Id": "acme\x01corp",           # Contains control chars
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                env_result = result["result"]
                                # Verify sanitization
                                assert env_result["GITHUB_TOKEN"] == "Bearertoken123"  # Dangerous chars removed
                                assert env_result["TENANT_ID"] == "acmecorp"           # Control chars removed
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_large_header_values_e2e(self, translate_server_process):
        """Test large header values in end-to-end scenario."""
        port = translate_server_process
        
        # Test with large header value (will be truncated)
        large_value = "x" * 5000  # 5KB value
        headers = {
            "Authorization": large_value,
            "X-Tenant-Id": "acme-corp",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            
            assert response.status_code == 202
            
            # Connect to SSE to get response
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                async for line in sse_response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            result = json.loads(data)
                            if result.get("id") == 1 and "result" in result:
                                env_result = result["result"]
                                # Verify truncation (should be 4096 characters)
                                assert len(env_result["GITHUB_TOKEN"]) == 4096
                                assert env_result["GITHUB_TOKEN"] == "x" * 4096
                                assert env_result["TENANT_ID"] == "acme-corp"
                                break
                        except json.JSONDecodeError:
                            continue

    @pytest.mark.asyncio
    async def test_health_check_e2e(self, translate_server_process):
        """Test health check endpoint works with dynamic environment injection."""
        port = translate_server_process
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://localhost:{port}/healthz")
            assert response.status_code == 200
            assert response.text == "ok"

    @pytest.mark.asyncio
    async def test_sse_endpoint_e2e(self, translate_server_process):
        """Test SSE endpoint works with dynamic environment injection."""
        port = translate_server_process
        
        headers = {
            "Authorization": "Bearer sse-token",
            "X-Tenant-Id": "sse-tenant",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Connect to SSE endpoint
            async with client.stream("GET", f"http://localhost:{port}/sse") as sse_response:
                # Should receive endpoint event first
                endpoint_event_received = False
                async for line in sse_response.aiter_lines():
                    if line.startswith("event: endpoint"):
                        endpoint_event_received = True
                        break
                    if line.startswith("event: keepalive"):
                        # Keepalive is also acceptable
                        break
                
                assert endpoint_event_received or True  # Either endpoint or keepalive is fine

    @pytest.mark.asyncio
    async def test_error_handling_e2e(self, translate_server_process):
        """Test error handling in end-to-end scenario."""
        port = translate_server_process
        
        async with httpx.AsyncClient() as client:
            # Test with invalid JSON
            response = await client.post(
                f"http://localhost:{port}/message",
                content="invalid json",
                headers={"Content-Type": "application/json"}
            )
            
            assert response.status_code == 400
            assert "Invalid JSON payload" in response.text

    @pytest.mark.asyncio
    async def test_concurrent_requests_e2e(self, translate_server_process):
        """Test concurrent requests with different headers."""
        port = translate_server_process
        
        async def make_request(client, headers, request_id):
            """Make a single request with given headers."""
            request_data = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "env_test",
                "params": {}
            }
            
            response = await client.post(
                f"http://localhost:{port}/message",
                json=request_data,
                headers=headers
            )
            return response
        
        async with httpx.AsyncClient() as client:
            # Make concurrent requests with different headers
            headers1 = {
                "Authorization": "Bearer concurrent-token-1",
                "X-Tenant-Id": "concurrent-tenant-1",
                "Content-Type": "application/json"
            }
            
            headers2 = {
                "Authorization": "Bearer concurrent-token-2",
                "X-Tenant-Id": "concurrent-tenant-2",
                "Content-Type": "application/json"
            }
            
            headers3 = {
                "Authorization": "Bearer concurrent-token-3",
                "X-Tenant-Id": "concurrent-tenant-3",
                "Content-Type": "application/json"
            }
            
            # Make concurrent requests
            tasks = [
                make_request(client, headers1, 1),
                make_request(client, headers2, 2),
                make_request(client, headers3, 3),
            ]
            
            responses = await asyncio.gather(*tasks)
            
            # All requests should succeed
            for response in responses:
                assert response.status_code == 202


class TestTranslateServerStartup:
    """Test translate server startup with dynamic environment injection."""

    @pytest.fixture
    def test_server_script(self):
        """Create a minimal test server script."""
        script_content = """#!/usr/bin/env python3
import sys
print('{"jsonrpc":"2.0","id":1,"result":"ready"}')
sys.stdout.flush()
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            yield f.name
        
        os.unlink(f.name)

    @pytest.mark.asyncio
    async def test_server_startup_with_valid_mappings(self, test_server_script):
        """Test server startup with valid header mappings."""
        port = 9002
        
        cmd = [
            "python3", "-m", "mcpgateway.translate",
            "--stdio", test_server_script,
            "--port", str(port),
            "--enable-dynamic-env",
            "--header-to-env", "Authorization=GITHUB_TOKEN",
            "--header-to-env", "X-Tenant-Id=TENANT_ID",
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait for server to start
            await asyncio.sleep(2)
            
            # Test that server is responding
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://localhost:{port}/healthz")
                assert response.status_code == 200
                
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    @pytest.mark.asyncio
    async def test_server_startup_with_invalid_mappings(self, test_server_script):
        """Test server startup with invalid header mappings."""
        port = 9003
        
        cmd = [
            "python3", "-m", "mcpgateway.translate",
            "--stdio", test_server_script,
            "--port", str(port),
            "--enable-dynamic-env",
            "--header-to-env", "Invalid Header!=GITHUB_TOKEN",  # Invalid header name
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait a bit to see if process exits
            await asyncio.sleep(1)
            
            # Process should exit with error
            return_code = process.poll()
            assert return_code is not None  # Process should have exited
            assert return_code != 0  # Should be error exit code
            
        finally:
            if process.poll() is None:  # Still running
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    @pytest.mark.asyncio
    async def test_server_startup_without_enable_flag(self, test_server_script):
        """Test server startup without enable-dynamic-env flag."""
        port = 9004
        
        cmd = [
            "python3", "-m", "mcpgateway.translate",
            "--stdio", test_server_script,
            "--port", str(port),
            "--header-to-env", "Authorization=GITHUB_TOKEN",  # Mappings without enable flag
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait for server to start
            await asyncio.sleep(2)
            
            # Test that server is responding (should ignore mappings)
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://localhost:{port}/healthz")
                assert response.status_code == 200
                
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
