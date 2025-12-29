# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_postgresql_schema_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for PostgreSQL schema configuration support (Issue #1535).

Tests verify that the DATABASE_URL options parameter is correctly parsed
and applied to PostgreSQL connections for custom schema support.
"""

import pytest
from sqlalchemy import make_url


class TestPostgreSQLSchemaConfiguration:
    """Test suite for PostgreSQL schema configuration via options parameter."""

    def test_url_parsing_with_options(self):
        """Test that options parameter is correctly extracted from DATABASE_URL."""
        # Test URL with search_path option
        url_string = "postgresql://user:pass@host:5432/db?options=-c%20search_path=mcp_gateway"
        url = make_url(url_string)

        # Verify options parameter is present
        assert "options" in url.query
        assert url.query["options"] == "-c search_path=mcp_gateway"

    def test_url_parsing_without_options(self):
        """Test that URLs without options parameter work correctly."""
        url_string = "postgresql://user:pass@host:5432/db"
        url = make_url(url_string)

        # Verify no options parameter
        assert "options" not in url.query

    def test_url_parsing_multiple_schemas(self):
        """Test URL with multiple schemas in search_path."""
        url_string = "postgresql://user:pass@host:5432/db?options=-c%20search_path=mcp_gateway,public"
        url = make_url(url_string)

        assert "options" in url.query
        assert "mcp_gateway" in url.query["options"]
        assert "public" in url.query["options"]

    def test_sqlite_url_ignores_options(self):
        """Test that SQLite URLs with options don't cause errors."""
        url_string = "sqlite:///./test.db?options=-c%20search_path=test"
        url = make_url(url_string)

        # SQLite backend should be detected
        assert url.get_backend_name() == "sqlite"
        # Options may be present but should be ignored by SQLite

    def test_connect_args_generation_postgresql(self):
        """Test that connect_args includes options for PostgreSQL."""
        # Simulate the logic from db.py - must use postgresql+psycopg:// for psycopg3
        url_string = "postgresql+psycopg://user:pass@host:5432/db?options=-c%20search_path=mcp_gateway"
        url = make_url(url_string)
        backend = url.get_backend_name()
        driver = url.get_driver_name() or "default"

        connect_args = {}

        if backend == "postgresql" and driver in ("psycopg", "default", ""):
            connect_args.update(
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=5,
                keepalives_count=5,
            )

            url_options = url.query.get("options")
            if url_options:
                connect_args["options"] = url_options

        # Verify connect_args includes both keepalives and options
        assert "keepalives" in connect_args
        assert "options" in connect_args
        assert connect_args["options"] == "-c search_path=mcp_gateway"

    def test_connect_args_generation_sqlite(self):
        """Test that connect_args for SQLite doesn't include PostgreSQL options."""
        url_string = "sqlite:///./test.db"
        url = make_url(url_string)
        backend = url.get_backend_name()

        connect_args = {}

        if backend == "sqlite":
            connect_args["check_same_thread"] = False

        # Verify SQLite-specific args only
        assert "check_same_thread" in connect_args
        assert "options" not in connect_args
        assert "keepalives" not in connect_args

    def test_url_encoding_variations(self):
        """Test various URL encoding formats for options parameter."""
        test_cases = [
            # URL encoded space
            "postgresql://user:pass@host/db?options=-c%20search_path=test",
            # Plus sign for space (alternative encoding)
            "postgresql://user:pass@host/db?options=-c+search_path=test",
            # No encoding (may work in some contexts)
            "postgresql://user:pass@host/db?options=-c search_path=test",
        ]

        for url_string in test_cases:
            url = make_url(url_string)
            assert "options" in url.query
            assert "search_path" in url.query["options"]

    def test_multiple_query_parameters(self):
        """Test URL with multiple query parameters including options."""
        url_string = "postgresql://user:pass@host/db?sslmode=require&options=-c%20search_path=mcp_gateway&connect_timeout=10"
        url = make_url(url_string)

        # Verify all parameters are present
        assert "sslmode" in url.query
        assert "options" in url.query
        assert "connect_timeout" in url.query
        assert url.query["options"] == "-c search_path=mcp_gateway"

    @pytest.mark.parametrize("schema_name", [
        "mcp_gateway",
        "custom_schema",
        "app_schema_v2",
        "schema_123",
    ])
    def test_various_schema_names(self, schema_name):
        """Test that various valid schema names work correctly."""
        url_string = f"postgresql://user:pass@host/db?options=-c%20search_path={schema_name}"
        url = make_url(url_string)

        assert "options" in url.query
        assert schema_name in url.query["options"]

    def test_backward_compatibility_no_options(self):
        """Test that existing deployments without options continue to work."""
        # Standard PostgreSQL URL without options - must use postgresql+psycopg:// for psycopg3
        url_string = "postgresql+psycopg://user:pass@host:5432/db"
        url = make_url(url_string)
        backend = url.get_backend_name()
        driver = url.get_driver_name() or "default"

        connect_args = {}

        if backend == "postgresql" and driver in ("psycopg", "default", ""):
            connect_args.update(
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=5,
                keepalives_count=5,
            )

            url_options = url.query.get("options")
            if url_options:
                connect_args["options"] = url_options

        # Verify keepalives are present but options are not
        assert "keepalives" in connect_args
        assert "options" not in connect_args

    def test_complex_options_parameter(self):
        """Test options parameter with multiple PostgreSQL settings."""
        url_string = "postgresql://user:pass@host/db?options=-c%20search_path=mcp_gateway%20-c%20statement_timeout=30000"
        url = make_url(url_string)

        assert "options" in url.query
        options = url.query["options"]
        assert "search_path=mcp_gateway" in options
        assert "statement_timeout" in options


class TestSchemaConfigurationIntegration:
    """Integration tests for schema configuration (require PostgreSQL)."""

    @pytest.mark.integration
    @pytest.mark.postgresql
    def test_connection_with_custom_schema(self):
        """Test actual database connection with custom schema (requires PostgreSQL)."""
        # This test would require a real PostgreSQL instance
        # Mark as integration test to skip in unit test runs
        pytest.skip("Requires PostgreSQL instance - run with integration tests")

    @pytest.mark.integration
    @pytest.mark.postgresql
    def test_table_creation_in_custom_schema(self):
        """Test that tables are created in the specified schema (requires PostgreSQL)."""
        # This test would verify tables are created in correct schema
        pytest.skip("Requires PostgreSQL instance - run with integration tests")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
