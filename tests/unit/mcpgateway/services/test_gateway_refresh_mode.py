# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_refresh_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for per-gateway refresh_mode (issue #7017).
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate
from mcpgateway.services.gateway_service import GatewayService, auto_refresh_enabled_for_gateway


@pytest.mark.parametrize(
    ("refresh_mode", "global_auto_refresh", "expected"),
    [
        (None, False, False),
        (None, True, True),
        ("", False, False),
        ("", True, True),
        ("   ", True, True),
        ("off", False, False),
        ("off", True, False),
        ("OFF", True, False),
        ("auto", False, True),
        ("auto", True, True),
        ("AUTO", False, True),
        ("quarantine", False, True),
        ("quarantine", True, True),
        ("QUARANTINE", False, True),
        ("unknown", False, False),
        ("unknown", True, True),
        (123, False, False),
        (123, True, True),
    ],
)
def test_auto_refresh_enabled_for_gateway(refresh_mode, global_auto_refresh, expected):
    """The per-gateway mode overrides AUTO_REFRESH_SERVERS for off, auto, and quarantine."""
    assert auto_refresh_enabled_for_gateway(refresh_mode, global_auto_refresh) is expected


def test_auto_refresh_enabled_for_gateway_treats_magicmock_as_unset():
    """MagicMock gateways without an explicit mode fall back to the global setting."""
    assert auto_refresh_enabled_for_gateway(MagicMock(), False) is False
    assert auto_refresh_enabled_for_gateway(MagicMock(), True) is True


@pytest.mark.parametrize("mode", ["off", "auto", "quarantine", "OFF", " Auto ", None, "", "  "])
def test_gateway_schemas_accept_refresh_mode(mode):
    """Create, update, and read schemas accept supported modes and normalize blanks to None."""
    expected = None if mode is None or (isinstance(mode, str) and not mode.strip()) else mode.strip().lower()
    created = GatewayCreate(name="gw", url="https://example.com/mcp", refresh_mode=mode)
    updated = GatewayUpdate(refresh_mode=mode)
    read = GatewayRead(name="gw", url="https://example.com/mcp", refresh_mode=mode, enabled=True, reachable=True, slug="gw")
    assert created.refresh_mode == expected
    assert updated.refresh_mode == expected
    assert read.refresh_mode == expected


def test_gateway_schemas_reject_unknown_refresh_mode():
    """An unknown refresh_mode is rejected."""
    with pytest.raises(ValidationError):
        GatewayCreate(name="gw", url="https://example.com/mcp", refresh_mode="manual")
    with pytest.raises(ValidationError):
        GatewayUpdate(refresh_mode="manual")


def test_gateway_update_can_clear_refresh_mode():
    """An explicit null refresh_mode is present in model_fields_set so it can clear a stored value."""
    update = GatewayUpdate(refresh_mode=None)
    assert "refresh_mode" in update.model_fields_set
    assert update.refresh_mode is None


@pytest.fixture
def gateway_service():
    """A GatewayService with no real HTTP client."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_db_session():
    """A session that can be used as a context manager."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    return session


def _gateway(refresh_mode=None):
    """A gateway fixture for the health-check auto-refresh path."""
    gw = MagicMock(spec=DbGateway)
    gw.id = "gw-refresh-mode-1"
    gw.name = "Refresh Mode Gateway"
    gw.url = "http://health.test"
    gw.enabled = True
    gw.auth_type = None
    gw.last_refresh_at = datetime.now(timezone.utc) - timedelta(hours=1)
    gw.refresh_interval_seconds = 300
    gw.refresh_mode = refresh_mode
    gw.ca_certificate = None
    gw.ca_certificate_sig = None
    return gw


def _execute_result(scalar):
    """A SQLAlchemy Result stand-in for Session.execute."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = []
    result.scalars.return_value = scalars_proxy
    result.rowcount = 0
    return result


async def _run_health_check(gateway_service, mock_db_session, gateway, auto_refresh_servers):
    """Run a successful health check and return the refresh mock."""
    gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock()
    gateway_service.set_gateway_state = AsyncMock()
    lock = MagicMock()
    lock.locked.return_value = False
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)
    gateway_service._get_refresh_lock = MagicMock(return_value=lock)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get.return_value = MagicMock(status_code=200)

    with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
        mock_settings.auto_refresh_servers = auto_refresh_servers
        mock_settings.gateway_auto_refresh_interval = 300
        mock_settings.enable_ed25519_signing = False
        mock_settings.httpx_admin_read_timeout = 5.0

        with patch("mcpgateway.services.http_client_service.get_isolated_http_client", return_value=mock_client):
            with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_db_session):
                mock_db_session.execute.return_value = _execute_result(gateway)
                await gateway_service._check_single_gateway_health(gateway)

    return gateway_service._refresh_gateway_tools_resources_prompts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refresh_mode", "auto_refresh_servers", "should_refresh"),
    [
        (None, False, False),
        (None, True, True),
        ("off", False, False),
        ("off", True, False),
        ("auto", False, True),
        ("auto", True, True),
        ("quarantine", False, True),
        ("quarantine", True, True),
    ],
)
async def test_health_check_honors_refresh_mode(gateway_service, mock_db_session, refresh_mode, auto_refresh_servers, should_refresh):
    """Scheduled auto-refresh follows refresh_mode, including when the global setting is off."""
    gateway = _gateway(refresh_mode)
    refresh = await _run_health_check(gateway_service, mock_db_session, gateway, auto_refresh_servers)
    if should_refresh:
        refresh.assert_awaited_once()
        _args, kwargs = refresh.call_args
        assert kwargs["created_via"] == "health_check"
    else:
        refresh.assert_not_called()
