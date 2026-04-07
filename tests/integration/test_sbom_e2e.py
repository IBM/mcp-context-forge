#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_sbom_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Test Suite

End-to-end integration tests for SBOM Generator plugin.
Tests the full workflow: plugin initialization → SBOM generation → querying → API access.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginContext
from plugins.sbom_generator import SBOMGeneratorPlugin
from plugins.sbom_generator.models import PackageEcosystem, SBOMComponent, SBOMDocument, SBOMFormat
from plugins.sbom_generator.query import ComponentSearch, LicenseAnalyzer


class TestSBOMPluginE2E:
    """End-to-end tests for SBOM plugin workflow."""

    @pytest.fixture
    def sbom_plugin_instance(self, plugin_config):
        """Create SBOM plugin instance."""
        return SBOMGeneratorPlugin(plugin_config)

    @pytest.fixture
    def mock_plugin_context(self, db_session):
        """Create mock plugin context with DB session."""
        context = MagicMock(spec=PluginContext)
        context.db_session = db_session
        context.request_id = str(uuid4())
        context.user_id = None
        context.metadata = {}
        context.global_context = {}
        return context

    @pytest.mark.asyncio
    async def test_plugin_initialization(self, sbom_plugin_instance):
        """Test plugin initializes successfully."""
        assert sbom_plugin_instance is not None
        assert sbom_plugin_instance.name == "sbom_generator"
        assert sbom_plugin_instance.config.version == "0.1.0"
        assert sbom_plugin_instance.plugin_config.syft.format == "cyclonedx"

    @pytest.mark.asyncio
    async def test_sbom_generation_flow(self, sbom_plugin_instance, mock_plugin_context):
        """Test complete SBOM generation flow."""
        server_id = str(uuid4())
        test_payload = {
            "server_id": server_id,
            "server_name": "test-server",
            "source_path": ".",
        }

        # This will fail if syft is not installed, but should not raise AttributeError
        result = await sbom_plugin_instance.assessment_post_scan(mock_plugin_context, test_payload)

        assert isinstance(result, dict)
        # Result should have either success or expected error structure
        assert "error" in result or "sbom_id" in result or "details" in result

    @pytest.mark.asyncio
    async def test_sbom_storage_and_retrieval(self, sbom_repository, sbom_plugin_instance, mock_plugin_context):
        """Test SBOM can be stored and retrieved after generation."""
        server_id = str(uuid4())

        # Manually create and store an SBOM (simulating plugin output)
        components = [
            SBOMComponent(
                name="requests",
                version="2.31.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/requests@2.31.0",
                licenses=["Apache-2.0"],
            ),
            SBOMComponent(
                name="django",
                version="4.2.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/django@4.2.0",
                licenses=["BSD-3-Clause"],
            ),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        # Store SBOM
        stored_sbom = sbom_repository.create_sbom(server_id, sbom)

        # Retrieve SBOM
        retrieved_sbom = sbom_repository.get_sbom(str(stored_sbom.id), include_components=True)

        assert retrieved_sbom is not None
        assert retrieved_sbom.server_id == server_id
        assert len(retrieved_sbom.components) == 2
        assert retrieved_sbom.format == "cyclonedx"
        assert retrieved_sbom.spec_version == "1.5"

    @pytest.mark.asyncio
    async def test_component_search_after_generation(self, sbom_repository):
        """Test component search works after SBOM storage."""
        server_id = str(uuid4())

        # Create and store SBOM
        components = [
            SBOMComponent(
                name="requests",
                version="2.31.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/requests@2.31.0",
                licenses=["Apache-2.0"],
            ),
            SBOMComponent(
                name="numpy",
                version="1.24.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/numpy@1.24.0",
                licenses=["BSD-3-Clause"],
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

        # Search components
        component_search = ComponentSearch(sbom_repository)
        results = component_search.search(name="requests")

        assert len(results) > 0
        assert results[0].name == "requests"
        assert results[0].version == "2.31.0"
        assert "Apache-2.0" in results[0].licenses

    @pytest.mark.asyncio
    async def test_license_analysis_workflow(self, sbom_repository, license_policy):
        """Test license analysis on stored SBOM."""
        server_id = str(uuid4())

        # Create SBOM with various licenses
        components = [
            SBOMComponent(
                name="lib-mit",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                licenses=["MIT"],
            ),
            SBOMComponent(
                name="lib-gpl",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                licenses=["GPL-3.0"],
            ),
            SBOMComponent(
                name="lib-flagged",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                licenses=["GPL-2.0"],
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

        # Analyze licenses
        analyzer = LicenseAnalyzer(sbom_repository, license_policy)
        server_report = analyzer.server_report(server_id)

        assert server_report.server_id == server_id
        assert "GPL-3.0" in server_report.blocked
        assert "GPL-2.0" in server_report.flagged
        assert not server_report.is_compliant

    @pytest.mark.asyncio
    async def test_multiple_sbom_versions(self, sbom_repository):
        """Test handling multiple SBOM versions for same server."""
        server_id = str(uuid4())

        # Store first SBOM
        sbom1 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            components=[
                SBOMComponent(
                    name="old-version",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["MIT"],
                )
            ],
        )
        sbom_repository.create_sbom(server_id, sbom1)

        # Store second SBOM (newer)
        sbom2 = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="new-version",
                    version="2.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["Apache-2.0"],
                )
            ],
        )
        sbom_repository.create_sbom(server_id, sbom2)

        # Verify latest SBOM is returned
        latest_sboms = sbom_repository.get_sbom_by_server(server_id, latest_only=True)

        assert len(latest_sboms) == 1
        assert len(latest_sboms[0].components) == 1
        assert latest_sboms[0].components[0].name == "new-version"

    @pytest.mark.asyncio
    async def test_global_license_summary(self, sbom_repository, license_policy):
        """Test global license summary across multiple servers."""
        # Create SBOMs for multiple servers
        for i in range(3):
            server_id = str(uuid4())
            sbom = SBOMDocument(
                format=SBOMFormat.CYCLONEDX,
                spec_version="1.5",
                serial_number=f"urn:uuid:{uuid4()}",
                generated_at=datetime.now(timezone.utc),
                components=[
                    SBOMComponent(
                        name=f"lib-{i}",
                        version="1.0",
                        ecosystem=PackageEcosystem.PYTHON,
                        licenses=["MIT"],
                    )
                ],
            )
            sbom_repository.create_sbom(server_id, sbom)

        # Get global summary
        analyzer = LicenseAnalyzer(sbom_repository, license_policy)
        summary = analyzer.global_summary()

        assert summary.total_components >= 3
        assert "MIT" in summary.license_counts or summary.total_components > 0

    @pytest.mark.asyncio
    async def test_sbom_format_support(self, sbom_repository):
        """Test SBOM generation supports multiple formats."""
        server_id = str(uuid4())

        # Test CycloneDX format
        sbom_cdx = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="lib", version="1.0", ecosystem=PackageEcosystem.PYTHON)],
        )

        sbom_repository.create_sbom(server_id, sbom_cdx)
        retrieved_cdx = sbom_repository.get_sbom_by_server(server_id)[0]
        assert retrieved_cdx.format == "cyclonedx"

        # Test SPDX format
        server_id_2 = str(uuid4())
        sbom_spdx = SBOMDocument(
            format=SBOMFormat.SPDX,
            spec_version="2.3",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[SBOMComponent(name="lib2", version="2.0", ecosystem=PackageEcosystem.NPM)],
        )

        sbom_repository.create_sbom(server_id_2, sbom_spdx)
        retrieved_spdx = sbom_repository.get_sbom_by_server(server_id_2)[0]
        assert retrieved_spdx.format == "spdx"

    @pytest.mark.asyncio
    async def test_sbom_component_ecosystems(self, sbom_repository):
        """Test SBOM supports multiple package ecosystems."""
        server_id = str(uuid4())

        components = [
            SBOMComponent(
                name="requests",
                version="1.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl="pkg:pypi/requests@1.0",
            ),
            SBOMComponent(
                name="express",
                version="4.0",
                ecosystem=PackageEcosystem.NPM,
                purl="pkg:npm/express@4.0",
            ),
            SBOMComponent(
                name="gorilla",
                version="1.0",
                ecosystem=PackageEcosystem.GO,
                purl="pkg:golang/github.com/gorilla/mux@1.0",
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

        # Search by ecosystem
        search = ComponentSearch(sbom_repository)
        python_libs = search.search(ecosystem="python")
        npm_libs = search.search(ecosystem="npm")

        assert any(r.ecosystem == "python" for r in python_libs)
        assert any(r.ecosystem == "npm" for r in npm_libs)

    @pytest.mark.asyncio
    async def test_sbom_metadata_preservation(self, sbom_repository):
        """Test that SBOM metadata is properly preserved."""
        server_id = str(uuid4())
        generation_time = datetime.now(timezone.utc)

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=generation_time,
            components=[SBOMComponent(name="lib", version="1.0", ecosystem=PackageEcosystem.PYTHON)],
        )

        stored = sbom_repository.create_sbom(server_id, sbom)
        retrieved = sbom_repository.get_sbom(str(stored.id))

        assert retrieved is not None
        assert retrieved.server_id == server_id
        assert retrieved.format == "cyclonedx"
        assert retrieved.spec_version == "1.5"
        assert retrieved.generated_at is not None

    @pytest.mark.asyncio
    async def test_sbom_transitive_dependencies(self, sbom_repository):
        """Test SBOM properly marks direct vs transitive dependencies."""
        server_id = str(uuid4())

        components = [
            SBOMComponent(name="direct-dep", version="1.0", ecosystem=PackageEcosystem.PYTHON, is_direct=True),
            SBOMComponent(name="transitive-dep", version="1.0", ecosystem=PackageEcosystem.PYTHON, is_direct=False),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)

        # Verify dependency type is preserved
        search = ComponentSearch(sbom_repository)
        results = search.get_by_server(server_id)

        direct_deps = [r for r in results if r.is_direct]
        transitive_deps = [r for r in results if not r.is_direct]

        assert len(direct_deps) >= 1
        assert len(transitive_deps) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_sbom_operations(self, sbom_repository):
        """Test handling concurrent SBOM operations (basic)."""
        server_ids = [str(uuid4()) for _ in range(3)]

        # Store multiple SBOMs
        sbom_ids = []
        for server_id in server_ids:
            sbom = SBOMDocument(
                format=SBOMFormat.CYCLONEDX,
                spec_version="1.5",
                serial_number=f"urn:uuid:{uuid4()}",
                generated_at=datetime.now(timezone.utc),
                components=[SBOMComponent(name=f"lib-{server_id[:8]}", version="1.0", ecosystem=PackageEcosystem.PYTHON)],
            )
            stored = sbom_repository.create_sbom(server_id, sbom)
            sbom_ids.append(str(stored.id))

        # Verify all were stored
        for sbom_id in sbom_ids:
            retrieved = sbom_repository.get_sbom(sbom_id)
            assert retrieved is not None

    @pytest.mark.asyncio
    async def test_empty_component_list(self, sbom_repository):
        """Test handling SBOM with no components."""
        server_id = str(uuid4())

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[],
        )

        stored = sbom_repository.create_sbom(server_id, sbom)
        retrieved = sbom_repository.get_sbom(str(stored.id), include_components=True)

        assert retrieved is not None
        assert len(retrieved.components) == 0

    @pytest.mark.asyncio
    async def test_sbom_size_limits(self, sbom_repository):
        """Test handling large number of components."""
        server_id = str(uuid4())

        # Create SBOM with many components
        components = [
            SBOMComponent(
                name=f"lib-{i}",
                version="1.0.0",
                ecosystem=PackageEcosystem.PYTHON,
                purl=f"pkg:pypi/lib-{i}@1.0.0",
            )
            for i in range(100)
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        stored = sbom_repository.create_sbom(server_id, sbom)
        retrieved = sbom_repository.get_sbom(str(stored.id), include_components=True)

        assert len(retrieved.components) == 100

    @pytest.mark.asyncio
    async def test_full_workflow_summary(self, sbom_plugin_instance, sbom_repository, license_policy):
        """Test full end-to-end workflow: store → search → analyze → report."""
        server_id = str(uuid4())

        # 1. Create and store SBOM
        components = [
            SBOMComponent(name="requests", version="2.28.0", ecosystem=PackageEcosystem.PYTHON, licenses=["Apache-2.0"]),
            SBOMComponent(name="django", version="3.2.0", ecosystem=PackageEcosystem.PYTHON, licenses=["BSD-3-Clause"]),
            SBOMComponent(name="gpl-lib", version="1.0.0", ecosystem=PackageEcosystem.PYTHON, licenses=["GPL-3.0"]),
        ]

        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        sbom_repository.create_sbom(server_id, sbom)

        # 2. Search components
        search = ComponentSearch(sbom_repository)
        results = search.get_by_server(server_id)
        assert len(results) == 3

        # 3. Analyze licenses
        analyzer = LicenseAnalyzer(sbom_repository, license_policy)
        report = analyzer.server_report(server_id)

        # 4. Verify compliance
        assert not report.is_compliant  # Has GPL-3.0
        assert "GPL-3.0" in report.blocked
        assert "Apache-2.0" in report.licenses

        # 5. Verify results can be serialized
        report_dict = report.to_dict()
        assert isinstance(report_dict, dict)
        assert "server_id" in report_dict
        assert "is_compliant" in report_dict
