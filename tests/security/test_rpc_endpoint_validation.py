# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_rpc_endpoint_validation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test RPC endpoint behavior to verify input validation happens before processing.
This test file demonstrates the actual vulnerability where malicious method names
reach the tool lookup logic instead of being rejected at the API layer.

Run with:
    pytest test_rpc_endpoint_validation.py -v -s
"""

# Standard
import logging
from unittest.mock import MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class TestRPCEndpointValidation:
    """Test the actual RPC endpoint to verify validation behavior.

    This test class verifies whether the /rpc endpoint properly validates
    method names BEFORE attempting to process them. The current issue is that
    invalid method names (including XSS payloads) reach the tool lookup logic
    and return errors like "Tool not found: <script>alert(1)</script>".
    """

    @pytest.fixture
    def client(self, app):
        """Create a test client for the FastAPI app with mocked security_logger."""
        # Mock security_logger to prevent database access
        mock_sec_logger = MagicMock()
        mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
        mock_sec_logger.log_security_event = MagicMock(return_value=None)
        with patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger):
            yield TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        """Create authorization headers for testing."""
        # You might need to adjust this based on your auth setup
        return {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

    def test_rpc_endpoint_with_malicious_methods(self, client, auth_headers):
        """Test that malicious method names are rejected before processing.

        This test sends actual HTTP requests to the RPC endpoint with various
        malicious payloads to verify they are rejected at the API layer, not
        during tool lookup.
        """
        print("\n" + "=" * 80)
        print("TESTING RPC ENDPOINT VALIDATION")
        print("=" * 80)

        malicious_payloads = [
            # XSS attempts
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            # SQL injection
            "'; DROP TABLE users; --",
            "admin' OR '1'='1",
            # Command injection
            "; ls -la",
            "| cat /etc/passwd",
            # Path traversal
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            # CRLF injection
            "method\r\nSet-Cookie: admin=true",
            # Null bytes
            "method\x00.php",
        ]

        results = []

        for payload in malicious_payloads:
            logger.debug(f"Testing malicious method: {payload[:50]}...")

            # Prepare the JSON-RPC request
            request_data = {"jsonrpc": "2.0", "method": payload, "params": {}, "id": 1}

            # Send the request
            response = client.post("/rpc", json=request_data, headers=auth_headers)

            # Analyze the response
            if response.status_code == 200:
                # Check if it's a JSON-RPC error response
                data = response.json()
                if "error" in data:
                    error_message = data["error"].get("message", "")
                    error_data = data["error"].get("data", "")

                    # Check if the payload appears in the error
                    if payload in error_message or payload in str(error_data):
                        results.append(f"❌ VULNERABILITY: Malicious input reached processing: {payload[:30]}...")
                        results.append(f"   Error was: {error_message[:100]}")
                        if error_data:
                            results.append(f"   Error data: {str(error_data)[:100]}")
                    elif "Tool not found" in error_message or "Tool not found" in str(error_data):
                        results.append(f"❌ VULNERABILITY: Method reached tool lookup: {payload[:30]}...")
                        results.append("   This means validation happened AFTER routing")
                    else:
                        results.append(f"✅ Method rejected with error: {payload[:30]}...")
                        results.append(f"   Error: {error_message[:100]}")
                else:
                    results.append(f"❌ CRITICAL: Method was processed successfully: {payload[:30]}...")

            elif response.status_code == 422:
                # This is what we want - validation error
                results.append(f"✅ Method rejected at validation layer (422): {payload[:30]}...")

            elif response.status_code == 400:
                # Bad request - also acceptable
                results.append(f"✅ Method rejected as bad request (400): {payload[:30]}...")

            else:
                # Unexpected status code
                results.append(f"⚠️  Unexpected status code {response.status_code} for: {payload[:30]}...")
                results.append(f"   Response: {response.text[:100]}...")

        # Print all results
        print("\nRESULTS:")
        print("-" * 80)
        for result in results:
            print(result)

        print("\n" + "=" * 80)
        print("EXPECTED BEHAVIOR:")
        print("- All malicious methods should return 422 (Unprocessable Entity)")
        print("- Or at least 400 (Bad Request)")
        print("- Error messages should NOT contain 'Tool not found: [payload]'")
        print("- The payload should NOT appear in error messages")
        print("=" * 80)

    def test_rpc_endpoint_with_valid_methods(self, client, auth_headers):
        """Test that valid method names are accepted."""
        print("\n" + "=" * 80)
        print("TESTING VALID RPC METHODS")
        print("=" * 80)

        valid_methods = [
            "tools_list",
            "resources_list",
            "servers_list",
            "gateway_tool_name",
            "time_server_get_time",
        ]

        results = []

        for method in valid_methods:
            request_data = {"jsonrpc": "2.0", "method": method, "params": {}, "id": 1}

            response = client.post("/rpc", json=request_data, headers=auth_headers)

            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    # Even valid methods might not have tools, but the error should be different
                    error_message = data["error"].get("message", "")
                    if "not found" in error_message.lower():
                        results.append(f"✅ Valid method processed (tool not found): {method}")
                    else:
                        results.append(f"✅ Valid method processed: {method}")
                else:
                    results.append(f"✅ Valid method executed successfully: {method}")
            else:
                results.append(f"❌ Valid method rejected with status {response.status_code}: {method}")

        # Print results
        for result in results:
            print(result)

    def test_rpc_direct_validation(self, client, auth_headers):
        """Test RPC validation by calling the endpoint directly."""
        print("\n" + "=" * 80)
        print("DIRECT RPC ENDPOINT TEST")
        print("=" * 80)

        # Test with the exact payload from the issue description
        request_data = {"jsonrpc": "2.0", "method": "<script>alert(1)</script>", "id": 1}

        response = client.post("/rpc", json=request_data, headers=auth_headers)

        print("\nTest payload: <script>alert(1)</script>")
        print(f"Status code: {response.status_code}")
        print(f"Response body: {response.text}")

        # According to the issue, this currently returns:
        # {
        #   "jsonrpc": "2.0",
        #   "error": {
        #     "code": -32000,
        #     "message": "Internal error",
        #     "data": "Tool not found: <script>alert(1)</script>"
        #   },
        #   "id": 1
        # }

        if response.status_code == 200:
            data = response.json()
            if "error" in data and "data" in data["error"]:
                error_data = data["error"]["data"]
                if "Tool not found: <script>alert(1)</script>" in str(error_data):
                    print("\n❌ VULNERABILITY CONFIRMED!")
                    print("The malicious method name reached the tool lookup logic.")
                    print("This should have been rejected at the validation layer.")
                    # Don't assert here - we want to see the issue
                else:
                    print("\n✅ Method was rejected properly")
        elif response.status_code in [400, 422]:
            print("\n✅ Method was rejected at validation layer (good!)")
        else:
            print(f"\n⚠️  Unexpected response status: {response.status_code}")

    def test_error_message_format(self, client, auth_headers):
        """Test the exact format of error messages for malicious input."""
        print("\n" + "=" * 80)
        print("ANALYZING ERROR MESSAGE FORMAT")
        print("=" * 80)

        test_payload = "<script>alert('XSS')</script>"

        request_data = {"jsonrpc": "2.0", "method": test_payload, "params": {}, "id": 1}

        response = client.post("/rpc", json=request_data, headers=auth_headers)

        print(f"\nPayload: {test_payload}")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print("\nFull Response:")
        print("-" * 40)

        try:
            json_response = response.json()
            # Standard
            import json

            print(json.dumps(json_response, indent=2))

            # Analyze the response
            if "error" in json_response:
                error = json_response["error"]
                print("\nError Analysis:")
                print(f"- Code: {error.get('code')}")
                print(f"- Message: {error.get('message')}")
                print(f"- Data: {error.get('data')}")

                # Check for the vulnerability signature
                error_str = str(error)
                if test_payload in error_str:
                    print("\n❌ VULNERABILITY CONFIRMED: User input reflected in error!")
                if "Tool not found" in error_str and test_payload in error_str:
                    print("❌ VULNERABILITY CONFIRMED: Malicious input reached tool lookup!")

        except Exception as e:
            print(f"Raw text response: {response.text}")
            print(f"Failed to parse JSON: {e}")


class TestRPCValidationBypass:
    """Test various techniques to bypass RPC validation."""

    @pytest.fixture
    def client(self, app):
        """Create a test client for the FastAPI app with mocked security_logger."""
        # Mock security_logger to prevent database access
        mock_sec_logger = MagicMock()
        mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
        mock_sec_logger.log_security_event = MagicMock(return_value=None)
        with patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger):
            yield TestClient(app)

    def test_bypass_techniques(self, client):
        """Test various bypass techniques."""
        print("\n" + "=" * 80)
        print("TESTING VALIDATION BYPASS TECHNIQUES")
        print("=" * 80)

        bypass_attempts = [
            # Unicode variations
            ("＜script＞alert('XSS')＜/script＞", "Full-width characters"),
            ("\\u003cscript\\u003ealert('XSS')\\u003c/script\\u003e", "Unicode escapes"),
            # URL encoding
            ("%3Cscript%3Ealert('XSS')%3C/script%3E", "URL encoded"),
            # Mixed valid/invalid
            ("tools_list<script>", "Valid prefix + XSS"),
            ("<script>tools_list", "XSS + valid suffix"),
            # Case variations
            ("TOOLS_LIST", "Uppercase valid method"),
            # Null byte injection
            ("tools_list\x00<script>", "Null byte separator"),
            # Double encoding
            ("%253Cscript%253E", "Double URL encoding"),
        ]

        headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

        for method, description in bypass_attempts:
            print(f"\nTesting {description}: {repr(method[:30])}...")

            request_data = {"jsonrpc": "2.0", "method": method, "params": {}, "id": 1}

            response = client.post("/rpc", json=request_data, headers=headers)

            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    print(f"Error: {data['error'].get('message', '')[:100]}")
                else:
                    print("Success response (potential bypass!)")
            else:
                print(f"Rejected with {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
