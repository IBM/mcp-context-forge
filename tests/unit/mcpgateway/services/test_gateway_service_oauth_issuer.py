# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_oauth_issuer.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for keeping OAuth client credentials bound to the issuer that granted them.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# First-Party
from mcpgateway.services.gateway_service import GatewayService


def _gateway(oauth_config):
    return SimpleNamespace(id="gw-1", oauth_config=oauth_config)


def _db(rowcount: int = 0):
    db = MagicMock()
    db.execute.return_value.rowcount = rowcount
    return db


def test_unchanged_issuer_touches_nothing():
    db = _db()
    GatewayService._retire_credentials_for_old_issuer(db, _gateway({"issuer": "https://as.example.com/", "client_id": "c"}), {"issuer": "https://as.example.com", "client_id": "c"})
    db.execute.assert_not_called()


def test_missing_issuer_touches_nothing():
    db = _db()
    GatewayService._retire_credentials_for_old_issuer(db, _gateway({"issuer": "https://new.example.com"}), {"authorization_url": "https://old.example.com/authorize"})
    GatewayService._retire_credentials_for_old_issuer(db, _gateway({"client_id": "c"}), {"issuer": "https://old.example.com"})
    db.execute.assert_not_called()


def test_changed_issuer_retires_registrations_for_other_issuers():
    db = _db(rowcount=1)
    GatewayService._retire_credentials_for_old_issuer(db, _gateway({"issuer": "https://new.example.com"}), {"issuer": "https://old.example.com"})
    db.execute.assert_called_once()
    statement = str(db.execute.call_args[0][0])
    assert "UPDATE registered_oauth_clients" in statement
    assert "is_active" in statement


def test_changed_issuer_with_same_static_client_id_is_flagged():
    db = _db()
    with patch("mcpgateway.services.gateway_service.logger") as logger:
        GatewayService._retire_credentials_for_old_issuer(db, _gateway({"issuer": "https://new.example.com", "client_id": "static"}), {"issuer": "https://old.example.com", "client_id": "static"})
    logger.warning.assert_called_once()
    assert "client_id is unchanged" in logger.warning.call_args[0][0]


def test_changed_issuer_with_new_client_id_is_not_flagged():
    db = _db()
    with patch("mcpgateway.services.gateway_service.logger") as logger:
        GatewayService._retire_credentials_for_old_issuer(db, _gateway({"issuer": "https://new.example.com", "client_id": "fresh"}), {"issuer": "https://old.example.com", "client_id": "static"})
    logger.warning.assert_not_called()
