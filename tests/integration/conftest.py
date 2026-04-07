#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Fixtures for SBOM API integration tests.
"""

# Standard
from datetime import datetime, timezone
import os
import tempfile
from uuid import uuid4

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import get_db

# Import the FastAPI app and database dependency
from mcpgateway.main import app
from mcpgateway.plugins.framework import PluginConfig, PluginContext
from plugins.sbom_generator.models import (
    LicensePolicy,
    PackageEcosystem,
    SBOMComponent,
    SBOMDocument,
    SBOMFormat,
)
from plugins.sbom_generator.storage.models import Base
from plugins.sbom_generator.storage.repository import SBOMRepository

# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture(scope="function")
def db_engine():
    """Create file-based test database engine.

    Uses a temporary file instead of :memory: to avoid SQLite threading issues
    with async tests.
    """
    # Create temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    # Create engine with thread-safe settings for SQLite
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False, "timeout": 30}, poolclass=StaticPool)

    # Create all tables
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup
    engine.dispose()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def db_session(db_engine):
    """Create database session for tests."""
    SessionLocal = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sbom_repository(db_session):
    """Create SBOM repository."""
    return SBOMRepository(db_session)


# ============================================================================
# FastAPI App Fixture with Database Override
# ============================================================================


@pytest.fixture
def app_fixture(db_engine):  # Notice we take db_engine now, not db_session
    """Provide FastAPI app with test database override."""

    TestingSessionLocal = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def server_id() -> str:
    """Generate test server UUID."""
    return str(uuid4())


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


@pytest.fixture
def populated_sbom(sbom_repository, server_id, sbom_document):
    """Create and populate test SBOM in database.

    NOTE: This is a synchronous fixture because create_sbom is synchronous.
    """
    db_sbom = sbom_repository.create_sbom(
        server_id=server_id,
        sbom_doc=sbom_document,
        compress=False,
    )
    return db_sbom


# ============================================================================
# Plugin Configuration Fixtures
# ============================================================================


@pytest.fixture
def default_config() -> dict:
    """Default plugin configuration for SBOM generator."""
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
    """Create PluginConfig instance for SBOM generator."""
    return PluginConfig(
        name="sbom_generator",
        kind="plugins.sbom_generator.sbom_generator.SBOMGeneratorPlugin",
        version="0.1.0",
        config=default_config,
    )


@pytest.fixture
def license_policy() -> LicensePolicy:
    """Create license policy for testing."""
    return LicensePolicy(
        blocked=["GPL-3.0", "AGPL-3.0"],
        flagged=["GPL-2.0"],
        allowed=[],
    )
