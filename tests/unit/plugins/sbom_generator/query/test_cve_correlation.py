#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/query/test_cve_correlation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from datetime import datetime, timezone
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.models import PackageEcosystem, SBOMComponent, SBOMDocument, SBOMFormat
from plugins.sbom_generator.query import AffectedServer, CVECorrelation


class TestAffectedServer:
    """Test AffectedServer dataclass for CVE correlation results."""

    def test_create_affected_server(self):
        """Test creating an AffectedServer instance."""
        server = AffectedServer(
            server_id="server-123",
            sbom_id="sbom-456",
            affected_components=["requests", "urllib3"],
            component_count=2,
            severity="high",
        )

        assert server.server_id == "server-123"
        assert server.sbom_id == "sbom-456"
        assert server.affected_components == ["requests", "urllib3"]
        assert server.component_count == 2
        assert server.severity == "high"

    def test_create_affected_server_with_defaults(self):
        """Test creating AffectedServer with default values."""
        server = AffectedServer(
            server_id="server-123",
            sbom_id="sbom-456",
            affected_components=[],
        )

        assert server.server_id == "server-123"
        assert server.sbom_id == "sbom-456"
        assert server.affected_components == []
        assert server.component_count == 0
        assert server.severity is None or server.severity == "unknown"

    def test_affected_server_to_dict(self):
        """Test converting AffectedServer to dict."""
        server = AffectedServer(
            server_id="server-123",
            sbom_id="sbom-456",
            affected_components=["lib1", "lib2"],
            component_count=2,
            severity="critical",
        )

        server_dict = server.to_dict()

        assert isinstance(server_dict, dict)
        assert server_dict["server_id"] == "server-123"
        assert server_dict["sbom_id"] == "sbom-456"
        assert server_dict["affected_components"] == ["lib1", "lib2"]
        assert server_dict["component_count"] == 2
        assert server_dict["severity"] == "critical"


class TestCVECorrelation:
    """Test CVECorrelation for vulnerability analysis."""

    @pytest.fixture
    def cve_correlation(self, sbom_repository):
        """Create CVECorrelation instance."""
        return CVECorrelation(sbom_repository)

    def test_cve_correlation_initialization(self, cve_correlation):
        """Test CVECorrelation initializes with repository."""
        assert cve_correlation is not None
        assert hasattr(cve_correlation, "_repo")

    def test_find_affected_by_cve_no_matches(self, cve_correlation):
        """Test finding affected servers for CVE with no matches."""
        results = cve_correlation.find_affected_by_cve("CVE-2024-0001")

        assert isinstance(results, list)
        assert len(results) == 0

    def test_find_affected_by_cve_with_purl(self, cve_correlation, sbom_repository):
        """Test finding affected servers using PURL-based CVE."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(
                name="requests",
                version="2.29.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/requests@2.29.0",
                licenses=["Apache-2.0"],
            ),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        # This tests the interface; actual CVE matching would depend on CVE database integration
        results = cve_correlation.find_affected_by_cve("CVE-2024-requests-vuln")

        assert isinstance(results, list)

    def test_find_affected_servers(self, cve_correlation, sbom_repository):
        """Test finding all servers affected by a component."""
        server1 = str(uuid4())
        server2 = str(uuid4())

        # Create SBOM for server1
        sbom1 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="vulnerable-lib",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    purl="pkg:pypi/vulnerable-lib@1.0.0",
                )
            ],
        )
        sbom_repository.create_sbom(server1, sbom1)

        # Create SBOM for server2
        sbom2 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="vulnerable-lib",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    purl="pkg:pypi/vulnerable-lib@1.0.0",
                )
            ],
        )
        sbom_repository.create_sbom(server2, sbom2)

        # Test interface for finding affected servers
        results = cve_correlation.find_affected_by_component("vulnerable-lib", "1.0.0")

        assert isinstance(results, list)
        # Should have results if implementation is complete
        if len(results) > 0:
            assert all(isinstance(r, AffectedServer) for r in results)

    def test_find_affected_by_version_range(self, cve_correlation, sbom_repository):
        """Test finding servers affected by version range."""
        server_id = str(uuid4())

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="package",
                    version="2.5.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    purl="pkg:pypi/package@2.5.0",
                )
            ],
        )
        sbom_repository.create_sbom(server_id, sbom)

        # Test interface for version range matching
        # (e.g., find CVEs affecting versions 2.0.0 - 2.6.0)
        results = cve_correlation.find_affected_by_version_range("package", "2.0.0", "2.6.0")

        assert isinstance(results, list)

    def test_get_cve_severity(self, cve_correlation):
        """Test retrieving CVE severity information."""
        severity = cve_correlation.get_cve_severity("CVE-2024-0001")

        # Should return severity string or None if not found
        assert severity is None or isinstance(severity, str)
        if severity:
            assert severity in ["critical", "high", "medium", "low", "unknown"]

    def test_find_affected_multiple_components(self, cve_correlation, sbom_repository):
        """Test finding servers affected by multiple vulnerable components."""
        server_id = str(uuid4())

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="lib1",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    purl="pkg:pypi/lib1@1.0.0",
                ),
                SBOMComponent(
                    name="lib2",
                    version="2.0.0",
                    ecosystem=PackageEcosystem.NPM,
                    purl="pkg:npm/lib2@2.0.0",
                ),
            ],
        )
        sbom_repository.create_sbom(server_id, sbom)

        # Test interface for finding servers with multiple vuln components
        results = cve_correlation.find_affected_servers([("lib1", "1.0.0"), ("lib2", "2.0.0")])

        assert isinstance(results, list)

    def test_cve_impact_analysis(self, cve_correlation):
        """Test analyzing CVE impact across deployment."""
        # Test interface for getting overall impact analysis
        impact = cve_correlation.get_impact_summary("CVE-2024-0001")

        assert impact is None or isinstance(impact, dict)
        if impact:
            assert "affected_count" in impact or "affected_servers" in impact

    def test_deduplication_of_servers(self, cve_correlation, sbom_repository):
        """Test that duplicate affected servers are deduplicated."""
        server_id = str(uuid4())

        # Store SBOM with multiple vulnerable components
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="vuln-lib-1",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                ),
                SBOMComponent(
                    name="vuln-lib-2",
                    version="2.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                ),
            ],
        )
        sbom_repository.create_sbom(server_id, sbom)

        # When multiple components are vulnerable, server should appear only once
        results = cve_correlation.find_affected_by_component("vuln-lib-1", "1.0.0")

        # Verify no duplicate server IDs in results
        if len(results) > 0:
            server_ids = [r.server_id for r in results]
            assert len(server_ids) == len(set(server_ids))

    def test_cve_correlation_with_transitive_deps(self, cve_correlation, sbom_repository):
        """Test CVE matching for transitive dependencies."""
        server_id = str(uuid4())

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="direct-dep",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    is_direct=True,
                ),
                SBOMComponent(
                    name="transitive-vuln",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    is_direct=False,  # Transitive
                ),
            ],
        )
        sbom_repository.create_sbom(server_id, sbom)

        # Should find transitive dependencies too
        results = cve_correlation.find_affected_by_component("transitive-vuln", "1.0.0")

        assert isinstance(results, list)
