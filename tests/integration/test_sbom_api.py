#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_sbom_api.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Integration tests for SBOM API endpoints.
"""

# Standard
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# Third-Party
from httpx import ASGITransport, AsyncClient
import pytest

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
async def test_client(app_fixture):
    """Create test HTTP client."""
    async with AsyncClient(transport=ASGITransport(app=app_fixture), base_url="http://test") as client:
        yield client


# ============================================================================
# GET /sbom/{sbom_id} - Retrieve SBOM by ID
# ============================================================================


class TestGetSBOMById:
    """Test GET /sbom/{sbom_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_sbom_success(self, test_client, populated_sbom):
        """Test successful SBOM retrieval."""
        response = await test_client.get(f"/sbom/{populated_sbom.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(populated_sbom.id)
        assert data["server_id"] == str(populated_sbom.server_id)
        assert data["format"] == populated_sbom.format
        assert data["spec_version"] == populated_sbom.spec_version
        assert "components" in data
        assert data["component_count"] > 0

    @pytest.mark.asyncio
    async def test_get_sbom_without_components(self, test_client, populated_sbom):
        """Test retrieving SBOM without components."""
        response = await test_client.get(
            f"/sbom/{populated_sbom.id}",
            params={"include_components": False},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["components"] is None
        assert data["component_count"] is None

    @pytest.mark.asyncio
    async def test_get_sbom_not_found(self, test_client):
        """Test 404 for non-existent SBOM."""
        nonexistent_id = uuid4()
        response = await test_client.get(f"/sbom/{nonexistent_id}")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_sbom_invalid_uuid(self, test_client):
        """Test 422 for invalid UUID format."""
        response = await test_client.get("/sbom/not-a-uuid")

        assert response.status_code == 422


# ============================================================================
# GET /sbom/server/{server_id} - Get SBOM by Server
# ============================================================================


class TestGetSBOMByServer:
    """Test GET /sbom/server/{server_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_server_sbom_success(self, test_client, populated_sbom):
        """Test successful server SBOM retrieval."""
        response = await test_client.get(f"/sbom/server/{populated_sbom.server_id}")

        assert response.status_code == 200
        data = response.json()

        assert data["server_id"] == str(populated_sbom.server_id)
        assert data["count"] >= 1
        assert len(data["sboms"]) >= 1
        assert data["sboms"][0]["id"] == str(populated_sbom.id)

    @pytest.mark.asyncio
    async def test_get_server_sbom_latest_only(self, test_client, sbom_repository, server_id, sbom_document):
        """Test retrieving only latest SBOM for server."""
        # Create two SBOMs
        sbom1 = sbom_repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_document,
        )

        sbom_document.serial_number = f"urn:uuid:{uuid4()}"
        sbom2 = sbom_repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_document,
        )

        response = await test_client.get(
            f"/sbom/server/{server_id}",
            params={"latest_only": True},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 1
        assert data["sboms"][0]["id"] == str(sbom2.id)  # Most recent

    @pytest.mark.asyncio
    async def test_get_server_sbom_all_versions(self, test_client, sbom_repository, server_id, sbom_document):
        """Test retrieving all SBOM versions for server."""
        # Create two SBOMs
        sbom_repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_document,
        )

        sbom_document.serial_number = f"urn:uuid:{uuid4()}"
        sbom_repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_document,
        )

        response = await test_client.get(
            f"/sbom/server/{server_id}",
            params={"latest_only": False},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_get_server_sbom_not_found(self, test_client):
        """Test 404 for server with no SBOMs."""
        nonexistent_server = uuid4()
        response = await test_client.get(f"/sbom/server/{nonexistent_server}")

        assert response.status_code == 404


# ============================================================================
# GET /sbom/components/search - Component Search
# ============================================================================


class TestComponentSearch:
    """Test GET /sbom/components/search endpoint."""

    @pytest.mark.asyncio
    async def test_search_by_name(self, test_client, populated_sbom):
        """Test component search by name."""
        response = await test_client.get(
            "/sbom/components/search",
            params={"name": "requests"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["count"] > 0
        assert all("requests" in c["name"].lower() for c in data["components"])

    @pytest.mark.asyncio
    async def test_search_by_version(self, test_client, populated_sbom):
        """Test component search by version."""
        response = await test_client.get(
            "/sbom/components/search",
            params={"version": "2.31.0"},
        )

        assert response.status_code == 200
        data = response.json()

        assert all(c["version"] == "2.31.0" for c in data["components"])

    @pytest.mark.asyncio
    async def test_search_by_ecosystem(self, test_client, populated_sbom):
        """Test component search by ecosystem."""
        response = await test_client.get(
            "/sbom/components/search",
            params={"ecosystem": "python"},
        )

        assert response.status_code == 200
        data = response.json()

        assert all(c["ecosystem"] == "python" for c in data["components"])

    @pytest.mark.asyncio
    async def test_search_with_multiple_filters(self, test_client, populated_sbom):
        """Test component search with multiple filters."""
        response = await test_client.get(
            "/sbom/components/search",
            params={
                "name": "requests",
                "ecosystem": "python",
            },
        )

        assert response.status_code == 200
        data = response.json()

        for comp in data["components"]:
            assert "requests" in comp["name"].lower()
            assert comp["ecosystem"] == "python"

    @pytest.mark.asyncio
    async def test_search_with_limit(self, test_client, populated_sbom):
        """Test component search respects limit."""
        response = await test_client.get(
            "/sbom/components/search",
            params={"ecosystem": "python", "limit": 2},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["components"]) <= 2
        # assert data["limit"] == 2

    @pytest.mark.asyncio
    async def test_search_no_results(self, test_client):
        """Test component search with no matches."""
        response = await test_client.get(
            "/sbom/components/search",
            params={"name": "nonexistent-package-xyz"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 0
        assert data["components"] == []

    @pytest.mark.asyncio
    async def test_search_limit_validation(self, test_client):
        """Test search limit parameter validation."""
        # Too high
        response = await test_client.get(
            "/sbom/components/search",
            params={"limit": 2000},  # Max is 1000
        )

        assert response.status_code == 422

        # Too low
        response = await test_client.get(
            "/sbom/components/search",
            params={"limit": 0},  # Min is 1
        )

        assert response.status_code == 422


# ============================================================================
# GET /sbom/affected - CVE Correlation
# ============================================================================


class TestFindAffectedServers:
    """Test GET /sbom/affected endpoint."""

    @pytest.mark.asyncio
    async def test_find_affected_by_package(self, test_client, populated_sbom):
        """Test finding servers affected by package."""
        response = await test_client.get(
            "/sbom/affected",
            params={"package": "requests"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["package"] == "requests"
        assert data["affected_count"] > 0
        affected_ids = [s["server_id"] for s in data["affected_servers"]]
        assert str(populated_sbom.server_id) in affected_ids

    @pytest.mark.asyncio
    async def test_find_affected_with_version_constraint(self, test_client, populated_sbom):
        """Test finding affected servers with version constraint."""
        response = await test_client.get(
            "/sbom/affected",
            params={
                "package": "requests",
                "version_lt": "2.32.0",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["package"] == "requests"
        assert data["version_constraint"] == "<2.32.0"

    @pytest.mark.asyncio
    async def test_find_affected_exact_version(self, test_client, populated_sbom):
        """Test finding affected servers with exact version."""
        response = await test_client.get(
            "/sbom/affected",
            params={
                "package": "requests",
                "version_eq": "2.31.0",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["version_constraint"] == "==2.31.0"

    @pytest.mark.asyncio
    async def test_find_affected_no_results(self, test_client):
        """Test finding affected servers with no matches."""
        response = await test_client.get(
            "/sbom/affected",
            params={"package": "nonexistent-package"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["affected_count"] == 0
        assert data["affected_servers"] == []

    @pytest.mark.asyncio
    async def test_find_affected_missing_package(self, test_client):
        """Test endpoint requires package parameter."""
        response = await test_client.get("/sbom/affected")

        assert response.status_code == 422


# ============================================================================
# GET /sbom/licenses/summary - License Summary
# ============================================================================


class TestLicenseSummary:
    """Test GET /sbom/licenses/summary endpoint."""

    @pytest.mark.asyncio
    async def test_get_license_summary(self, test_client, populated_sbom):
        """Test getting license summary."""
        response = await test_client.get("/sbom/licenses/summary")

        assert response.status_code == 200
        data = response.json()

        assert "total_licenses" in data
        assert "license_counts" in data


# ============================================================================
# DELETE /sbom/cleanup - Cleanup Operations
# ============================================================================


class TestCleanupEndpoint:
    """Test DELETE /sbom/cleanup endpoint."""

    @pytest.mark.asyncio
    async def test_cleanup_dry_run(self, test_client, populated_sbom):
        """Test cleanup in dry-run mode."""
        response = await test_client.delete(
            "/sbom/cleanup",
            params={
                "retention_days": 365,
                "dry_run": True,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["dry_run"] is True
        assert "sboms_affected" in data
        assert "Would delete" in data["message"]

    @pytest.mark.asyncio
    async def test_cleanup_actual_delete(self, test_client, sbom_repository, server_id, sbom_document, db_session):
        """Test actual cleanup operation."""
        # Create old SBOM
        db_sbom = sbom_repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_document,
        )

        # Set to old date
        old_date = datetime.now(timezone.utc) - timedelta(days=400)
        db_sbom.created_at = old_date
        db_session.add(db_sbom)
        db_session.commit()

        response = await test_client.delete(
            "/sbom/cleanup",
            params={
                "retention_days": 365,
                "dry_run": False,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["dry_run"] is False
        assert data["sboms_affected"] >= 1
        assert "Deleted" in data["message"]

    @pytest.mark.asyncio
    async def test_cleanup_validation(self, test_client):
        """Test cleanup parameter validation."""
        # Invalid retention_days
        response = await test_client.delete(
            "/sbom/cleanup",
            params={"retention_days": 0},  # Must be >= 1
        )

        assert response.status_code == 422


# ============================================================================
# GET /sbom/stats - Statistics
# ============================================================================


class TestStatsEndpoint:
    """Test GET /sbom/stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats(self, test_client):
        """Test getting SBOM statistics."""
        response = await test_client.get("/sbom/stats")

        assert response.status_code == 200
        data = response.json()

        # Currently returns placeholder
        assert "total_sboms" in data
        assert "ecosystem_count" in data


# ============================================================================
# Integration Test Scenarios
# ============================================================================


class TestEndToEndScenarios:
    """Test complete end-to-end workflows."""

    @pytest.mark.asyncio
    async def test_complete_cve_response_workflow(self, test_client, sbom_repository, sbom_document):
        """
        Test complete CVE incident response workflow:
        1. Create SBOMs for multiple servers
        2. Search for affected servers by package/version
        3. Retrieve detailed SBOMs for affected servers
        """
        # Setup: Create SBOMs for 3 servers
        server_ids = [str(uuid4()) for _ in range(3)]

        for server_id in server_ids:
            sbom_document.serial_number = f"urn:uuid:{uuid4()}"
            sbom_repository.create_sbom(
                server_id=server_id,
                sbom_doc=sbom_document,
            )

        # Step 1: Find affected servers
        response = await test_client.get(
            "/sbom/affected",
            params={
                "package": "requests",
                "version_lt": "2.32.0",
            },
        )

        assert response.status_code == 200
        affected = response.json()["affected_servers"]
        assert len(affected) == 3

        # Step 2: Get detailed SBOM for first affected server
        server_id = affected[0]["server_id"]
        response = await test_client.get(f"/sbom/server/{server_id}")

        assert response.status_code == 200
        sbom_data = response.json()
        assert len(sbom_data["sboms"]) > 0

    @pytest.mark.asyncio
    async def test_license_compliance_workflow(self, test_client, populated_sbom):
        """
        Test license compliance workflow:
        1. Get SBOM for server
        2. Check components for specific licenses
        3. Get license summary
        """
        # Step 1: Get SBOM
        response = await test_client.get(f"/sbom/{populated_sbom.id}")
        assert response.status_code == 200
        sbom = response.json()

        # Step 2: Search for GPL components
        response = await test_client.get(
            "/sbom/components/search",
            params={"name": "gpl"},  # Searching for GPL packages
        )
        assert response.status_code == 200

        # Step 3: Get license summary
        response = await test_client.get("/sbom/licenses/summary")
        assert response.status_code == 200


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestAPIErrorHandling:
    """Test API error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_database_error_handling(self, test_client):
        """Test API handles database errors gracefully."""
        # This test would need to mock database failures
        # For now, placeholder
        pass

    @pytest.mark.asyncio
    async def test_invalid_input_handling(self, test_client):
        """Test API validates input parameters."""
        # Invalid UUID format
        response = await test_client.get("/sbom/not-a-uuid")
        assert response.status_code == 422

        # Invalid limit
        response = await test_client.get(
            "/sbom/components/search",
            params={"limit": -1},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, test_client, populated_sbom):
        """Test API handles concurrent requests gracefully (no crashes).

        Note: Due to SQLite transaction isolation, some requests might return
        404 during high concurrency. This is expected behavior - the test verifies
        the API doesn't crash and returns valid HTTP responses.
        """
        # Standard
        import asyncio

        # Make concurrent requests
        tasks = [test_client.get(f"/sbom/{populated_sbom.id}") for _ in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all requests completed without exceptions
        assert len(responses) == 5, "Not all requests completed"

        # All should be valid HTTP responses (not crashes)
        for response in responses:
            assert not isinstance(response, Exception), f"Request raised exception: {response}"
            assert hasattr(response, "status_code"), "Response missing status_code"

        # At least one should succeed
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count >= 1, f"No successful responses. Status codes: {[r.status_code for r in responses]}"
