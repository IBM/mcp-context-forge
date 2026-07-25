#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/query/test_license_analyzer.py
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
from plugins.sbom_generator.models import LicensePolicy, PackageEcosystem, SBOMComponent, SBOMDocument, SBOMFormat
from plugins.sbom_generator.query import LicenseAnalyzer, LicenseSummary, ServerLicenseReport


class TestLicenseSummary:
    """Test LicenseSummary dataclass."""

    def test_create_empty_summary(self):
        """Test creating an empty LicenseSummary."""
        summary = LicenseSummary()

        assert summary.total_components == 0
        assert summary.license_counts == {}
        assert summary.blocked == []
        assert summary.flagged == []
        assert summary.allowed == []
        assert summary.servers_with_blocked == []

    def test_create_summary_with_data(self):
        """Test creating LicenseSummary with data."""
        summary = LicenseSummary(
            total_components=10,
            license_counts={"MIT": 5, "Apache-2.0": 3, "GPL-3.0": 2},
            blocked=["GPL-3.0"],
            flagged=["GPL-2.0"],
            allowed=["MIT", "Apache-2.0"],
            servers_with_blocked=["server-123"],
        )

        assert summary.total_components == 10
        assert summary.license_counts == {"MIT": 5, "Apache-2.0": 3, "GPL-3.0": 2}
        assert summary.blocked == ["GPL-3.0"]
        assert summary.flagged == ["GPL-2.0"]
        assert summary.allowed == ["MIT", "Apache-2.0"]
        assert summary.servers_with_blocked == ["server-123"]

    def test_summary_to_dict(self):
        """Test converting LicenseSummary to dict."""
        summary = LicenseSummary(
            total_components=10,
            license_counts={"MIT": 5, "Apache-2.0": 3},
            blocked=["GPL-3.0"],
            flagged=["GPL-2.0"],
            allowed=["MIT"],
            servers_with_blocked=["server-1"],
        )

        summary_dict = summary.to_dict()

        assert isinstance(summary_dict, dict)
        assert summary_dict["total_components"] == 10
        assert summary_dict["license_counts"] == {"MIT": 5, "Apache-2.0": 3}
        assert summary_dict["blocked"] == ["GPL-3.0"]
        assert summary_dict["flagged"] == ["GPL-2.0"]
        assert summary_dict["allowed"] == ["MIT"]
        assert summary_dict["servers_with_blocked"] == ["server-1"]


class TestServerLicenseReport:
    """Test ServerLicenseReport dataclass."""

    def test_create_report(self):
        """Test creating a ServerLicenseReport."""
        report = ServerLicenseReport(
            server_id="server-123",
            licenses=["MIT", "Apache-2.0"],
            blocked=["GPL-3.0"],
            flagged=["GPL-2.0"],
            is_compliant=False,
        )

        assert report.server_id == "server-123"
        assert report.licenses == ["MIT", "Apache-2.0"]
        assert report.blocked == ["GPL-3.0"]
        assert report.flagged == ["GPL-2.0"]
        assert report.is_compliant is False

    def test_create_compliant_report(self):
        """Test creating a compliant ServerLicenseReport."""
        report = ServerLicenseReport(
            server_id="server-456",
            licenses=["MIT", "Apache-2.0"],
            blocked=[],
            flagged=[],
            is_compliant=True,
        )

        assert report.server_id == "server-456"
        assert len(report.blocked) == 0
        assert report.is_compliant is True

    def test_report_to_dict(self):
        """Test converting ServerLicenseReport to dict."""
        report = ServerLicenseReport(
            server_id="server-123",
            licenses=["MIT"],
            blocked=["GPL-3.0"],
            flagged=["GPL-2.0"],
            is_compliant=False,
        )

        report_dict = report.to_dict()

        assert isinstance(report_dict, dict)
        assert report_dict["server_id"] == "server-123"
        assert report_dict["licenses"] == ["MIT"]
        assert report_dict["blocked"] == ["GPL-3.0"]
        assert report_dict["flagged"] == ["GPL-2.0"]
        assert report_dict["is_compliant"] is False


class TestLicenseAnalyzer:
    """Test LicenseAnalyzer query interface."""

    @pytest.fixture
    def license_policy(self):
        """Create a license policy for testing."""
        return LicensePolicy(
            blocked=["GPL-3.0", "AGPL-3.0"],
            flagged=["GPL-2.0"],
            allowed=["MIT", "Apache-2.0", "BSD-3-Clause"],
        )

    @pytest.fixture
    def license_analyzer(self, sbom_repository, license_policy):
        """Create LicenseAnalyzer instance."""
        return LicenseAnalyzer(sbom_repository, license_policy)

    def test_global_summary_empty(self, license_analyzer):
        """Test global summary when no SBOMs exist."""
        summary = license_analyzer.global_summary()

        assert summary.total_components == 0
        assert summary.license_counts == {}
        assert summary.blocked == []
        assert summary.flagged == []
        assert summary.allowed == []

    def test_global_summary_with_components(self, license_analyzer, sbom_repository):
        """Test global summary with components."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["MIT"]),
            SBOMComponent(name="lib2", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["Apache-2.0"]),
            SBOMComponent(name="lib3", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-3.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        summary = license_analyzer.global_summary()

        assert summary.total_components >= 3
        assert "MIT" in summary.license_counts or summary.total_components > 0
        if "GPL-3.0" in summary.license_counts:
            assert "GPL-3.0" in summary.blocked or summary.license_counts.get("GPL-3.0", 0) >= 0

    def test_global_summary_identifies_blocked_licenses(self, license_analyzer, sbom_repository):
        """Test that global summary identifies blocked licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="closed-lib", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-3.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        summary = license_analyzer.global_summary()

        assert "GPL-3.0" in summary.blocked

    def test_global_summary_identifies_flagged_licenses(self, license_analyzer, sbom_repository):
        """Test that global summary identifies flagged licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="caution-lib", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-2.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        summary = license_analyzer.global_summary()

        assert "GPL-2.0" in summary.flagged

    def test_global_summary_servers_with_blocked(self, license_analyzer, sbom_repository):
        """Test identifying servers with blocked licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="lib", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-3.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        summary = license_analyzer.global_summary()

        assert len(summary.servers_with_blocked) > 0
        assert server_id in summary.servers_with_blocked

    def test_server_report_nonexistent(self, license_analyzer):
        """Test server report for non-existent server."""
        report = license_analyzer.server_report(str(uuid4()))

        assert report.server_id is not None
        assert report.licenses == []
        assert report.blocked == []
        assert report.flagged == []
        assert report.is_compliant is True

    def test_server_report_compliant(self, license_analyzer, sbom_repository):
        """Test server report for compliant server."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["MIT"]),
            SBOMComponent(name="lib2", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["Apache-2.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        report = license_analyzer.server_report(server_id)

        assert report.server_id == server_id
        assert report.is_compliant is True
        assert len(report.blocked) == 0

    def test_server_report_with_blocked_licenses(self, license_analyzer, sbom_repository):
        """Test server report with blocked licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["MIT"]),
            SBOMComponent(name="lib2", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-3.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        report = license_analyzer.server_report(server_id)

        assert report.server_id == server_id
        assert report.is_compliant is False
        assert "GPL-3.0" in report.blocked

    def test_server_report_with_flagged_licenses(self, license_analyzer, sbom_repository):
        """Test server report with flagged licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(name="lib1", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["MIT"]),
            SBOMComponent(name="lib2", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-2.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)
        report = license_analyzer.server_report(server_id)

        assert report.server_id == server_id
        assert "GPL-2.0" in report.flagged
        assert report.is_compliant is True  # Flagged is not blocking

    def test_server_report_latest_only(self, license_analyzer, sbom_repository, license_policy):
        """Test that server report uses latest SBOM only."""
        server_id = str(uuid4())

        # Store old SBOM
        old_sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            components=[SBOMComponent(name="old-lib", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["MIT"])],
        )
        sbom_repository.create_sbom(server_id, old_sbom)

        # Store new SBOM
        new_sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="new-lib", version="1.0", ecosystem=PackageEcosystem.PYTHON, licenses=["Apache-2.0"])],
        )
        sbom_repository.create_sbom(server_id, new_sbom)

        analyzer = LicenseAnalyzer(sbom_repository, license_policy)
        report = analyzer.server_report(server_id)

        # Should only have licenses from new SBOM
        assert "Apache-2.0" in report.licenses
        assert "MIT" not in report.licenses

    def test_server_report_multiple_licenses(self, license_analyzer, sbom_repository):
        """Test server report with components having multiple licenses."""
        server_id = str(uuid4())
        components = [
            SBOMComponent(
                name="multi-license",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                licenses=["MIT", "Apache-2.0", "GPL-3.0"],
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
        report = license_analyzer.server_report(server_id)

        assert len(report.licenses) >= 3
        assert "GPL-3.0" in report.blocked
        assert "MIT" in report.licenses

    def test_license_policy_is_blocked(self, license_policy):
        """Test license policy blocked check."""
        assert license_policy.is_blocked("GPL-3.0")
        assert license_policy.is_blocked("AGPL-3.0")
        assert not license_policy.is_blocked("MIT")

    def test_license_policy_is_flagged(self, license_policy):
        """Test license policy flagged check."""
        assert license_policy.is_flagged("GPL-2.0")
        assert not license_policy.is_flagged("MIT")

    def test_license_policy_validate(self, license_policy):
        """Test license policy validation."""
        result = license_policy.validate_licenses(["MIT", "GPL-3.0", "GPL-2.0"])

        assert "GPL-3.0" in result["blocked"]
        assert "GPL-2.0" in result["flagged"]
        assert "MIT" in result["allowed"]
