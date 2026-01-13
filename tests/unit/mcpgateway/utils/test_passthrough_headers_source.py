# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_passthrough_headers_source.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for PASSTHROUGH_HEADERS_SOURCE configuration feature.
Passthrough can take precedence from:
- Environment variables only ("env" mode)
- Database only with env fallback ("db" mode)
- Merged union of both sources ("merge" mode)
"""

# Standard
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache


@pytest.fixture
def mock_db():
    return Mock()


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure cache is clean before each test"""
    global_config_cache.invalidate()
    yield
    global_config_cache.invalidate()


class TestPassthroughHeadersSource:
    """Test suite for different passthrough header source modes."""

    def test_env_mode_ignores_db(self, mock_db):
        """Test that 'env' mode uses environment variables and ignores database."""
        # Setup: DB has one set of headers, Env has another
        mock_config = Mock()
        mock_config.passthrough_headers = ["X-From-DB"]
        mock_db.query.return_value.first.return_value = mock_config

        env_headers = ["X-From-Env"]

        with patch("mcpgateway.config.settings.passthrough_headers_source", "env"):
            # Execute
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            # Verify
            assert result == ["X-From-Env"]

    def test_env_mode_empty_defaults(self, mock_db):
        """Test 'env' mode with empty defaults returns empty list."""
        mock_config = Mock()
        mock_config.passthrough_headers = ["X-From-DB"]
        mock_db.query.return_value.first.return_value = mock_config

        with patch("mcpgateway.config.settings.passthrough_headers_source", "env"):
            result = global_config_cache.get_passthrough_headers(mock_db, [])
            assert result == []

    def test_merge_mode_unions_sources(self, mock_db):
        """Test 'merge' mode combines headers from both sources."""
        # Setup
        mock_config = Mock()
        mock_config.passthrough_headers = ["X-Common", "X-Only-DB"]
        mock_db.query.return_value.first.return_value = mock_config

        env_headers = ["X-Common", "X-Only-Env"]

        with patch("mcpgateway.config.settings.passthrough_headers_source", "merge"):
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            # Verify contents (order doesn't matter for correctness, but list is returned)
            assert len(result) == 3
            assert "X-Common" in result
            assert "X-Only-DB" in result
            assert "X-Only-Env" in result

    def test_merge_mode_casing_precedence(self, mock_db):
        """Test that 'merge' mode uses DB casing for duplicates."""
        # Setup
        mock_config = Mock()
        mock_config.passthrough_headers = ["X-COMMON-HEADER"]  # DB has uppercase
        mock_db.query.return_value.first.return_value = mock_config

        env_headers = ["x-common-header"]  # Env has lowercase

        with patch("mcpgateway.config.settings.passthrough_headers_source", "merge"):
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            # Should contain only one entry
            assert len(result) == 1
            # Should match DB casing
            assert result[0] == "X-COMMON-HEADER"

    def test_merge_mode_no_db_config(self, mock_db):
        """Test 'merge' mode works when DB result is None."""
        mock_db.query.return_value.first.return_value = None

        env_headers = ["X-Env-Only"]

        with patch("mcpgateway.config.settings.passthrough_headers_source", "merge"):
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            assert result == ["X-Env-Only"]

    def test_db_mode_fallback(self, mock_db):
        """Test 'db' mode falls back to env if DB config is missing."""
        mock_db.query.return_value.first.return_value = None
        env_headers = ["X-Fallback"]

        with patch("mcpgateway.config.settings.passthrough_headers_source", "db"):
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            assert result == ["X-Fallback"]

    def test_db_mode_priority(self, mock_db):
        """Test 'db' mode strictly uses DB config if present."""
        mock_config = Mock()
        mock_config.passthrough_headers = ["X-DB"]
        mock_db.query.return_value.first.return_value = mock_config

        env_headers = ["X-Env"]

        with patch("mcpgateway.config.settings.passthrough_headers_source", "db"):
            result = global_config_cache.get_passthrough_headers(mock_db, env_headers)

            assert result == ["X-DB"]


class TestSetGlobalPassthroughHeaders:
    """Test suite for set_global_passthrough_headers function."""

    @pytest.mark.asyncio
    async def test_env_mode_skips_db_operations(self, mock_db):
        """Test that 'env' mode skips database writes entirely."""
        from mcpgateway.utils.passthrough_headers import set_global_passthrough_headers

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.passthrough_headers_source = "env"

            await set_global_passthrough_headers(mock_db)

            # Should NOT query or write to database
            mock_db.query.assert_not_called()
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()
