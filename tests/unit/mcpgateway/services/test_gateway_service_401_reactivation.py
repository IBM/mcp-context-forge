# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_401_reactivation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for gateway reactivation on 401/403 responses and last_seen updates.

Specifically targets coverage for gateway_service.py lines:
- 3996-3998: Gateway reactivation when previously unreachable
- 4005-4008: last_seen update and exception handling
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService


class TestGateway401Reactivation:
    """Test gateway reactivation on 401/403 responses (lines 3996-3998, 4005-4008)."""

    def _make_gateway(self, *, enabled=True, reachable=False, transport="sse", auth_type="oauth", oauth_config=None):
        """Helper to create a mock gateway."""
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-gw-401"
        gateway.name = "Test Gateway 401"
        gateway.url = "https://example.com"
        gateway.transport = transport
        gateway.auth_type = auth_type
        gateway.oauth_config = oauth_config or {"grant_type": "authorization_code"}
        gateway.enabled = enabled
        gateway.reachable = reachable
        gateway.auth_value = None
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None
        return gateway

    @pytest.mark.asyncio
    async def test_401_reactivates_previously_unreachable_gateway(self):
        """401 response should reactivate gateway that was previously unreachable (line 3996-3998)."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        # Gateway that was previously unreachable
        gateway = self._make_gateway(enabled=True, reachable=False)

        # Mock database sessions
        update_db = MagicMock()
        mock_db_gateway = MagicMock()
        update_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_db_gateway)))

        status_db = MagicMock()

        # Mock 401 response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status = MagicMock(side_effect=mock_error)

        # Context managers for async operations
        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()  # Token lookup DB

            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db  # last_seen update DB

            def __exit__(self, *exc):
                return False

        class _StatusDBCM:
            def __enter__(self):
                return status_db  # Reactivation DB

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                client = MagicMock()
                stream_cm = MagicMock()
                stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
                stream_cm.__aexit__ = AsyncMock(return_value=False)
                client.stream = MagicMock(return_value=stream_cm)
                return client

            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.SessionLocal", return_value=_StatusDBCM()),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_token_service_class,
        ):
            # Setup fresh_db_session to return token lookup DB, then update DB
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]

            # Mock token service
            mock_token_service = MagicMock()
            mock_token_service.get_user_token = AsyncMock(return_value=None)
            mock_token_service_class.return_value = mock_token_service

            # Run health check
            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

            # Verify gateway was reactivated (line 3996-3998)
            service.set_gateway_state.assert_called_once()
            call_args = service.set_gateway_state.call_args
            assert call_args[0][0] == status_db  # First positional arg is status_db
            assert call_args[1]["activate"] is True
            assert call_args[1]["reachable"] is True
            assert call_args[1]["only_update_reachable"] is True

            # Verify last_seen was updated (line 4005-4006)
            assert mock_db_gateway.last_seen is not None
            assert isinstance(mock_db_gateway.last_seen, datetime)
            update_db.commit.assert_called_once()

            # Verify _handle_gateway_failure was NOT called
            service._handle_gateway_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_403_reactivates_previously_unreachable_gateway(self):
        """403 response should also reactivate gateway that was previously unreachable."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        gateway = self._make_gateway(enabled=True, reachable=False)

        update_db = MagicMock()
        mock_db_gateway = MagicMock()
        update_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_db_gateway)))

        status_db = MagicMock()

        # Mock 403 response
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_error = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status = MagicMock(side_effect=mock_error)

        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _StatusDBCM:
            def __enter__(self):
                return status_db

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                client = MagicMock()
                stream_cm = MagicMock()
                stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
                stream_cm.__aexit__ = AsyncMock(return_value=False)
                client.stream = MagicMock(return_value=stream_cm)
                return client

            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.SessionLocal", return_value=_StatusDBCM()),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_token_service_class,
        ):
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]

            mock_token_service = MagicMock()
            mock_token_service.get_user_token = AsyncMock(return_value=None)
            mock_token_service_class.return_value = mock_token_service

            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

            # Verify reactivation occurred
            service.set_gateway_state.assert_called_once()
            call_args = service.set_gateway_state.call_args
            assert call_args[1]["reachable"] is True

            # Verify last_seen updated
            assert mock_db_gateway.last_seen is not None
            update_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_401_last_seen_update_failure_is_logged(self):
        """Failed last_seen update should be logged but not crash (line 4007-4008)."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        gateway = self._make_gateway(enabled=True, reachable=False)

        # Mock update DB that raises exception
        update_db = MagicMock()
        update_db.execute = MagicMock(side_effect=RuntimeError("Database connection lost"))

        status_db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status = MagicMock(side_effect=mock_error)

        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                # Exception will be caught by try/except in code
                return False

        class _StatusDBCM:
            def __enter__(self):
                return status_db

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                client = MagicMock()
                stream_cm = MagicMock()
                stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
                stream_cm.__aexit__ = AsyncMock(return_value=False)
                client.stream = MagicMock(return_value=stream_cm)
                return client

            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.SessionLocal", return_value=_StatusDBCM()),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_token_service_class,
        ):
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]

            mock_token_service = MagicMock()
            mock_token_service.get_user_token = AsyncMock(return_value=None)
            mock_token_service_class.return_value = mock_token_service

            # Should not crash despite last_seen update failure (line 4007-4008 exception handler)
            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

            # Gateway should still be reactivated
            service.set_gateway_state.assert_called_once()
            assert service.set_gateway_state.call_args[1]["reachable"] is True

            # _handle_gateway_failure should NOT be called (401 is not a genuine failure)
            service._handle_gateway_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_401_already_reachable_gateway_skips_reactivation(self):
        """401 on already-reachable gateway should skip reactivation but still update last_seen."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        # Gateway already enabled and reachable
        gateway = self._make_gateway(enabled=True, reachable=True)

        update_db = MagicMock()
        mock_db_gateway = MagicMock()
        update_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_db_gateway)))

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status = MagicMock(side_effect=mock_error)

        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                client = MagicMock()
                stream_cm = MagicMock()
                stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
                stream_cm.__aexit__ = AsyncMock(return_value=False)
                client.stream = MagicMock(return_value=stream_cm)
                return client

            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_token_service_class,
        ):
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]

            mock_token_service = MagicMock()
            mock_token_service.get_user_token = AsyncMock(return_value=None)
            mock_token_service_class.return_value = mock_token_service

            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

            # Should NOT call set_gateway_state (already reachable)
            service.set_gateway_state.assert_not_called()

            # Should still update last_seen (line 4005-4006)
            assert mock_db_gateway.last_seen is not None
            update_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_401_disabled_gateway_skips_reactivation(self):
        """401 on disabled gateway should not reactivate but should update last_seen."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        # Disabled gateway
        gateway = self._make_gateway(enabled=False, reachable=False)

        update_db = MagicMock()
        mock_db_gateway = MagicMock()
        update_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_db_gateway)))

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status = MagicMock(side_effect=mock_error)

        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                client = MagicMock()
                stream_cm = MagicMock()
                stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
                stream_cm.__aexit__ = AsyncMock(return_value=False)
                client.stream = MagicMock(return_value=stream_cm)
                return client

            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_token_service_class,
        ):
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]

            mock_token_service = MagicMock()
            mock_token_service.get_user_token = AsyncMock(return_value=None)
            mock_token_service_class.return_value = mock_token_service

            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

            # Should NOT call set_gateway_state (gateway disabled)
            service.set_gateway_state.assert_not_called()

            # Should still update last_seen
            assert mock_db_gateway.last_seen is not None
            update_db.commit.assert_called_once()
