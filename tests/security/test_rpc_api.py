#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPC method validation test

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This script tests if alicious method names reach the tool lookup logic
instead of being rejected at the validation layer.

Usage:
    python test_rpc_vulnerability_demo.py
"""

# Standard
import json
import os
import sys

# Third-Party
import pytest

try:
    # Third-Party
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)


@pytest.mark.skip(reason="Disabled temporarily as this requires a live MCP Gateway instance")
def test_rpc_vulnerability():
    """Test the RPC endpoint with malicious method names."""

    # Configuration
    base_url = os.getenv("MCPGATEWAY_URL", "http://localhost:4444")
    bearer_token = os.getenv("MCPGATEWAY_BEARER_TOKEN")

    if not bearer_token:
        print("Please set MCPGATEWAY_BEARER_TOKEN environment variable")
        print("You can generate one with:")
        print("  export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}

    print("=" * 80)
    print("RPC METHOD VALIDATION VULNERABILITY TEST")
    print("=" * 80)
    print(f"Testing against: {base_url}/rpc")
    print()

    # Test cases
    test_cases = [
        {"name": "XSS in method name", "payload": {"jsonrpc": "2.0", "method": "<script>alert(1)</script>", "id": 1}},
        {"name": "SQL injection in method name", "payload": {"jsonrpc": "2.0", "method": "'; DROP TABLE users; --", "id": 2}},
        {"name": "Command injection in method name", "payload": {"jsonrpc": "2.0", "method": "; cat /etc/passwd", "id": 3}},
        {"name": "Path traversal in method name", "payload": {"jsonrpc": "2.0", "method": "../../../etc/passwd", "id": 4}},
        {"name": "Valid method name (control)", "payload": {"jsonrpc": "2.0", "method": "tools_list", "id": 5}},
    ]

    for test in test_cases:
        print(f"\nTest: {test['name']}")
        print(f"Method: {test['payload']['method']}")
        print("-" * 40)

        try:
            response = requests.post(f"{base_url}/rpc", json=test["payload"], headers=headers, timeout=5)

            print(f"Status Code: {response.status_code}")

            # Pretty print the response
            try:
                response_data = response.json()
                print(f"Response: {json.dumps(response_data, indent=2)}")

                # Check for the vulnerability signature
                if response.status_code == 200 and "error" in response_data:
                    error_data = response_data["error"].get("data", "")
                    error_message = response_data["error"].get("message", "")

                    # The vulnerability: malicious input appears in "Tool not found" error
                    if "Tool not found:" in str(error_data) and test["payload"]["method"] in str(error_data):
                        print("\n❌ VULNERABILITY DETECTED!")
                        print("   The malicious method name reached the tool lookup logic.")
                        print("   This indicates validation is happening AFTER processing.")
                    elif test["payload"]["method"] in str(error_data) or test["payload"]["method"] in error_message:
                        print("\n❌ SECURITY ISSUE: User input reflected in error message!")
                    else:
                        print("\n✅ Method appears to be properly rejected")

                elif response.status_code in [400, 422]:
                    print("\n✅ Method rejected at validation layer (good!)")
                elif response.status_code == 200 and "result" in response_data:
                    if test["name"] == "Valid method name (control)":
                        print("\n✅ Valid method processed successfully")
                    else:
                        print("\n❌ CRITICAL: Malicious method was executed!")

            except ValueError:
                print(f"Raw Response: {response.text[:200]}...")

        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("\nVulnerability Indicators:")
    print("- Error message contains 'Tool not found: <malicious-input>'")
    print("- HTTP 200 status with error instead of 422/400")
    print("- User input reflected in error messages")
    print("\nExpected Secure Behavior:")
    print("- HTTP 422 or 400 for invalid method formats")
    print("- Generic error message without user input")
    print("- Validation before any processing/lookup")
    print("=" * 80)


if __name__ == "__main__":
    test_rpc_vulnerability()
