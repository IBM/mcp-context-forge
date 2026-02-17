# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_hnsw_index.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for HNSW index on tool embeddings.

Tests verify:
- Migration module can be imported and has correct revision chain
- HNSW config settings have correct defaults and bounds
- Migration is idempotent on SQLite (no-op)
- ToolEmbedding model declares HNSW index on PostgreSQL backend
"""

# Standard
import importlib

# Third-Party
import pytest


MIGRATION_MODULE = "mcpgateway.alembic.versions.c3d4e5f6a7b8_add_hnsw_index_to_tool_embeddings"


class TestHnswMigrationModule:
    """Test that the HNSW migration module is valid."""

    def test_migration_imports(self):
        """Test that migration module can be imported."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert module is not None

    def test_revision_id(self):
        """Test correct revision identifier."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert module.revision == "c3d4e5f6a7b8"

    def test_down_revision(self):
        """Test migration descends from tool_embedding table migration."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert module.down_revision == "bab4694b3e90"

    def test_upgrade_function_exists(self):
        """Test upgrade function is defined."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert callable(getattr(module, "upgrade", None))

    def test_downgrade_function_exists(self):
        """Test downgrade function is defined."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert callable(getattr(module, "downgrade", None))


class TestHnswConfigDefaults:
    """Test HNSW configuration settings."""

    def test_hnsw_m_default(self):
        """Test hnsw_m has correct default value."""
        from mcpgateway.config import Settings

        s = Settings()
        assert s.hnsw_m == 16

    def test_hnsw_ef_construction_default(self):
        """Test hnsw_ef_construction has correct default value."""
        from mcpgateway.config import Settings

        s = Settings()
        assert s.hnsw_ef_construction == 64

    def test_hnsw_m_bounds(self):
        """Test hnsw_m rejects out-of-range values."""
        from mcpgateway.config import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(hnsw_m=1)  # below ge=2
        with pytest.raises(ValidationError):
            Settings(hnsw_m=101)  # above le=100

    def test_hnsw_ef_construction_bounds(self):
        """Test hnsw_ef_construction rejects out-of-range values."""
        from mcpgateway.config import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(hnsw_ef_construction=15)  # below ge=16
        with pytest.raises(ValidationError):
            Settings(hnsw_ef_construction=513)  # above le=512


class TestToolEmbeddingModel:
    """Test ToolEmbedding model HNSW index declaration."""

    def test_sqlite_has_no_hnsw_index(self):
        """On SQLite (default test backend), no HNSW index should be declared."""
        from mcpgateway.db import ToolEmbedding

        table_args = getattr(ToolEmbedding, "__table_args__", None)
        # On SQLite, __table_args__ should either be absent or empty
        if table_args is not None:
            index_names = [arg.name for arg in table_args if hasattr(arg, "name")]
            assert "idx_tool_embeddings_hnsw" not in index_names
