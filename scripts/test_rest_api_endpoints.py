#!/usr/bin/env python3
"""
Test script for REST API gateway endpoints.

This script tests the new RESTful endpoints for gateway CRUD operations:
- POST /admin/gateways (create with JSON)
- PUT /admin/gateways/{id} (update with JSON)
- DELETE /admin/gateways/{id} (delete)

Usage:
    uv run scripts/test_rest_api_endpoints.py
"""

import asyncio
import os
import sys
from typing import Dict, Optional, Tuple

import httpx


class GatewayAPITester:
    """Test the gateway REST API endpoints."""

    def __init__(self, base_url: str = "http://localhost:8000", token: Optional[str] = None):
        """Initialize the tester.

        Args:
            base_url: Base URL of the gateway API
            token: JWT token for authentication (if None, checks $TOKEN env var, then creates one)
        """
        self.base_url = base_url.rstrip("/")
        # Check environment variable if token not provided
        self.token = token or os.environ.get("TOKEN")
        self.created_gateway_id: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _create_test_token(self) -> str:
        """Create a test JWT token using the utility."""
        try:
            # Try to import and use the token creation utility
            from mcpgateway.utils.create_jwt_token import create_jwt_token

            # Create token with admin user data
            token = await create_jwt_token(
                data={"sub": "test-admin@example.com"},
                expires_in_minutes=60,
                user_data={
                    "email": "test-admin@example.com",
                    "full_name": "Test Admin",
                    "is_admin": True,
                    "auth_provider": "test"
                },
                teams=None  # Admin bypass
            )
            print("✅ Created test JWT token")
            return token
        except Exception as e:
            print(f"❌ Failed to create test token: {e}")
            print("Please set a valid JWT token manually or ensure the server is configured correctly")
            sys.exit(1)

    async def test_create_gateway_json(self) -> bool:
        """Test creating a gateway with JSON payload."""
        print("\n" + "="*60)
        print("TEST 1: Create Gateway with JSON (POST /admin/gateways)")
        print("="*60)

        payload = {
            "name": "test-rest-gateway",
            "url": "http://httpbin.org/delay/0",  # Use a real endpoint for testing
            "transport": "SSE",
            "description": "Test gateway created via REST API",
            "tags": ["test", "rest-api"],
            "skip_initialization": True  # Skip validation for testing
        }

        print(f"\n📤 Sending POST request to {self.base_url}/admin/gateways")
        print(f"📦 Payload: {payload}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/admin/gateways",
                    json=payload,
                    headers=self._get_headers(),
                    timeout=10.0
                )

                print(f"\n📥 Response Status: {response.status_code}")
                print(f"📥 Response Body: {response.text}")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        print("✅ Gateway created successfully!")
                        # Try to extract gateway ID from response
                        if "gateway_id" in data:
                            self.created_gateway_id = data["gateway_id"]
                            print(f"   Gateway ID: {self.created_gateway_id}")
                        return True
                    else:
                        print(f"❌ Creation failed: {data.get('message')}")
                        return False
                else:
                    print(f"❌ Request failed with status {response.status_code}")
                    return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    async def test_update_gateway_json(self, gateway_id: str) -> bool:
        """Test updating a gateway with JSON payload."""
        print("\n" + "="*60)
        print(f"TEST 2: Update Gateway with JSON (PUT /admin/gateways/{gateway_id})")
        print("="*60)

        payload = {
            "name": "test-rest-gateway-updated",
            "description": "Updated via REST API PUT endpoint",
            "tags": ["test", "rest-api", "updated"]
        }

        print(f"\n📤 Sending PUT request to {self.base_url}/admin/gateways/{gateway_id}")
        print(f"📦 Payload: {payload}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.base_url}/admin/gateways/{gateway_id}",
                    json=payload,
                    headers=self._get_headers(),
                    timeout=10.0
                )

                print(f"\n📥 Response Status: {response.status_code}")
                print(f"📥 Response Body: {response.text}")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        print("✅ Gateway updated successfully!")
                        return True
                    else:
                        print(f"❌ Update failed: {data.get('message')}")
                        return False
                else:
                    print(f"❌ Request failed with status {response.status_code}")
                    return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    async def test_delete_gateway(self, gateway_id: str) -> bool:
        """Test deleting a gateway."""
        print("\n" + "="*60)
        print(f"TEST 3: Delete Gateway (DELETE /admin/gateways/{gateway_id})")
        print("="*60)

        print(f"\n📤 Sending DELETE request to {self.base_url}/admin/gateways/{gateway_id}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.base_url}/admin/gateways/{gateway_id}",
                    headers=self._get_headers(),
                    timeout=10.0
                )

                print(f"\n📥 Response Status: {response.status_code}")
                print(f"📥 Response Body: {response.text}")

                if response.status_code == 204:
                    print("✅ Gateway deleted successfully (204 No Content)!")
                    return True
                elif response.status_code == 200:
                    # Legacy behavior - still accept but warn
                    data = response.json()
                    if data.get("success"):
                        print("⚠️  Gateway deleted (200 OK - should return 204 No Content)")
                        return True
                    else:
                        print(f"❌ Deletion failed: {data.get('message')}")
                        return False
                else:
                    print(f"❌ Request failed with status {response.status_code}")
                    return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    async def test_form_data_acceptance(self) -> bool:
        """Test that the endpoint accepts both JSON and form-data."""
        print("\n" + "="*60)
        print("TEST 4: Verify Form-Data Acceptance")
        print("="*60)

        # Test that form data to REST endpoint is accepted (backward compatibility)
        form_data = {
            "name": "test-form-gateway",
            "url": "http://httpbin.org/delay/0",
            "transport": "SSE",
            "description": "Test gateway created via form data",
            "skip_initialization": "true"
        }

        print(f"\n📤 Sending form data to endpoint (should succeed)")
        print(f"📦 Form Data: {form_data}")

        try:
            async with httpx.AsyncClient() as client:
                headers: Dict[str, str] = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                response = await client.post(
                    f"{self.base_url}/admin/gateways",
                    data=form_data,
                    headers=headers,
                    timeout=10.0
                )

                print(f"\n📥 Response Status: {response.status_code}")
                print(f"📥 Response Body: {response.text}")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        print("✅ Form data accepted successfully (backward compatibility maintained)")
                        # Clean up the created gateway if we got an ID
                        if "gateway_id" in data:
                            gateway_id = data["gateway_id"]
                            await client.delete(
                                f"{self.base_url}/admin/gateways/{gateway_id}",
                                headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
                                timeout=10.0
                            )
                        return True
                    else:
                        print(f"❌ Form data rejected: {data.get('message')}")
                        return False
                else:
                    print(f"❌ Unexpected status code: {response.status_code}")
                    return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    async def run_all_tests(self) -> bool:
        """Run all tests in sequence."""
        print("\n" + "🚀 " + "="*58)
        print("🚀 REST API Gateway Endpoints Test Suite")
        print("🚀 " + "="*58)
        print(f"\n🌐 Base URL: {self.base_url}")

        # Create token if not provided
        if not self.token:
            print("\n🔑 No token provided (not in --token or $TOKEN env var), creating test token...")
            self.token = await self._create_test_token()
        else:
            # Determine source: if TOKEN env var exists, it came from there; otherwise from command line
            token_source = "TOKEN environment variable" if os.environ.get("TOKEN") else "command line"
            print(f"\n🔑 Using token from {token_source}")

        results: list[Tuple[str, bool]] = []

        # Test 1: Create gateway with JSON
        result1 = await self.test_create_gateway_json()
        results.append(("Create Gateway (JSON)", result1))

        if result1 and self.created_gateway_id:
            # Test 2: Update gateway with JSON
            result2 = await self.test_update_gateway_json(self.created_gateway_id)
            results.append(("Update Gateway (JSON)", result2))

            # Test 3: Delete gateway
            result3 = await self.test_delete_gateway(self.created_gateway_id)
            results.append(("Delete Gateway", result3))
        else:
            print("\n⚠️  Skipping update and delete tests (no gateway ID)")
            results.append(("Update Gateway (JSON)", False))
            results.append(("Delete Gateway", False))

        # Test 4: Form-data acceptance
        result4 = await self.test_form_data_acceptance()
        results.append(("Form-Data Acceptance", result4))

        # Print summary
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)

        for test_name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status} - {test_name}")

        total_passed = sum(1 for _, passed in results if passed)
        total_tests = len(results)

        print(f"\n📈 Results: {total_passed}/{total_tests} tests passed")

        if total_passed == total_tests:
            print("\n🎉 All tests passed!")
            return True
        else:
            print(f"\n⚠️  {total_tests - total_passed} test(s) failed")
            return False


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Test REST API gateway endpoints")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the gateway API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--token",
        help="JWT token for authentication (if not provided, checks $TOKEN env var, then creates one)"
    )

    args = parser.parse_args()

    tester = GatewayAPITester(base_url=args.url, token=args.token)
    success = await tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
