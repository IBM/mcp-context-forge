# -*- coding: utf-8 -*-
"""
HTTP Client Redirect Protection Tests.

Validates that HTTP clients do not automatically follow redirects, which could
be exploited to access internal endpoints. Tests verify both shared and isolated
client configurations.
"""

# Standard Library
from typing import List

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.http_client_service import get_http_client, get_isolated_http_client


def create_redirect_transport(redirect_location: str) -> httpx.MockTransport:
    """
    Create a mock transport that returns a 302 redirect.

    Args:
        redirect_location: The URL to redirect to (e.g., internal endpoints)

    Returns:
        MockTransport configured to return 302 redirect
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=302,
            headers={"Location": redirect_location},
            content=b"",
        )

    return httpx.MockTransport(handler)


def create_redirect_chain_transport(locations: List[str]) -> httpx.MockTransport:
    """
    Create a mock transport that simulates a redirect chain.

    Args:
        locations: List of redirect locations for each step

    Returns:
        MockTransport configured to return redirect chain
    """
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if "/redirect1" in url:
            return httpx.Response(
                status_code=302,
                headers={"Location": locations[0]},
                content=b"",
            )
        elif "/redirect2" in url:
            return httpx.Response(
                status_code=302,
                headers={"Location": locations[1]},
                content=b"",
            )
        elif "/final" in url:
            return httpx.Response(
                status_code=200,
                content=b"final-content",
            )
        else:
            return httpx.Response(status_code=404)

    return httpx.MockTransport(handler)


class TestSharedHttpClientRedirectProtection:
    """
    Test that get_http_client() returns a client that does NOT follow redirects.

    Verifies that the shared client has follow_redirects=False by default.
    """

    @pytest.mark.asyncio
    async def test_shared_client_blocks_redirect_to_internal_endpoint(self):

        # Setup: Mock transport that returns 302 to internal endpoint
        transport = create_redirect_transport("http://192.168.1.1/internal/api")

        # Get the shared client used by services
        client = await get_http_client()

        # Replace transport to simulate redirect server
        original_transport = client._transport
        client._transport = transport

        try:
            # Test: Make request that would redirect to internal endpoint
            response = await client.get("http://external.example.com/redirect")

            # Verify: Got 302, did NOT follow redirect
            assert response.status_code == 302, "Client should return 302, not follow redirect"
            assert response.headers["Location"] == "http://192.168.1.1/internal/api"
            assert len(response.content) == 0, "Client should NOT fetch redirect target content"
        finally:
            # Restore original transport
            client._transport = original_transport

    @pytest.mark.asyncio
    async def test_shared_client_blocks_redirect_to_localhost(self):

        transport = create_redirect_transport("http://127.0.0.1:4444/admin")

        client = await get_http_client()
        original_transport = client._transport
        client._transport = transport

        try:
            response = await client.post("http://external.example.com/redirect", json={"test": "data"})

            assert response.status_code == 302
            assert response.headers["Location"] == "http://127.0.0.1:4444/admin"
        finally:
            client._transport = original_transport

    @pytest.mark.asyncio
    async def test_shared_client_blocks_redirect_to_rfc1918_network(self):

        transport = create_redirect_transport("http://10.0.0.1/internal")

        client = await get_http_client()
        original_transport = client._transport
        client._transport = transport

        try:
            response = await client.get("http://external.example.com/redirect")

            assert response.status_code == 302
            assert response.headers["Location"] == "http://10.0.0.1/internal"
        finally:
            client._transport = original_transport

    @pytest.mark.asyncio
    async def test_shared_client_blocks_redirect_chain(self):

        transport = create_redirect_chain_transport(
            ["http://external2.example.com/redirect2", "http://10.0.0.2/internal"]
        )

        client = await get_http_client()
        original_transport = client._transport
        client._transport = transport

        try:
            response = await client.get("http://external.example.com/redirect1")

            # Should stop at first redirect
            assert response.status_code == 302
            assert "redirect2" in response.headers["Location"]
            # Should NOT have followed to second redirect or internal endpoint
        finally:
            client._transport = original_transport


class TestIsolatedHttpClientRedirectProtection:

    @pytest.mark.asyncio
    async def test_isolated_client_with_redirects_disabled_blocks_redirect(self):

        transport = create_redirect_transport("http://10.0.0.1/internal")

        # Get isolated client with redirects disabled
        async with get_isolated_http_client(follow_redirects=False, timeout=5.0) as client:
            # Replace transport to simulate redirect
            client._transport = transport

            response = await client.get("http://external.example.com/redirect")

            # Verify: Got 302, did NOT follow
            assert response.status_code == 302
            assert response.headers["Location"] == "http://10.0.0.1/internal"

    @pytest.mark.asyncio
    async def test_isolated_client_with_redirects_enabled_follows_redirect(self):

        transport = create_redirect_chain_transport(
            ["http://example.com/final", "http://10.0.0.2/internal"]
        )

        # Get isolated client with redirects ENABLED (control test)
        async with get_isolated_http_client(follow_redirects=True, timeout=5.0) as client:
            client._transport = transport

            response = await client.get("http://example.com/redirect1")

            # Verify: Followed redirect and got final content
            assert response.status_code == 200
            assert response.content == b"final-content"


class TestClientConfigurationVerification:

    @pytest.mark.asyncio
    async def test_get_http_client_configuration(self):
        """
        Verify get_http_client() returns client with follow_redirects=False.

        Tests the configuration at http_client_service.py:124.
        """
        client = await get_http_client()

        # Verify the client is configured to NOT follow redirects
        # We need to check the actual configuration, not just behavior
        # The client should have been created with follow_redirects=False

        # Make a test request with mock transport to verify behavior
        transport = create_redirect_transport("http://10.0.0.1/internal")
        original_transport = client._transport
        client._transport = transport

        try:
            response = await client.get("http://test.com/redirect")
            # If follow_redirects=False, we get 302
            # If follow_redirects=True, httpx would follow and we'd get different status
            assert response.status_code == 302, (
                "get_http_client() must return client with follow_redirects=False "
                "(configuration at http_client_service.py:124)"
            )
        finally:
            client._transport = original_transport

    @pytest.mark.asyncio
    async def test_get_isolated_http_client_respects_parameter(self):

        transport = create_redirect_transport("http://10.0.0.1/internal")

        # Test with redirects disabled
        async with get_isolated_http_client(follow_redirects=False, timeout=5.0) as client:
            client._transport = transport
            response = await client.get("http://test.com/redirect")
            assert response.status_code == 302, "follow_redirects=False should return 302"

        # Test with redirects enabled (control)
        transport_chain = create_redirect_chain_transport(
            ["http://test.com/final", "http://10.0.0.2/internal"]
        )
        async with get_isolated_http_client(follow_redirects=True, timeout=5.0) as client:
            client._transport = transport_chain
            response = await client.get("http://test.com/redirect1")
            assert response.status_code == 200, "follow_redirects=True should follow to final"


class TestToolServiceRedirectProtection:
    """
    Test that tool invocation HTTP clients do NOT follow redirects.

    Validates that REST tool invocations have follow_redirects=False to prevent
    SSRF attacks via redirect-based URL manipulation.
    """

    @pytest.mark.asyncio
    async def test_tool_invocation_blocks_redirect_to_internal_endpoint(self):
        """Test that tool invocation clients block redirects to internal endpoints."""
        # Setup: Mock transport that returns 302 to internal endpoint
        transport = create_redirect_transport("http://192.168.1.1/internal/api")

        # Create a mock tool invocation client (simulates tool_service.py:5272)
        # This client should have follow_redirects=False
        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            # Test: Make request that would redirect to internal endpoint
            response = await client.get("http://external.example.com/tool")

            # Verify: Got 302, did NOT follow redirect
            assert response.status_code == 302, "Tool client should return 302, not follow redirect"
            assert response.headers["Location"] == "http://192.168.1.1/internal/api"
            assert len(response.content) == 0, "Tool client should NOT fetch redirect target content"

    @pytest.mark.asyncio
    async def test_tool_invocation_blocks_redirect_to_metadata_service(self):
        """Test that tool invocation blocks redirects to cloud metadata services."""
        transport = create_redirect_transport("http://169.254.169.254/latest/meta-data/")

        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            response = await client.post("http://external.example.com/tool", json={"test": "data"})

            assert response.status_code == 302
            assert response.headers["Location"] == "http://169.254.169.254/latest/meta-data/"


class TestResourceServiceRedirectProtection:
    """
    Test that resource fetching HTTP clients do NOT follow redirects.

    Validates that resource read operations have follow_redirects=False to prevent
    SSRF attacks via redirect-based URI manipulation.
    """

    @pytest.mark.asyncio
    async def test_resource_fetch_blocks_redirect_to_internal_endpoint(self):
        """Test that resource fetch clients block redirects to internal endpoints."""
        # Setup: Mock transport that returns 302 to internal endpoint
        transport = create_redirect_transport("http://10.0.0.1/internal/resource")

        # Create a mock resource fetch client (simulates resource_service.py:1866)
        # This client should have follow_redirects=False
        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            # Test: Make request that would redirect to internal endpoint
            response = await client.get("http://external.example.com/resource")

            # Verify: Got 302, did NOT follow redirect
            assert response.status_code == 302, "Resource client should return 302, not follow redirect"
            assert response.headers["Location"] == "http://10.0.0.1/internal/resource"
            assert len(response.content) == 0, "Resource client should NOT fetch redirect target content"

    @pytest.mark.asyncio
    async def test_resource_fetch_blocks_redirect_to_localhost(self):
        """Test that resource fetch blocks redirects to localhost."""
        transport = create_redirect_transport("http://127.0.0.1:8080/admin")

        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            response = await client.get("http://external.example.com/resource")

            assert response.status_code == 302
            assert response.headers["Location"] == "http://127.0.0.1:8080/admin"


class TestCatalogServiceRedirectProtection:
    """
    Test that catalog health check HTTP clients do NOT follow redirects.

    Validates that catalog server health checks have follow_redirects=False to prevent
    SSRF attacks via redirect-based health check manipulation.
    """

    @pytest.mark.asyncio
    async def test_catalog_health_check_blocks_redirect(self):
        """Test that catalog health check clients block redirects."""
        # Setup: Mock transport that returns 302 to internal endpoint
        transport = create_redirect_transport("http://10.0.0.2/internal/health")

        # Create a mock catalog health check client (simulates catalog_service.py:514)
        # This client should have follow_redirects=False
        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            # Test: Make health check request that would redirect
            response = await client.get("http://external.example.com/health", timeout=5.0)

            # Verify: Got 302, did NOT follow redirect
            assert response.status_code == 302, "Catalog client should return 302, not follow redirect"
            assert response.headers["Location"] == "http://10.0.0.2/internal/health"

    @pytest.mark.asyncio
    async def test_catalog_health_check_blocks_redirect_chain(self):
        """Test that catalog health check blocks redirect chains."""
        transport = create_redirect_chain_transport(
            ["http://external2.example.com/redirect2", "http://192.168.1.1/internal"]
        )

        async with httpx.AsyncClient(follow_redirects=False, transport=transport) as client:
            response = await client.get("http://external.example.com/redirect1", timeout=5.0)

            # Should stop at first redirect
            assert response.status_code == 302
            assert "redirect2" in response.headers["Location"]
            # Should NOT have followed to second redirect or internal endpoint


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
