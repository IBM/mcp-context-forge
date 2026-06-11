# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_conditional_requests.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Integration tests for RFC 6585 Phase 2 conditional request validation.

Tests the full HTTP request/response flow with database interaction,
ensuring the conditional request middleware works correctly with real
server, gateway, tool, resource, and prompt endpoints.

Examples:
    >>> pytest tests/integration/test_conditional_requests.py -v  # doctest: +SKIP
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestConditionalRequestsIntegration:
    """Integration tests for conditional request validation."""

    @pytest.fixture(autouse=True)
    def enable_conditional_requests(self, monkeypatch):
        """Enable conditional requests for integration tests."""
        monkeypatch.setenv("CONDITIONAL_REQUESTS_ENABLED", "true")
        monkeypatch.setenv("CONDITIONAL_REQUESTS_REQUIRED_METHODS", "PUT,PATCH,DELETE")

    def test_server_update_without_if_match_returns_428(self, client_with_auth, test_server):
        """Test that updating server without If-Match returns 428."""
        # Try to update without If-Match header
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
        )

        assert response.status_code == 428
        data = response.json()
        assert data["error"] == "Precondition Required"
        assert "If-Match" in data["required_headers"]

    def test_server_update_with_valid_etag_succeeds(self, client_with_auth, test_server):
        """Test that updating server with valid ETag succeeds."""
        # Get current server to obtain ETag
        get_response = client_with_auth.get(f"/servers/{test_server['id']}")
        assert get_response.status_code == 200
        current_version = get_response.json()["version"]

        # Generate ETag
        from mcpgateway.utils.etag import generate_etag

        etag = generate_etag(test_server["id"], current_version)

        # Update with valid ETag
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Server"

    def test_server_update_with_stale_etag_returns_412(self, client_with_auth, test_server):
        """Test that updating server with stale ETag returns 412."""
        # Generate stale ETag (wrong version)
        from mcpgateway.utils.etag import generate_etag

        stale_etag = generate_etag(test_server["id"], 999)

        # Try to update with stale ETag
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": stale_etag},
        )

        assert response.status_code == 412
        data = response.json()
        assert data["error"] == "Precondition Failed"
        assert "current_etag" in data

    def test_server_delete_requires_if_match(self, client_with_auth, test_server):
        """Test that deleting server requires If-Match header."""
        # Try to delete without If-Match
        response = client_with_auth.delete(f"/servers/{test_server['id']}")

        assert response.status_code == 428
        data = response.json()
        assert data["error"] == "Precondition Required"

    def test_gateway_update_with_conditional_request(self, client_with_auth, test_gateway):
        """Test that gateway updates work with conditional requests."""
        # Get current gateway
        get_response = client_with_auth.get(f"/gateways/{test_gateway['id']}")
        assert get_response.status_code == 200
        current_version = get_response.json()["version"]

        # Generate ETag
        from mcpgateway.utils.etag import generate_etag

        etag = generate_etag(test_gateway["id"], current_version)

        # Update with valid ETag
        response = client_with_auth.put(
            f"/gateways/{test_gateway['id']}",
            json={"name": "Updated Gateway", "endpoint_url": test_gateway["endpoint_url"]},
            headers={"If-Match": etag},
        )

        assert response.status_code == 200

    def test_tool_update_with_conditional_request(self, client_with_auth, test_tool):
        """Test that tool updates work with conditional requests."""
        # Get current tool
        get_response = client_with_auth.get(f"/tools/{test_tool['id']}")
        assert get_response.status_code == 200
        current_version = get_response.json()["version"]

        # Generate ETag
        from mcpgateway.utils.etag import generate_etag

        etag = generate_etag(test_tool["id"], current_version)

        # Update with valid ETag
        response = client_with_auth.put(
            f"/tools/{test_tool['id']}",
            json={
                "name": "Updated Tool",
                "description": "Updated description",
                "input_schema": test_tool["input_schema"],
            },
            headers={"If-Match": etag},
        )

        assert response.status_code == 200

    def test_exempt_paths_bypass_validation(self, client_with_auth):
        """Test that exempt paths bypass conditional request validation."""
        # Health check should not require If-Match
        response = client_with_auth.get("/health")
        assert response.status_code == 200

    def test_get_requests_do_not_require_if_match(self, client_with_auth, test_server):
        """Test that GET requests do not require If-Match header."""
        response = client_with_auth.get(f"/servers/{test_server['id']}")
        assert response.status_code == 200

    def test_post_requests_do_not_require_if_match(self, client_with_auth):
        """Test that POST (create) requests do not require If-Match header."""
        response = client_with_auth.post(
            "/servers",
            json={
                "name": "New Server",
                "endpoint_url": "http://localhost:9999",
                "transport": "sse",
            },
        )

        # Should succeed (201) or fail with validation error, but not 428
        assert response.status_code != 428

    def test_wildcard_etag_matches_any_version(self, client_with_auth, test_server):
        """Test that wildcard ETag (*) matches any version."""
        # Update with wildcard ETag
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": "*"},
        )

        # Should succeed regardless of version
        assert response.status_code == 200

    def test_multiple_etags_one_matches(self, client_with_auth, test_server):
        """Test that request succeeds if any ETag in list matches."""
        # Get current version
        get_response = client_with_auth.get(f"/servers/{test_server['id']}")
        current_version = get_response.json()["version"]

        from mcpgateway.utils.etag import generate_etag

        # Create list with stale and valid ETags
        stale_etag = generate_etag(test_server["id"], 999)
        valid_etag = generate_etag(test_server["id"], current_version)
        another_stale = generate_etag(test_server["id"], 888)

        # Update with multiple ETags (one valid)
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": f"{stale_etag}, {valid_etag}, {another_stale}"},
        )

        assert response.status_code == 200

    def test_concurrent_modification_detection(self, client_with_auth, test_server):
        """Test that concurrent modifications are detected."""
        # Get current version
        get_response = client_with_auth.get(f"/servers/{test_server['id']}")
        initial_version = get_response.json()["version"]

        from mcpgateway.utils.etag import generate_etag

        etag = generate_etag(test_server["id"], initial_version)

        # First client updates successfully
        response1 = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "First Update", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": etag},
        )
        assert response1.status_code == 200

        # Second client tries to update with same (now stale) ETag
        response2 = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Second Update", "endpoint_url": test_server["endpoint_url"]},
            headers={"If-Match": etag},  # Stale ETag
        )

        # Should fail with 412
        assert response2.status_code == 412
        data = response2.json()
        assert data["error"] == "Precondition Failed"
        assert "current_etag" in data

        # Verify current ETag reflects first update (version incremented)
        new_version = initial_version + 1
        expected_etag = generate_etag(test_server["id"], new_version)
        assert data["current_etag"] == expected_etag


@pytest.mark.integration
class TestConditionalRequestsDisabled:
    """Test behavior when conditional requests are disabled."""

    @pytest.fixture(autouse=True)
    def disable_conditional_requests(self, monkeypatch):
        """Disable conditional requests for these tests."""
        monkeypatch.setenv("CONDITIONAL_REQUESTS_ENABLED", "false")

    def test_update_without_if_match_succeeds_when_disabled(self, client_with_auth, test_server):
        """Test that updates work without If-Match when feature is disabled."""
        response = client_with_auth.put(
            f"/servers/{test_server['id']}",
            json={"name": "Updated Server", "endpoint_url": test_server["endpoint_url"]},
        )

        # Should succeed without If-Match header
        assert response.status_code == 200

    def test_delete_without_if_match_succeeds_when_disabled(self, client_with_auth, test_server):
        """Test that deletes work without If-Match when feature is disabled."""
        response = client_with_auth.delete(f"/servers/{test_server['id']}")

        # Should succeed without If-Match header
        assert response.status_code == 200
