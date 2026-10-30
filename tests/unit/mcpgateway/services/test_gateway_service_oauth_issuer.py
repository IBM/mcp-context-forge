# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_oauth_issuer.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for flagging OAuth client credentials carried across an issuer change.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import RegisteredOAuthClient
from mcpgateway.services.dcr_service import DcrService
from mcpgateway.services.gateway_service import GatewayService


def _gateway(oauth_config):
    return SimpleNamespace(id="gw-1", oauth_config=oauth_config)


def _flag(gateway, original):
    with patch("mcpgateway.services.gateway_service.logger") as logger, patch("mcpgateway.services.gateway_service.get_security_logger") as security:
        GatewayService._flag_credentials_kept_across_issuer_change(gateway, original, "admin@example.com")
    return logger, security


def test_unchanged_issuer_is_silent():
    logger, security = _flag(_gateway({"issuer": "https://as.example.com/", "client_id": "c"}), {"issuer": "https://as.example.com", "client_id": "c"})
    logger.warning.assert_not_called()
    security.assert_not_called()


def test_issuer_added_or_removed_is_silent():
    logger, _ = _flag(_gateway({"issuer": "https://new.example.com", "client_id": "c"}), {"authorization_url": "https://old.example.com/authorize", "client_id": "c"})
    logger.warning.assert_not_called()
    logger, _ = _flag(_gateway({"client_id": "c"}), {"issuer": "https://old.example.com", "client_id": "c"})
    logger.warning.assert_not_called()


def test_changed_issuer_with_new_client_id_is_silent():
    logger, security = _flag(_gateway({"issuer": "https://new.example.com", "client_id": "fresh"}), {"issuer": "https://old.example.com", "client_id": "static"})
    logger.warning.assert_not_called()
    security.assert_not_called()


def test_changed_issuer_with_same_static_client_id_is_flagged():
    logger, security = _flag(_gateway({"issuer": "https://new.example.com", "client_id": "static"}), {"issuer": "https://old.example.com", "client_id": "static"})
    logger.warning.assert_called_once()
    assert "client_id is unchanged" in logger.warning.call_args[0][0]
    event = security.return_value.log_suspicious_activity.call_args[1]
    assert event["activity_type"] == "oauth_client_id_kept_across_issuer_change"
    assert event["user_email"] == "admin@example.com"
    assert event["threat_indicators"] == {"gateway_id": "gw-1", "old_issuer": "https://old.example.com", "new_issuer": "https://new.example.com"}


def test_security_event_failure_does_not_break_the_update():
    with patch("mcpgateway.services.gateway_service.get_security_logger", side_effect=RuntimeError("down")):
        GatewayService._flag_credentials_kept_across_issuer_change(_gateway({"issuer": "https://new.example.com", "client_id": "static"}), {"issuer": "https://old.example.com", "client_id": "static"}, None)


@pytest.mark.asyncio
async def test_registered_clients_survive_issuer_round_trip(test_db):
    """Issuer A -> B -> A keeps the A registration usable: nothing is deactivated or duplicated."""
    gateway = DbGateway(id="gw-rt", name="rt", slug="rt", url="https://mcp.example.com", description="", capabilities={}, oauth_config={"issuer": "https://a.example.com", "grant_type": "authorization_code"})
    test_db.add(gateway)
    test_db.add(
        RegisteredOAuthClient(
            gateway_id="gw-rt",
            issuer="https://a.example.com",
            client_id="client-a",
            redirect_uris='["https://gateway.example.com/oauth/callback"]',
            grant_types='["authorization_code"]',
            created_at=datetime.now(timezone.utc),
            is_active=True,
        )
    )
    test_db.commit()

    original = dict(gateway.oauth_config)
    gateway.oauth_config = {"issuer": "https://b.example.com", "grant_type": "authorization_code"}
    GatewayService._flag_credentials_kept_across_issuer_change(gateway, original, None)
    gateway.oauth_config = {"issuer": "https://a.example.com", "grant_type": "authorization_code"}
    GatewayService._flag_credentials_kept_across_issuer_change(gateway, {"issuer": "https://b.example.com"}, None)
    test_db.commit()

    found = await DcrService().get_or_register_client("gw-rt", "rt", "https://a.example.com", "https://gateway.example.com/oauth/callback", ["mcp:read"], test_db)
    assert found.client_id == "client-a"
    assert found.is_active is True
