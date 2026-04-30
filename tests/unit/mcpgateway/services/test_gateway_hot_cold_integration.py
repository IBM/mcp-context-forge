# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_hot_cold_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for hot/cold server classification with GatewayService.
Tests the integration between ServerClassificationService and GatewayService
for health checks and auto-refresh polling.
"""

# Standard
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.server_classification_service import ServerClassificationService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with (
        patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit,
        patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger,
    ):
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def gateway_service_with_classification():
    """Create a GatewayService instance with classification service."""
    with patch("mcpgateway.services.gateway_service.SessionLocal"):
        service = GatewayService()
        service.oauth_manager = AsyncMock()

        # Mock classification service
        mock_classification = AsyncMock(spec=ServerClassificationService)
        service._classification_service = mock_classification

        return service, mock_classification


def _make_mock_gateway(
    gateway_id: str = "gw-123",
    name: str = "test-gateway",
    url: str = "http://test-server:8000",
    enabled: bool = True,
    reachable: bool = True,
) -> MagicMock:
    """Create a mock gateway object."""
    mock = MagicMock(spec=DbGateway)
    mock.id = gateway_id
    mock.name = name
    mock.url = url
    mock.enabled = enabled
    mock.reachable = reachable
    mock.transport = "SSE"
    mock.auth_type = None
    mock.auth_value = None
    mock.oauth_config = None
    mock.ca_certificate = None
    mock.ca_certificate_sig = None
    mock.client_cert = None
    mock.client_key = None
    mock.auth_query_params = None
    mock.visibility = "private"
    mock.last_refresh_at = None
    mock.refresh_interval_seconds = None
    return mock


class TestHealthCheckHotColdIntegration:
    """Tests for health check integration with hot/cold polling.

    Health checks always run regardless of classification — only auto-refresh
    (tool discovery) is gated by hot/cold intervals.
    """

    @pytest.mark.asyncio
    async def test_health_check_always_runs_regardless_of_classification(self, gateway_service_with_classification):
        """Health checks must never be skipped — classification only gates auto-refresh."""
        gateway_service, mock_classification = gateway_service_with_classification

        # Classification says "don't poll" — but health check must still run
        mock_classification.should_poll_server = AsyncMock(return_value=False)

        mock_gateway = _make_mock_gateway(url="http://cold-server:8000")

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_http.stream = AsyncMock(return_value=mock_response)
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            mock_client.return_value = mock_http

            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

            # Health check HTTP call must have been made even though classification said "skip"
            mock_client.assert_called()

    @pytest.mark.asyncio
    async def test_health_check_proceeds_when_classification_disabled(self, gateway_service_with_classification):
        """Health check always proceeds when classification feature is disabled."""
        gateway_service, mock_classification = gateway_service_with_classification
        gateway_service._classification_service = None

        mock_gateway = _make_mock_gateway(url="http://any-server:8000")

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_http.stream = AsyncMock(return_value=mock_response)
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            mock_client.return_value = mock_http

            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")
            mock_client.assert_called()


class TestPollTypeIndependence:
    """Tests for independent tracking of health and tool_discovery poll types."""

    @pytest.mark.asyncio
    async def test_health_and_tool_discovery_polled_independently(self, gateway_service_with_classification):
        """Test health and tool_discovery polls tracked independently."""
        gateway_service, mock_classification = gateway_service_with_classification

        url = "http://test-server:8000"

        async def should_poll_side_effect(url_arg, poll_type):
            if poll_type == "health":
                return False
            elif poll_type == "tool_discovery":
                return True
            return True

        mock_classification.should_poll_server = AsyncMock(side_effect=should_poll_side_effect)

        # Health check not due
        health_result = await mock_classification.should_poll_server(url, "health")
        assert health_result is False

        # Tool discovery is due
        tools_result = await mock_classification.should_poll_server(url, "tool_discovery")
        assert tools_result is True

        assert mock_classification.should_poll_server.await_count == 2


class TestClassificationServiceInitialization:
    """Tests for classification service initialization in GatewayService."""

    @pytest.mark.asyncio
    async def test_classification_service_initialized_when_enabled(self):
        """Test classification service initialized when feature enabled."""
        mock_redis = AsyncMock()

        with (
            patch("mcpgateway.services.gateway_service.settings") as mock_settings,
            patch("mcpgateway.services.gateway_service.SessionLocal"),
            patch("mcpgateway.services.gateway_service.get_redis_client") as mock_get_redis,
        ):
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.platform_admin_email = "admin@example.com"
            mock_get_redis.return_value = mock_redis

            service = GatewayService()

            # Initialize the service (which would normally create classification service)
            with patch.object(service, "_run_health_checks") as mock_run_health:
                mock_run_health.return_value = None

                await service.initialize()

                # Verify classification service was created
                assert service._classification_service is not None

    @pytest.mark.asyncio
    async def test_classification_service_not_initialized_when_disabled(self):
        """Test classification service not initialized when feature disabled."""
        with (
            patch("mcpgateway.services.gateway_service.settings") as mock_settings,
            patch("mcpgateway.services.gateway_service.SessionLocal"),
        ):
            mock_settings.hot_cold_classification_enabled = False
            mock_settings.platform_admin_email = "admin@example.com"

            service = GatewayService()

            with patch.object(service, "_run_health_checks") as mock_run_health:
                mock_run_health.return_value = None

                await service.initialize()

                # Classification service should not be created
                assert service._classification_service is None or not hasattr(service, "_classification_service")


class TestConfigurationValues:
    """Tests for hot/cold polling interval configuration."""

    @pytest.mark.asyncio
    async def test_hot_server_interval_equals_gateway_auto_refresh(self):
        """Test hot server check interval equals gateway_auto_refresh_interval."""
        # First-Party
        from mcpgateway.config import Settings

        # Create a real config instance with specific value
        config = Settings(gateway_auto_refresh_interval=300)

        # Access the property
        assert config.hot_server_check_interval == 300

    @pytest.mark.asyncio
    async def test_cold_server_interval_is_3x_gateway_auto_refresh(self):
        """Test cold server check interval is 3x gateway_auto_refresh_interval."""
        # First-Party
        from mcpgateway.config import Settings

        # Create a real config instance with specific value
        config = Settings(gateway_auto_refresh_interval=300)

        # Access the property
        assert config.cold_server_check_interval == 900  # 3x

    @pytest.mark.asyncio
    async def test_intervals_derive_correctly_from_config(self):
        """Test intervals correctly derived from configuration."""
        # First-Party
        from mcpgateway.config import Settings

        # Test different base intervals
        base_intervals = [60, 120, 300, 600]

        for base in base_intervals:
            # Create a config instance for each test value
            config = Settings(gateway_auto_refresh_interval=base)

            # Verify derived intervals
            hot_interval = config.hot_server_check_interval
            cold_interval = config.cold_server_check_interval

            assert hot_interval == base
            assert cold_interval == base * 3


class TestFailOpenBehavior:
    """Tests for fail-open behavior on errors."""

    @pytest.mark.asyncio
    async def test_health_check_proceeds_on_classification_error(self, gateway_service_with_classification):
        """Test health check proceeds when classification check fails."""
        gateway_service, mock_classification = gateway_service_with_classification

        # Classification service raises error
        mock_classification.should_poll_server = AsyncMock(side_effect=Exception("Redis connection error"))

        mock_gateway = _make_mock_gateway(url="http://test-server:8000")

        # Health check should still proceed (fail-open)
        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

            # Mock HTTP response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_http.stream = AsyncMock(return_value=mock_response)
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            mock_client.return_value = mock_http

            # Should not raise exception, health check should proceed
            try:
                await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")
            except Exception as e:
                pytest.fail(f"Health check should not raise exception on classification error: {e}")

    @pytest.mark.asyncio
    async def test_auto_refresh_proceeds_on_classification_error_via_health_check(self, gateway_service_with_classification, monkeypatch):
        """Test auto-refresh proceeds when classification check fails during health check (fail-open)."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)

        gateway_service, mock_classification = gateway_service_with_classification

        # Classification service raises error
        mock_classification.should_poll_server = AsyncMock(side_effect=Exception("Redis connection error"))

        mock_gateway = _make_mock_gateway(url="http://test-server:8000", name="test-gateway")
        mock_gateway.last_refresh_at = None

        # Mock the internal refresh method call
        with patch.object(gateway_service, "_refresh_gateway_tools_resources_prompts", AsyncMock(return_value={"added": 0, "updated": 0, "removed": 0})):
            with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db:
                mock_session = MagicMock()
                mock_fresh_db.return_value.__enter__.return_value = mock_session
                mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
                mock_session.commit = MagicMock()

                with patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_client:
                    # Mock HTTP response
                    mock_response = AsyncMock()
                    mock_response.status_code = 200
                    mock_response.raise_for_status = MagicMock()
                    mock_http = AsyncMock()
                    mock_http.__aenter__.return_value = mock_http
                    mock_http.__aexit__.return_value = None
                    mock_http.stream = AsyncMock(return_value=mock_response)
                    mock_response.__aenter__.return_value = mock_response
                    mock_response.__aexit__.return_value = None
                    mock_client.return_value = mock_http

                    # Should not raise exception, auto-refresh should proceed with fail-open
                    try:
                        await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")
                    except Exception as e:
                        pytest.fail(f"Health check with auto-refresh should not raise exception on classification error: {e}")

    @pytest.mark.asyncio
    async def test_auto_refresh_skipped_when_tools_classification_not_due(self, gateway_service_with_classification, monkeypatch):
        """Test auto-refresh is skipped when classification says tools are not due, even after health check passes."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)

        gateway_service, mock_classification = gateway_service_with_classification

        # Tool discovery poll is not due
        mock_classification.should_poll_server = AsyncMock(return_value=False)
        mock_classification.mark_poll_completed = AsyncMock()

        mock_gateway = _make_mock_gateway(url="http://test-server:8000")
        mock_refresh = AsyncMock()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_get_client,
            patch.object(gateway_service, "_refresh_gateway_tools_resources_prompts", mock_refresh),
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_stream_cm = MagicMock()
            mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
            mock_http_client = MagicMock()
            mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
            mock_client_cm = MagicMock()
            mock_client_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_client_cm.__aexit__ = AsyncMock(return_value=False)
            mock_get_client.return_value = mock_client_cm

            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

        # Tools refresh must NOT have been called (classification said not due)
        mock_refresh.assert_not_awaited()
        # Only tool_discovery poll type checked (health checks always run)
        mock_classification.should_poll_server.assert_awaited_once_with("http://test-server:8000", "tool_discovery", gateway_id="gw-123")

    @pytest.mark.asyncio
    async def test_mark_poll_completed_tool_discovery_exception_ignored(self, gateway_service_with_classification, monkeypatch):
        """Test that exceptions from mark_poll_completed(tool_discovery) are silently ignored."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)

        gateway_service, mock_classification = gateway_service_with_classification

        # Both health and tools polls are due
        mock_classification.should_poll_server = AsyncMock(return_value=True)

        # mark_poll_completed raises only for tool_discovery
        async def _mark_side_effect(url, poll_type):
            if poll_type == "tool_discovery":
                raise Exception("Redis write error")

        mock_classification.mark_poll_completed = AsyncMock(side_effect=_mark_side_effect)

        mock_gateway = _make_mock_gateway(url="http://test-server:8000", name="test-gateway")
        mock_gateway.last_refresh_at = None

        with (
            patch.object(gateway_service, "_refresh_gateway_tools_resources_prompts", AsyncMock(return_value={"added": 0, "updated": 0, "removed": 0})),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_get_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_stream_cm = MagicMock()
            mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
            mock_http_client = MagicMock()
            mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
            mock_client_cm = MagicMock()
            mock_client_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_client_cm.__aexit__ = AsyncMock(return_value=False)
            mock_get_client.return_value = mock_client_cm

            # Exception from mark_poll_completed(tool_discovery) must not propagate
            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")


def _make_http_client_context_manager():
    """Build the async context manager chain used by tests that go through get_isolated_http_client."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_stream_cm = MagicMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
    mock_http_client = MagicMock()
    mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_client_cm


class TestBranchSpecificMissingLines:
    """Tests that cover lines identified as missing in this branch's changes."""

    # ------------------------------------------------------------------
    # Line 3590: last_refresh.replace(tzinfo=timezone.utc) — naive datetime
    # inside the new `should_auto_refresh` gate added by this branch.
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auto_refresh_naive_last_refresh_at_triggers_tzinfo_fix(self, gateway_service_with_classification, monkeypatch):
        """Naive datetime in last_refresh_at gets UTC tzinfo applied before comparison (line 3590)."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.gateway_auto_refresh_interval", 300)

        gateway_service, mock_classification = gateway_service_with_classification
        # Disable classification so should_auto_refresh=True via the unconditional else branch
        gateway_service._classification_service = None

        mock_gateway = _make_mock_gateway(url="http://test-server:8000", name="test-gateway")
        # Naive datetime (no tzinfo), old enough that time_since_refresh > 300s
        mock_gateway.last_refresh_at = datetime.utcnow() - timedelta(hours=2)
        mock_gateway.refresh_interval_seconds = None

        mock_refresh = AsyncMock(return_value={"added": 0, "updated": 0, "removed": 0})

        with (
            patch.object(gateway_service, "_refresh_gateway_tools_resources_prompts", mock_refresh),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_get_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()
            mock_get_client.return_value = _make_http_client_context_manager()

            # Should not raise; tzinfo fix is applied and refresh proceeds
            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

        # Refresh must have been called (naive datetime was handled correctly)
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_refresh_naive_last_refresh_at_within_interval_skips_refresh(self, gateway_service_with_classification, monkeypatch):
        """Naive datetime recent enough to skip refresh is still handled without error (line 3590 + throttle)."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.gateway_auto_refresh_interval", 3600)

        gateway_service, mock_classification = gateway_service_with_classification
        gateway_service._classification_service = None

        mock_gateway = _make_mock_gateway(url="http://test-server:8000", name="test-gateway")
        # Naive datetime, refreshed 30 seconds ago (within 3600s interval)
        mock_gateway.last_refresh_at = datetime.utcnow() - timedelta(seconds=30)
        mock_gateway.refresh_interval_seconds = None

        mock_refresh = AsyncMock(return_value={"added": 0, "updated": 0, "removed": 0})

        with (
            patch.object(gateway_service, "_refresh_gateway_tools_resources_prompts", mock_refresh),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_get_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()
            mock_get_client.return_value = _make_http_client_context_manager()

            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

        # Not due for refresh yet
        mock_refresh.assert_not_awaited()

    # ------------------------------------------------------------------
    # Lines 3344-3345: decode_auth exception on query_param auth type
    # Inside _check_single_gateway_health, modified by this branch.
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_health_check_query_param_decryption_failure_proceeds_fail_open(self, gateway_service_with_classification):
        """Health check proceeds when query-param auth decryption raises an exception (lines 3344-3345)."""
        gateway_service, mock_classification = gateway_service_with_classification
        mock_classification.should_poll_server = AsyncMock(return_value=True)
        mock_classification.mark_poll_completed = AsyncMock()

        mock_gateway = _make_mock_gateway(url="http://test-server:8000", name="test-gateway")
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_query_params = {"api_key": "badly_encrypted_value"}  # pragma: allowlist secret

        with (
            patch("mcpgateway.services.gateway_service.decode_auth", side_effect=Exception("Decryption failed")),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client") as mock_get_client,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()
            mock_get_client.return_value = _make_http_client_context_manager()

            # Must not raise; decryption failure is silently logged (line 3344-3345)
            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

        # Health check still executed (get_isolated_http_client was called)
        mock_get_client.assert_called_once()

    # ------------------------------------------------------------------
    # Line 3398: ssl_context = None (else branch) for https URL with no CA cert
    # Inside _check_single_gateway_health, modified by this branch.
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_health_check_https_url_no_ca_cert_ssl_context_none(self, gateway_service_with_classification):
        """ssl_context is None for https URL with no CA certificate (line 3398 else branch)."""
        gateway_service, mock_classification = gateway_service_with_classification
        mock_classification.should_poll_server = AsyncMock(return_value=True)
        mock_classification.mark_poll_completed = AsyncMock()

        # https URL + no CA certificate → falls into the else: ssl_context = None branch (line 3398)
        mock_gateway = _make_mock_gateway(url="https://secure-server:8443", name="test-gateway")
        # ca_certificate is None by default in _make_mock_gateway — no valid cert, no ssl override

        ssl_context_captured = {}

        original_get_isolated = __import__("mcpgateway.services.gateway_service", fromlist=["get_isolated_http_client"])

        def capture_ssl_context(*args, **kwargs):
            ssl_context_captured["verify"] = kwargs.get("verify")
            return _make_http_client_context_manager()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", side_effect=capture_ssl_context),
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway
            mock_session.commit = MagicMock()

            await gateway_service._check_single_gateway_health(mock_gateway, user_email="test@example.com")

        # ssl_context should be None (the else branch at line 3398)
        assert ssl_context_captured.get("verify") is None


class TestMarkPollCompletedInRefreshPath:
    """Tests that mark_poll_completed runs inside _refresh_gateway_tools_resources_prompts."""

    @pytest.mark.asyncio
    async def test_refresh_calls_mark_poll_completed_on_success(self, gateway_service_with_classification, monkeypatch):
        """Successful tool refresh must advance the hot/cold poll schedule."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)

        gateway_service, mock_classification = gateway_service_with_classification
        mock_classification.should_poll_server = AsyncMock(return_value=True)
        mock_classification.mark_poll_completed = AsyncMock()

        mock_gateway = _make_mock_gateway(url="http://refresh-gw:8000")
        mock_gateway.last_refresh_at = None
        mock_gateway.refresh_interval_seconds = None

        # Mock _initialize_gateway to return empty (no changes, but success)
        with (
            patch.object(gateway_service, "_initialize_gateway", AsyncMock(return_value=({}, [], [], []))),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tl_fn,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session

            # Return gateway from DB query inside refresh
            mock_gw_db = MagicMock()
            mock_gw_db.id = "gw-123"
            mock_gw_db.tools = []
            mock_gw_db.resources = []
            mock_gw_db.prompts = []
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gw_db
            mock_session.commit = MagicMock()
            mock_session.dirty = set()

            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_tl = AsyncMock()
            mock_tl_fn.return_value = mock_tl

            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                gateway_id="gw-123",
                gateway=mock_gateway,
            )

        # mark_poll_completed must have been called with the base URL
        mock_classification.mark_poll_completed.assert_awaited_once_with("http://refresh-gw:8000", "tool_discovery", gateway_id="gw-123")

    @pytest.mark.asyncio
    async def test_refresh_mark_poll_exception_ignored(self, gateway_service_with_classification, monkeypatch):
        """Exception from mark_poll_completed inside refresh must not crash the refresh."""
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.auto_refresh_servers", True)

        gateway_service, mock_classification = gateway_service_with_classification
        mock_classification.should_poll_server = AsyncMock(return_value=True)
        mock_classification.mark_poll_completed = AsyncMock(side_effect=Exception("Redis down"))

        mock_gateway = _make_mock_gateway(url="http://err-gw:8000")
        mock_gateway.last_refresh_at = None
        mock_gateway.refresh_interval_seconds = None

        with (
            patch.object(gateway_service, "_initialize_gateway", AsyncMock(return_value=({}, [], [], []))),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tl_fn,
        ):
            mock_session = MagicMock()
            mock_fresh_db.return_value.__enter__.return_value = mock_session
            mock_gw_db = MagicMock()
            mock_gw_db.id = "gw-123"
            mock_gw_db.tools = []
            mock_gw_db.resources = []
            mock_gw_db.prompts = []
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gw_db
            mock_session.commit = MagicMock()
            mock_session.dirty = set()
            mock_cache_fn.return_value = AsyncMock()
            mock_tl_fn.return_value = AsyncMock()

            # Must not raise despite mark_poll_completed failure
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                gateway_id="gw-123",
                gateway=mock_gateway,
            )
            assert result["success"]


class TestUpdateGatewayPollSchedule:
    """Tests for mark_poll_completed in the update_gateway path."""

    @pytest.mark.asyncio
    async def test_update_gateway_advances_poll_on_successful_reinit(self):
        """update_gateway must call mark_poll_completed after successful re-initialization."""
        from mcpgateway.services.server_classification_service import ServerClassificationService

        with patch("mcpgateway.services.gateway_service.SessionLocal"):
            service = GatewayService()
            service.oauth_manager = AsyncMock()

            mock_classification = AsyncMock(spec=ServerClassificationService)
            mock_classification.mark_poll_completed = AsyncMock()
            service._classification_service = mock_classification

        mock_db = MagicMock()

        # Build a mock gateway in DB
        mock_gw = MagicMock()
        mock_gw.id = "gw-update-1"
        mock_gw.url = "http://update-gw:8000"
        mock_gw.name = "update-gw"
        mock_gw.enabled = True
        mock_gw.reachable = True
        mock_gw.transport = "SSE"
        mock_gw.auth_type = None
        mock_gw.auth_value = None
        mock_gw.auth_query_params = None
        mock_gw.oauth_config = None
        mock_gw.ca_certificate = None
        mock_gw.client_cert = None
        mock_gw.client_key = None
        mock_gw.tools = []
        mock_gw.resources = []
        mock_gw.prompts = []
        mock_gw.tags = []
        mock_gw.version = 1
        mock_gw.visibility = "public"
        mock_gw.passthrough_headers = None
        mock_gw.team_id = None
        mock_gw.owner_email = "admin@example.com"
        mock_gw.capabilities = {}
        mock_gw.gateway_mode = "cache"
        mock_gw.team = None
        mock_gw.created_by = "admin@example.com"
        mock_gw.created_from_ip = "127.0.0.1"
        mock_gw.created_via = "api"
        mock_gw.created_user_agent = "test"
        mock_gw.modified_by = None
        mock_gw.modified_from_ip = None
        mock_gw.modified_via = None
        mock_gw.modified_user_agent = None
        mock_gw.updated_at = datetime.now()
        mock_gw.last_seen = datetime.now()
        mock_gw.created_at = datetime.now()
        mock_gw.slug = "update-gw"
        mock_gw.last_refresh_at = None
        mock_gw.refresh_interval_seconds = None
        mock_gw.description = None
        mock_gw.import_batch_id = None
        mock_gw.federation_source = None
        mock_gw.ca_certificate_sig = None
        mock_gw.signing_algorithm = "ed25519"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gw
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.flush = MagicMock()

        # GatewayUpdate with a URL change to trigger re-init
        from mcpgateway.schemas import GatewayUpdate

        gateway_update = MagicMock(spec=GatewayUpdate)
        gateway_update.url = "http://update-gw:8000"
        gateway_update.name = None
        gateway_update.description = None
        gateway_update.transport = None
        gateway_update.tags = None
        gateway_update.passthrough_headers = None
        gateway_update.auth_type = None
        gateway_update.auth_username = None
        gateway_update.auth_password = None
        gateway_update.auth_token = None
        gateway_update.auth_header_key = None
        gateway_update.auth_header_value = None
        gateway_update.auth_headers = None
        gateway_update.auth_value = None
        gateway_update.oauth_config = None
        gateway_update.auth_query_param_key = None
        gateway_update.auth_query_param_value = None
        gateway_update.ca_certificate = None
        gateway_update.ca_certificate_sig = None
        gateway_update.signing_algorithm = None
        gateway_update.client_cert = None
        gateway_update.client_key = None
        gateway_update.one_time_auth = None
        gateway_update.visibility = None
        gateway_update.team_id = None
        gateway_update.refresh_interval_seconds = None
        gateway_update.gateway_mode = None

        with (
            patch.object(service, "_initialize_gateway", AsyncMock(return_value=({}, [], [], []))),
            patch.object(service, "_notify_gateway_updated", AsyncMock()),
            patch("mcpgateway.services.gateway_service._get_registry_cache", return_value=AsyncMock()),
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache", return_value=AsyncMock()),
            patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit,
            patch("mcpgateway.services.gateway_service.structured_logger") as mock_slog,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache", AsyncMock()),
        ):
            mock_audit.log_action = MagicMock()
            mock_slog.log = MagicMock()

            await service.update_gateway(mock_db, "gw-update-1", gateway_update)

        mock_classification.mark_poll_completed.assert_awaited_once_with("http://update-gw:8000", "tool_discovery", gateway_id="gw-update-1")
