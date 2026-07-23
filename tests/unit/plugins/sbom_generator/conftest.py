#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.plugins.framework import PluginConfig, PluginContext
from plugins.sbom_generator import SBOMGeneratorPlugin
from plugins.sbom_generator.config import SBOMGeneratorConfig
from plugins.sbom_generator.models import (
    ExtractionResult,
    ExtractionSource,
    PackageEcosystem,
    SBOMComponent,
    SBOMDocument,
    SBOMFormat,
)
from plugins.sbom_generator.storage.models import (
    Base,
    SBOMDocumentDB,
)
from plugins.sbom_generator.storage.repository import SBOMRepository

# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def db_engine():
    """Create in-memory SQLite database engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Create database session."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sbom_repository(db_session):
    """Create SBOM repository."""
    return SBOMRepository(db_session)


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def default_config() -> dict:
    """Default plugin configuration."""
    return {
        "syft": {
            "enabled": True,
            "format": "cyclonedx",
            "spec_version": "1.5",
            "include_dev_deps": False,
            "include_files": False,
            "timeout_seconds": 300,
        },
        "license": {
            "detect_licenses": True,
            "blocked_licenses": ["GPL-3.0", "AGPL-3.0"],
            "warn_licenses": ["GPL-2.0"],
        },
        "storage": {
            "store_full_sbom": True,
            "retention_days": 365,
            "enable_compression": False,
        },
        "fail_on_blocked_licenses": True,
        "fail_on_missing_sbom": False,
    }


@pytest.fixture
def plugin_config(default_config) -> PluginConfig:
    """Create PluginConfig instance."""
    return PluginConfig(
        name="sbom_generator",
        kind="plugins.sbom_generator.sbom_generator.SBOMGeneratorPlugin",
        version="0.1.0",
        config=default_config,
    )


@pytest.fixture
def sbom_config(default_config) -> SBOMGeneratorConfig:
    """Create SBOMGeneratorConfig instance."""
    return SBOMGeneratorConfig(**default_config)


# ============================================================================
# Plugin Fixtures
# ============================================================================


@pytest.fixture
def sbom_plugin(plugin_config) -> SBOMGeneratorPlugin:
    """Create SBOM Generator plugin instance."""
    return SBOMGeneratorPlugin(plugin_config)


@pytest.fixture
def plugin_context(db_session) -> PluginContext:
    """Create mock plugin context."""
    context = MagicMock(spec=PluginContext)
    context.db_session = db_session  # Use real session
    context.request_id = str(uuid4())
    context.user_id = str(uuid4())
    return context


# ============================================================================
# Data Model Fixtures
# ============================================================================


@pytest.fixture
def sample_component() -> SBOMComponent:
    """Create sample SBOM component."""
    return SBOMComponent(
        name="requests",
        version="2.31.0",
        ecosystem=PackageEcosystem.PYTHON,
        purl="pkg:pypi/requests@2.31.0",
        licenses=["Apache-2.0"],
        hash_sha256="abc123def456",
        is_direct=True,
        metadata={"author": "Kenneth Reitz"},
    )


@pytest.fixture
def sample_components() -> list[SBOMComponent]:
    """Create list of sample components."""
    return [
        SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0"],
            is_direct=True,
        ),
        SBOMComponent(
            name="urllib3",
            version="2.0.7",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/urllib3@2.0.7",
            licenses=["MIT"],
            is_direct=False,
        ),
        SBOMComponent(
            name="certifi",
            version="2023.7.22",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/certifi@2023.7.22",
            licenses=["MPL-2.0"],
            is_direct=False,
        ),
    ]


@pytest.fixture
def extraction_result(sample_components) -> ExtractionResult:
    """Create sample extraction result."""
    return ExtractionResult(
        components=sample_components,
        source=ExtractionSource.SOURCE_DIRECTORY,
        source_path="/app/src",
        extracted_at=datetime.now(timezone.utc),
        tool_name="syft",
        tool_version="0.90.0",
        extraction_duration_ms=1500,
        errors=[],
        warnings=["Some packages lack license information"],
    )


@pytest.fixture
def sbom_document(sample_components) -> SBOMDocument:
    """Create sample SBOM document."""
    return SBOMDocument(
        format=SBOMFormat.CYCLONEDX,
        spec_version="1.5",
        serial_number=f"urn:uuid:{uuid4()}",
        version=1,
        generated_at=datetime.now(timezone.utc),
        main_component_name="test-mcp-server",
        main_component_version="1.0.0",
        components=sample_components,
        tool_name="mcp-gateway-sbom-generator",
        tool_version="0.1.0",
        metadata={"scan_type": "source_directory"},
    )


# ============================================================================
# Database Record Fixtures
# ============================================================================


@pytest.fixture
def server_id() -> str:
    """Generate test server UUID."""
    return str(uuid4())


@pytest.fixture
def db_sbom_document(
    sbom_repository: SBOMRepository,
    server_id: str,
    sbom_document: SBOMDocument,
) -> SBOMDocumentDB:
    """Create SBOM document in test database."""
    return sbom_repository.create_sbom(
        server_id=server_id,
        sbom_doc=sbom_document,
        compress=False,
    )


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def assessment_payload(server_id: str) -> dict:
    """Create mock assessment payload."""
    return {
        "server_id": server_id,
        "server_name": "test-mcp-server",
        "server_version": "1.0.0",
        "server_type": "container",
        "image_name": "mcp-server:latest",
        "source_path": "/app/src",
    }


@pytest.fixture
def blocked_license_component() -> SBOMComponent:
    """Create component with blocked license."""
    return SBOMComponent(
        name="copyleft-lib",
        version="1.0.0",
        ecosystem=PackageEcosystem.PYTHON,
        purl="pkg:pypi/copyleft-lib@1.0.0",
        licenses=["GPL-3.0"],
        is_direct=True,
    )


@pytest.fixture
def blocked_license_sbom(blocked_license_component) -> SBOMDocument:
    """Create SBOM with blocked license."""
    return SBOMDocument(
        format=SBOMFormat.CYCLONEDX,
        spec_version="1.5",
        serial_number=f"urn:uuid:{uuid4()}",
        version=1,
        generated_at=datetime.now(timezone.utc),
        main_component_name="test-server",
        main_component_version="1.0.0",
        components=[blocked_license_component],
    )
