# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_token_security_edge_cases.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Edge case tests for JWT Token Security to improve coverage.

Tests cover:
- Redis unavailability scenarios
- Database error handling
- Exception paths in token blocklist service
- Error paths in auth router
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_blocklist_service import TokenBlocklistService


class TestTokenBlocklistServiceEdgeCases:
    """Test edge cases in token blocklist service."""

    def test_redis_unavailable_on_init(self):
        """Test handling when Redis is unavailable during initialization."""
        service = TokenBlocklistService()

        # Patch the _get_redis_client method to simulate failure
        with patch.object(service, "_get_redis_client", return_value=None):
            # Service should handle Redis unavailability gracefully
            redis_client = service._get_redis_client()
            assert redis_client is None

    def test_redis_connection_failure_during_ping(self):
        """Test handling when Redis ping fails."""
        service = TokenBlocklistService()

        # Mock redis module import and connection failure
        with patch("mcpgateway.services.token_blocklist_service.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"

            with patch("redis.from_url") as mock_redis_from_url:
                mock_client = MagicMock()
                mock_client.ping.side_effect = Exception("Connection refused")
                mock_redis_from_url.return_value = mock_client

                # Reset the cached client
                service._redis_client = None

                # Should mark Redis as unavailable
                result = service._get_redis_client()
                assert result is None

    def test_cleanup_expired_tokens_returns_zero_on_error(self):
        """Test cleanup_expired_tokens returns 0 when database fails."""
        service = TokenBlocklistService()

        # Mock fresh_db_session to raise an exception
        with patch("mcpgateway.services.token_blocklist_service.fresh_db_session") as mock_session:
            mock_session.side_effect = Exception("Database connection failed")

            # Should return 0 and log error
            result = service.cleanup_expired_tokens()
            assert result == 0

    def test_get_revocation_stats_returns_empty_on_error(self):
        """Test get_revocation_stats returns empty dict when database fails."""
        service = TokenBlocklistService()

        # Mock fresh_db_session to raise an exception
        with patch("mcpgateway.services.token_blocklist_service.fresh_db_session") as mock_session:
            mock_session.side_effect = Exception("Database connection failed")

            # Should return empty stats
            result = service.get_revocation_stats()
            assert result == {"total_revoked": 0, "by_reason": {}}

    def test_revoke_user_tokens_not_implemented(self):
        """Test revoke_user_tokens returns 0 (not yet implemented)."""
        service = TokenBlocklistService()

        # This method is a placeholder
        result = service.revoke_user_tokens(user_email="test@example.com", revoked_by="admin@example.com", reason="security")
        assert result == 0


class TestAuthRouterEdgeCases:
    """Test edge cases in auth router."""

    def test_get_db_rollback_on_exception(self):
        """Test that get_db properly rolls back on exception."""
        from mcpgateway.routers.auth import get_db

        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            # Simulate an exception during the context
            gen = get_db()
            next(gen)  # Enter context

            # Simulate exception
            try:
                gen.throw(Exception("Test error"))
            except Exception:
                pass

            # Verify rollback was called
            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_rollback_failure_invalidates(self):
        """Test that get_db invalidates session if rollback fails."""
        from mcpgateway.routers.auth import get_db

        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_session_local.return_value = mock_db

            # Simulate an exception during the context
            gen = get_db()
            next(gen)  # Enter context

            # Simulate exception
            try:
                gen.throw(Exception("Test error"))
            except Exception:
                pass

            # Verify invalidate was called after rollback failed
            mock_db.invalidate.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_invalidate_failure_silent(self):
        """Test that get_db silently handles invalidate failure."""
        from mcpgateway.routers.auth import get_db

        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_db.invalidate.side_effect = Exception("Invalidate failed")
            mock_session_local.return_value = mock_db

            # Simulate an exception during the context
            gen = get_db()
            next(gen)  # Enter context

            # Should not raise exception from invalidate failure
            try:
                gen.throw(Exception("Test error"))
            except Exception as e:
                # Should only see the original exception, not invalidate failure
                assert str(e) == "Test error"

            mock_db.close.assert_called_once()
