#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/query/test_component_search.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Test Suite
"""

# Standard
from datetime import datetime, timezone
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.models import PackageEcosystem, SBOMComponent, SBOMDocument, SBOMFormat
from plugins.sbom_generator.query import ComponentSearch, ComponentSearchResult


class TestComponentSearchResult:
    """Test ComponentSearchResult dataclass."""

    def test_create_result(self):
        """Test creating a ComponentSearchResult."""
        result = ComponentSearchResult(
            sbom_id="sbom-123",
            server_id="server-123",
            name="requests",
            version="2.31.0",
            ecosystem="python",
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0"],
            is_direct=True,
        )

        assert result.sbom_id == "sbom-123"
        assert result.server_id == "server-123"
        assert result.name == "requests"
        assert result.version == "2.31.0"
        assert result.ecosystem == "python"
        assert result.purl == "pkg:pypi/requests@2.31.0"
        assert result.licenses == ["Apache-2.0"]
        assert result.is_direct is True

    def test_result_with_defaults(self):
        """Test ComponentSearchResult with default values."""
        result = ComponentSearchResult(
            sbom_id="sbom-123",
            server_id="server-123",
            name="package",
            version="1.0.0",
            ecosystem="npm",
        )

        assert result.purl is None
        assert result.licenses == []
        assert result.is_direct is True

    def test_result_to_dict(self):
        """Test converting ComponentSearchResult to dict."""
        result = ComponentSearchResult(
            sbom_id="sbom-123",
            server_id="server-123",
            name="requests",
            version="2.31.0",
            ecosystem="python",
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0", "MIT"],
            is_direct=False,
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["sbom_id"] == "sbom-123"
        assert result_dict["server_id"] == "server-123"
        assert result_dict["name"] == "requests"
        assert result_dict["version"] == "2.31.0"
        assert result_dict["ecosystem"] == "python"
        assert result_dict["purl"] == "pkg:pypi/requests@2.31.0"
        assert result_dict["licenses"] == ["Apache-2.0", "MIT"]
        assert result_dict["is_direct"] is False


class TestComponentSearch:
    """Test ComponentSearch query interface."""

    @pytest.fixture
    def sbom_with_components(self, sbom_repository, sample_components):
        """Create and store an SBOM with components."""
        server_id = str(uuid4())
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=sample_components,
        )

        stored_sbom = sbom_repository.create_sbom(server_id, sbom)
        return stored_sbom, server_id

    @pytest.fixture
    def component_search(self, sbom_repository):
        """Create ComponentSearch instance."""
        return ComponentSearch(sbom_repository)

    def test_search_all_components(self, component_search, sbom_with_components):
        """Test searching for all components without filters."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search()

        assert len(results) > 0
        assert all(isinstance(r, ComponentSearchResult) for r in results)

    def test_search_by_name(self, component_search, sbom_with_components):
        """Test searching components by name."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(name="requests")

        assert len(results) > 0
        assert any("requests" in r.name.lower() for r in results)

    def test_search_by_name_partial_match(self, component_search, sbom_with_components):
        """Test partial name matching."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(name="cert")

        # "certifi" should match
        assert any("cert" in r.name.lower() for r in results)

    def test_search_by_ecosystem(self, component_search, sbom_with_components):
        """Test searching components by ecosystem."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(ecosystem="python")

        assert len(results) > 0
        assert all(r.ecosystem == "python" for r in results)

    def test_search_by_version(self, component_search, sbom_with_components):
        """Test searching components by version."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(version="2.31.0")

        # Should match requests 2.31.0
        assert any(r.version == "2.31.0" for r in results)

    def test_search_by_purl(self, component_search, sbom_with_components):
        """Test searching components by PURL."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(purl="pkg:pypi/requests@2.31.0")

        assert len(results) > 0
        assert results[0].purl == "pkg:pypi/requests@2.31.0"

    def test_search_combined_filters(self, component_search, sbom_with_components):
        """Test searching with multiple filters combined (AND logic)."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(name="requests", ecosystem="python", version="2.31.0")

        assert len(results) > 0
        assert any(r.name == "requests" and r.ecosystem == "python" and r.version == "2.31.0" for r in results)

    def test_search_no_results(self, component_search, sbom_with_components):
        """Test search returning no results."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(name="nonexistent-package-xyz")

        assert len(results) == 0

    def test_search_with_limit(self, component_search, sbom_with_components):
        """Test search respects limit parameter."""
        _sbom, _server_id = sbom_with_components
        results = component_search.search(limit=1)

        assert len(results) <= 1

    def test_get_by_sbom(self, component_search, sbom_with_components):
        """Test retrieving all components for specific SBOM."""
        sbom, server_id = sbom_with_components
        results = component_search.get_by_sbom(str(sbom.id))

        assert len(results) == 3  # sample_components has 3
        assert all(r.sbom_id == str(sbom.id) for r in results)
        assert all(r.server_id == server_id for r in results)

    def test_get_by_sbom_nonexistent(self, component_search):
        """Test retrieving components for non-existent SBOM."""
        results = component_search.get_by_sbom(str(uuid4()))

        assert len(results) == 0

    def test_get_by_server(self, component_search, sbom_with_components):
        """Test retrieving all components for specific server."""
        sbom, server_id = sbom_with_components
        results = component_search.get_by_server(server_id)

        assert len(results) == 3
        assert all(r.server_id == server_id for r in results)

    def test_get_by_server_latest_only(self, component_search, sbom_repository):
        """Test retrieving only latest SBOM components."""
        server_id = str(uuid4())

        # Store first SBOM
        sbom1 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON)],
        )
        sbom_repository.create_sbom(server_id, sbom1)

        # Store second SBOM (newer)
        sbom2 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(name="lib2", version="2.0", ecosystem=PackageEcosystem.PYTHON),
                SBOMComponent(name="lib3", version="3.0", ecosystem=PackageEcosystem.PYTHON),
            ],
        )
        sbom_repository.create_sbom(server_id, sbom2)

        component_search = ComponentSearch(sbom_repository)
        results = component_search.get_by_server(server_id, latest_only=True)

        # Should only return components from latest SBOM
        assert len(results) == 2
        assert all(r.name in ["lib2", "lib3"] for r in results)

    def test_get_by_server_all_sboms(self, component_search, sbom_repository):
        """Test retrieving components from all SBOMs for server."""
        server_id = str(uuid4())

        # Store first SBOM
        sbom1 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON)],
        )
        sbom_repository.create_sbom(server_id, sbom1)

        # Store second SBOM
        sbom2 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="lib2", version="2.0", ecosystem=PackageEcosystem.PYTHON)],
        )
        sbom_repository.create_sbom(server_id, sbom2)

        component_search = ComponentSearch(sbom_repository)
        results = component_search.get_by_server(server_id, latest_only=False)

        # Should return components from both SBOMs
        assert len(results) == 2
        assert any(r.name == "lib1" for r in results)
        assert any(r.name == "lib2" for r in results)

    def test_result_licenses_parsing(self, sbom_repository):
        """Test that JSON-encoded licenses are properly parsed."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(
                name="multi-license",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                licenses=["MIT", "Apache-2.0", "BSD-3-Clause"],
            )
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.SPDX,
            spec_version="2.3",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        component_search = ComponentSearch(sbom_repository)
        results = component_search.search(name="multi-license")

        assert len(results) == 1
        assert len(results[0].licenses) == 3
        assert "MIT" in results[0].licenses
        assert "Apache-2.0" in results[0].licenses

    def test_result_purl_optional(self, sbom_repository):
        """Test that PURL is optional in results."""
        server_id = str(uuid4())
        components = [SBOMComponent(name="lib-no-purl", version="1.0", ecosystem=PackageEcosystem.PYTHON, purl=None)]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        component_search = ComponentSearch(sbom_repository)
        results = component_search.search(name="lib-no-purl")

        assert len(results) == 1
        assert results[0].purl is None
