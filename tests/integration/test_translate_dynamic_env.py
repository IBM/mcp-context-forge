# -*- coding: utf-8 -*-
"""Integration tests for dynamic environment variable injection.

Location: ./tests/integration/test_translate_dynamic_env.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Integration tests for dynamic environment variable injection in mcpgateway.translate.
"""

import asyncio
import pytest
import tempfile
import os
import json

# First-Party
from mcpgateway.translate import StdIOEndpoint, _PubSub
from mcpgateway.translate_header_utils import (
    extract_env_vars_from_headers,
    parse_header_mappings,
    HeaderMappingError,
)


class TestDynamicEnvironmentInjection:
    """Test dynamic environment variable injection integration."""

    @pytest.fixture
    def test_script(self):
        """Create a test script that prints environment variables."""
        script_content = """#!/usr/bin/env python3
import os
import json
import sys

# Print specified environment variables
env_vars = {}
for var in sys.argv[1:]:
    if var in os.environ:
        env_vars[var] = os.environ[var]

print(json.dumps(env_vars))
sys.stdout.flush()
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            try:
                yield f.name
            finally:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass

    @pytest.fixture
    def mcp_server_script(self):
        """Create a mock MCP server script that responds to JSON-RPC."""
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            try:
                yield f.name
            finally:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass

    @pytest.mark.asyncio
    async def test_header_to_env_integration(self, test_script):
        """Test full integration of header-to-environment mapping."""
        # Setup
        headers = {
            "Authorization": "Bearer github-token-123",
            "X-Tenant-Id": "acme-corp",
            "X-API-Key": "api-key-456",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "X-API-Key": "API_KEY",
        }

        # Extract environment variables from headers
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Verify extraction
        expected = {
            "GITHUB_TOKEN": "Bearer github-token-123",
            "TENANT_ID": "acme-corp",
            "API_KEY": "api-key-456",
        }
        assert env_vars == expected

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            # Send request to check environment variables
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID", "API_KEY"]\n')

            # Wait for response
            await asyncio.sleep(0.1)

            # Verify process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_case_insensitive_header_mapping(self, test_script):
        """Test case-insensitive header mapping integration."""
        headers = {
            "authorization": "Bearer github-token-123",  # lowercase
            "X-TENANT-ID": "acme-corp",  # uppercase
            "x-api-key": "api-key-456",  # mixed case
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",  # Proper case
            "X-Tenant-Id": "TENANT_ID",  # Proper case
            "X-Api-Key": "API_KEY",  # Proper case
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Verify case-insensitive matching worked
        expected = {
            "GITHUB_TOKEN": "Bearer github-token-123",
            "TENANT_ID": "acme-corp",
            "API_KEY": "api-key-456",
        }
        assert env_vars == expected

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID", "API_KEY"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_partial_header_mapping(self, test_script):
        """Test partial header mapping (some headers missing)."""
        headers = {
            "Authorization": "Bearer github-token-123",
            "X-Tenant-Id": "acme-corp",
            "Other-Header": "ignored-value",  # Not in mappings
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "X-API-Key": "API_KEY",  # Not in headers
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Verify only matching headers are included
        expected = {
            "GITHUB_TOKEN": "Bearer github-token-123",
            "TENANT_ID": "acme-corp",
        }
        assert env_vars == expected

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID", "API_KEY"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_mcp_server_environment_injection(self, mcp_server_script):
        """Test environment variable injection with MCP server script."""
        headers = {
            "Authorization": "Bearer github-token-123",
            "X-Tenant-Id": "acme-corp",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Test with MCP server script
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {mcp_server_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            # Send MCP initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0.0"}},
            }
            await endpoint.send(json.dumps(init_request) + "\n")

            # Wait for response
            await asyncio.sleep(0.1)

            # Send environment test request
            env_test_request = {"jsonrpc": "2.0", "id": 2, "method": "env_test", "params": {}}
            await endpoint.send(json.dumps(env_test_request) + "\n")

            # Wait for response
            await asyncio.sleep(0.1)

            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_environment_variable_override(self, test_script):
        """Test that additional environment variables override initial ones."""
        # Initial environment variables
        initial_env_vars = {
            "GITHUB_TOKEN": "initial-token",
            "BASE_VAR": "base-value",
        }

        # Headers that will override some values
        headers = {
            "Authorization": "Bearer override-token",
            "X-Tenant-Id": "override-tenant",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",  # This will override initial
            "X-Tenant-Id": "TENANT_ID",  # This is new
        }

        # Extract environment variables from headers
        header_env_vars = extract_env_vars_from_headers(headers, mappings)

        # Combine with initial (header vars should override)
        combined_env_vars = {**initial_env_vars, **header_env_vars}

        expected = {
            "GITHUB_TOKEN": "Bearer override-token",  # Overridden
            "BASE_VAR": "base-value",  # Preserved
            "TENANT_ID": "override-tenant",  # New
        }
        assert combined_env_vars == expected

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, combined_env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "BASE_VAR", "TENANT_ID"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_sanitization_integration(self, test_script):
        """Test that header value sanitization works in integration."""
        headers = {
            "Authorization": "Bearer\x00token\n123",  # Contains dangerous chars
            "X-Tenant-Id": "acme\x01corp",  # Contains control chars
            "Normal-Header": "normal-value",  # Normal value
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "Normal-Header": "NORMAL_VAR",
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Verify sanitization
        expected = {
            "GITHUB_TOKEN": "Bearertoken123",  # Dangerous chars removed
            "TENANT_ID": "acmecorp",  # Control chars removed
            "NORMAL_VAR": "normal-value",  # Normal value preserved
        }
        assert env_vars == expected

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID", "NORMAL_VAR"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_empty_headers_handling(self, test_script):
        """Test handling of empty headers."""
        headers = {}
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Should return empty dict
        assert env_vars == {}

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_empty_mappings_handling(self, test_script):
        """Test handling of empty mappings."""
        headers = {
            "Authorization": "Bearer github-token-123",
            "X-Tenant-Id": "acme-corp",
        }
        mappings = {}

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Should return empty dict
        assert env_vars == {}

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    def test_parse_header_mappings_integration(self):
        """Test parse_header_mappings function integration."""
        # Test valid mappings
        mappings_list = [
            "Authorization=GITHUB_TOKEN",
            "X-Tenant-Id=TENANT_ID",
            "X-API-Key=API_KEY",
        ]

        mappings = parse_header_mappings(mappings_list)

        expected = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "X-API-Key": "API_KEY",
        }
        assert mappings == expected

    def test_parse_header_mappings_with_spaces(self):
        """Test parse_header_mappings with spaces around equals."""
        mappings_list = [
            "Authorization = GITHUB_TOKEN",
            " X-Tenant-Id = TENANT_ID ",
            "Content-Type=CONTENT_TYPE",
        ]

        mappings = parse_header_mappings(mappings_list)

        expected = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "Content-Type": "CONTENT_TYPE",
        }
        assert mappings == expected

    def test_parse_header_mappings_validation(self):
        """Test parse_header_mappings validation."""
        # Test invalid header name
        with pytest.raises(HeaderMappingError, match="Invalid header name"):
            parse_header_mappings(["Invalid Header!=GITHUB_TOKEN"])

        # Test invalid environment variable name
        with pytest.raises(HeaderMappingError, match="Invalid environment variable name"):
            parse_header_mappings(["Authorization=123INVALID"])

        # Test duplicate header
        with pytest.raises(HeaderMappingError, match="Duplicate header mapping"):
            parse_header_mappings(
                [
                    "Authorization=GITHUB_TOKEN",
                    "Authorization=API_TOKEN",
                ]
            )

    @pytest.mark.asyncio
    async def test_large_header_values(self, test_script):
        """Test handling of large header values."""
        large_value = "x" * 5000  # 5KB value (will be truncated to 4KB)
        headers = {
            "Authorization": large_value,
            "X-Tenant-Id": "acme-corp",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        # Extract environment variables
        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Verify truncation
        assert len(env_vars["GITHUB_TOKEN"]) == 4096  # MAX_HEADER_VALUE_LENGTH
        assert env_vars["TENANT_ID"] == "acme-corp"

        # Test with StdIOEndpoint
        pubsub = _PubSub()
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN", "TENANT_ID"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self, mcp_server_script):
        """Test handling multiple concurrent requests with different headers."""
        # This test simulates what would happen in a real scenario
        # where multiple clients send requests with different headers

        # Setup for first request
        headers1 = {
            "Authorization": "Bearer token-user1",
            "X-Tenant-Id": "tenant-1",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        env_vars1 = extract_env_vars_from_headers(headers1, mappings)

        # Setup for second request
        headers2 = {
            "Authorization": "Bearer token-user2",
            "X-Tenant-Id": "tenant-2",
        }

        env_vars2 = extract_env_vars_from_headers(headers2, mappings)

        # Verify different environment variables
        assert env_vars1["GITHUB_TOKEN"] == "Bearer token-user1"
        assert env_vars1["TENANT_ID"] == "tenant-1"
        assert env_vars2["GITHUB_TOKEN"] == "Bearer token-user2"
        assert env_vars2["TENANT_ID"] == "tenant-2"

        # Test both with separate endpoints (simulating different processes)
        pubsub1 = _PubSub()
        endpoint1 = StdIOEndpoint(f"python3 {mcp_server_script}", pubsub1, env_vars1)

        pubsub2 = _PubSub()
        endpoint2 = StdIOEndpoint(f"python3 {mcp_server_script}", pubsub2, env_vars2)

        await endpoint1.start()
        await endpoint2.start()

        try:
            # Send requests to both endpoints
            request1 = {"jsonrpc": "2.0", "id": 1, "method": "env_test", "params": {}}
            await endpoint1.send(json.dumps(request1) + "\n")

            request2 = {"jsonrpc": "2.0", "id": 2, "method": "env_test", "params": {}}
            await endpoint2.send(json.dumps(request2) + "\n")

            await asyncio.sleep(0.1)

            assert endpoint1._proc is not None
            assert endpoint2._proc is not None

        finally:
            await endpoint1.stop()
            await endpoint2.stop()


class TestErrorHandlingIntegration:
    """Test error handling in integration scenarios."""

    @pytest.fixture
    def test_script(self):
        """Create a test script that prints environment variables."""
        script_content = """#!/usr/bin/env python3
import os
import json
import sys

# Print specified environment variables
env_vars = {}
for var in sys.argv[1:]:
    if var in os.environ:
        env_vars[var] = os.environ[var]

print(json.dumps(env_vars))
sys.stdout.flush()
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            try:
                yield f.name
            finally:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass

    @pytest.mark.asyncio
    async def test_invalid_command_handling(self):
        """Test handling of invalid commands."""
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token"}

        # Use nonexistent command
        endpoint = StdIOEndpoint("nonexistent-command-12345", pubsub, env_vars)

        with pytest.raises((OSError, FileNotFoundError)):
            await endpoint.start()

    @pytest.mark.asyncio
    async def test_header_mapping_error_propagation(self):
        """Test that header mapping errors are properly handled."""
        # Test invalid mapping format
        with pytest.raises(HeaderMappingError):
            parse_header_mappings(["InvalidFormat"])

        # Test invalid header name
        with pytest.raises(HeaderMappingError):
            parse_header_mappings(["Invalid Header!=GITHUB_TOKEN"])

        # Test invalid environment variable name
        with pytest.raises(HeaderMappingError):
            parse_header_mappings(["Authorization=123INVALID"])

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, test_script):
        """Test graceful degradation when environment injection fails."""
        pubsub = _PubSub()

        # Test with invalid environment variable names (should be caught during parsing)
        try:
            parse_header_mappings(["Authorization=123INVALID"])
            assert False, "Should have raised HeaderMappingError"
        except HeaderMappingError:
            pass  # Expected

        # Test normal operation without environment variables
        endpoint = StdIOEndpoint(f"python3 {test_script}", pubsub, {})
        await endpoint.start()

        try:
            await endpoint.send('["GITHUB_TOKEN"]\n')
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()
