# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_catalog_identity_contracts.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Reverse-proxy catalog identity and public-schema contract tests.
"""

import uuid

from pydantic import ValidationError
import pytest

from mcpgateway.schemas import GatewayCreate
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, REVERSE_PROXY_CATALOG_NAMESPACE, stable_proxy_id
from mcpgateway.services.reverse_proxy_protocol import RegistrationServer


def test_stable_proxy_id_uses_fixed_namespace_and_canonical_identity():
    # Given
    context = AuthenticatedRegistrationContext(owner_email=" Alice@Example.COM ", team_id=None)
    server = RegistrationServer(name=" My Server ")

    # When
    result = stable_proxy_id(context, server)

    # Then
    expected = uuid.uuid5(REVERSE_PROXY_CATALOG_NAMESPACE, "owner=alice@example.com|scope=public|name=my-server").hex
    assert result == expected


def test_stable_proxy_id_varies_by_owner_and_team_scope():
    # Given
    server = RegistrationServer(name="shared-name")
    public_alice = AuthenticatedRegistrationContext(owner_email="alice@example.com", team_id=None)
    public_bob = AuthenticatedRegistrationContext(owner_email="bob@example.com", team_id=None)
    team_alice = AuthenticatedRegistrationContext(owner_email="alice@example.com", team_id="TEAM-A")

    # When
    identities = {stable_proxy_id(public_alice, server), stable_proxy_id(public_bob, server), stable_proxy_id(team_alice, server)}

    # Then
    assert len(identities) == 3


def test_client_authority_fields_do_not_affect_stable_id():
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    baseline = RegistrationServer(name="authority-test")
    attacker = RegistrationServer.model_validate(
        {"name": "authority-test", "id": "client-gateway-id", "owner_email": "attacker@example.com", "team_id": "attacker-team", "visibility": "private"}
    )

    # When / Then
    assert stable_proxy_id(context, baseline) == stable_proxy_id(context, attacker)


def test_public_gateway_create_still_rejects_proxied_transport():
    # Given / When / Then
    with pytest.raises(ValidationError, match="Invalid transport type"):
        GatewayCreate.model_validate({"name": "public-api", "url": "https://example.com/mcp", "transport": "PROXIED"})
