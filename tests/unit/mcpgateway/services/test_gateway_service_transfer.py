# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_transfer.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for GatewayService.transfer_gateway_ownership.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from mcpgateway.services.gateway_service import GatewayNotFoundError, GatewayService


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def service():
    return GatewayService()


def _scalar_result(value):
    """Helper: mock db.execute() returning scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(items):
    """Helper: mock db.execute() returning scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


@pytest.mark.asyncio
async def test_transfer_target_user_not_found(service, mock_db):
    mock_db.execute.return_value = _scalar_result(None)

    with pytest.raises(ValueError, match="not found or inactive"):
        await service.transfer_gateway_ownership(
            mock_db, "gw-1", "nobody@example.com", "actor@example.com"
        )


@pytest.mark.asyncio
async def test_transfer_gateway_not_found(service, mock_db):
    mock_db.execute.return_value = _scalar_result(MagicMock())  # user found

    with patch(
        "mcpgateway.services.gateway_service.get_for_update", return_value=None
    ):
        with pytest.raises(GatewayNotFoundError, match="not found"):
            await service.transfer_gateway_ownership(
                mock_db, "gw-missing", "target@example.com", "actor@example.com"
            )


@pytest.mark.asyncio
async def test_transfer_team_gateway_target_not_member(service, mock_db):
    gateway = MagicMock()
    gateway.visibility = "team"
    gateway.team_id = "team-1"
    gateway.owner_email = "old@example.com"

    user = MagicMock()

    # First call: user lookup (scalar_one_or_none → user)
    # Second call: team membership check (scalar_one_or_none → None)
    mock_db.execute.side_effect = [
        _scalar_result(user),
        _scalar_result(None),
    ]

    with patch(
        "mcpgateway.services.gateway_service.get_for_update", return_value=gateway
    ):
        with pytest.raises(ValueError, match="not an active member"):
            await service.transfer_gateway_ownership(
                mock_db, "gw-1", "target@example.com", "actor@example.com"
            )


@pytest.mark.asyncio
async def test_transfer_with_explicit_target_team_not_member(service, mock_db):
    gateway = MagicMock()
    gateway.visibility = "public"
    gateway.team_id = None
    gateway.owner_email = "old@example.com"

    user = MagicMock()

    # First call: user lookup → user found
    # Second call: target_team_id membership check → None (not a member)
    mock_db.execute.side_effect = [
        _scalar_result(user),
        _scalar_result(None),
    ]

    with patch(
        "mcpgateway.services.gateway_service.get_for_update", return_value=gateway
    ):
        with pytest.raises(ValueError, match="not an active member of target team"):
            await service.transfer_gateway_ownership(
                mock_db,
                "gw-1",
                "target@example.com",
                "actor@example.com",
                target_team_id="new-team",
            )


@pytest.mark.asyncio
async def test_transfer_success_public_gateway(service, mock_db):
    gateway = MagicMock()
    gateway.visibility = "public"
    gateway.team_id = None
    gateway.owner_email = "old@example.com"
    gateway.id = "gw-1"

    user = MagicMock()
    expected_read = MagicMock()

    # user lookup, then tools/resources/prompts queries (empty)
    mock_db.execute.side_effect = [
        _scalar_result(user),
        _scalars_result([]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    with (
        patch(
            "mcpgateway.services.gateway_service.get_for_update",
            return_value=gateway,
        ),
        patch(
            "mcpgateway.services.gateway_service.get_audit_trail_service"
        ) as mock_audit_fn,
        patch.object(service, "convert_gateway_to_read", return_value=expected_read),
    ):
        mock_audit_fn.return_value = MagicMock()
        result = await service.transfer_gateway_ownership(
            mock_db, "gw-1", "target@example.com", "actor@example.com"
        )

    assert gateway.owner_email == "target@example.com"
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(gateway)
    assert result is expected_read


@pytest.mark.asyncio
async def test_transfer_updates_linked_entities_and_team(service, mock_db):
    gateway = MagicMock()
    gateway.visibility = "public"
    gateway.team_id = None
    gateway.owner_email = "old@example.com"
    gateway.id = "gw-1"

    user = MagicMock()
    tool = MagicMock()
    resource = MagicMock()
    prompt = MagicMock()
    member = MagicMock()  # membership check passes

    # user lookup, target_team_id membership, tools, resources, prompts
    mock_db.execute.side_effect = [
        _scalar_result(user),
        _scalar_result(member),
        _scalars_result([tool]),
        _scalars_result([resource]),
        _scalars_result([prompt]),
    ]

    with (
        patch(
            "mcpgateway.services.gateway_service.get_for_update",
            return_value=gateway,
        ),
        patch(
            "mcpgateway.services.gateway_service.get_audit_trail_service"
        ) as mock_audit_fn,
        patch.object(service, "convert_gateway_to_read", return_value=MagicMock()),
    ):
        mock_audit_fn.return_value = MagicMock()
        await service.transfer_gateway_ownership(
            mock_db,
            "gw-1",
            "target@example.com",
            "actor@example.com",
            target_team_id="new-team",
        )

    assert gateway.owner_email == "target@example.com"
    assert gateway.team_id == "new-team"
    assert tool.owner_email == "target@example.com"
    assert tool.team_id == "new-team"
    assert resource.owner_email == "target@example.com"
    assert resource.team_id == "new-team"
    assert prompt.owner_email == "target@example.com"
    assert prompt.team_id == "new-team"


@pytest.mark.asyncio
async def test_transfer_team_gateway_with_explicit_target_team_checks_membership_once(service, mock_db):
    """A team gateway with an explicit target team performs one membership lookup."""
    gateway = MagicMock()
    gateway.visibility = "team"
    gateway.team_id = "old-team"
    gateway.owner_email = "old@example.com"
    gateway.id = "gw-team"

    mock_db.execute.side_effect = [
        _scalar_result(MagicMock()),  # target user
        _scalar_result(MagicMock()),  # target team membership
        _scalars_result([]),  # tools
        _scalars_result([]),  # resources
        _scalars_result([]),  # prompts
    ]

    with (
        patch("mcpgateway.services.gateway_service.get_for_update", return_value=gateway),
        patch("mcpgateway.services.gateway_service.get_audit_trail_service") as mock_audit_fn,
        patch.object(service, "convert_gateway_to_read", return_value=MagicMock()),
    ):
        mock_audit_fn.return_value = MagicMock()
        await service.transfer_gateway_ownership(
            mock_db,
            "gw-team",
            "target@example.com",
            "actor@example.com",
            target_team_id="new-team",
        )

    assert gateway.team_id == "new-team"
    assert mock_db.execute.call_count == 5

@pytest.mark.asyncio
async def test_transfer_private_gateway_to_team_coerces_visibility(service, mock_db):
    """Private gateway+linked entities become team-visible when transferred to a team."""
    gateway = MagicMock()
    gateway.visibility = "private"
    gateway.team_id = None
    gateway.owner_email = "old@example.com"
    gateway.id = "gw-priv"

    tool = MagicMock()
    tool.visibility = "private"
    resource = MagicMock()
    resource.visibility = "private"
    prompt = MagicMock()
    prompt.visibility = "private"
    user = MagicMock()
    member = MagicMock()

    mock_db.execute.side_effect = [
        _scalar_result(user),
        _scalar_result(member),
        _scalars_result([tool]),
        _scalars_result([resource]),
        _scalars_result([prompt]),
    ]

    with (
        patch("mcpgateway.services.gateway_service.get_for_update", return_value=gateway),
        patch("mcpgateway.services.gateway_service.get_audit_trail_service") as mock_audit_fn,
        patch.object(service, "convert_gateway_to_read", return_value=MagicMock()),
    ):
        mock_audit_fn.return_value = MagicMock()
        await service.transfer_gateway_ownership(
            mock_db, "gw-priv", "target@example.com", "actor@example.com", target_team_id="new-team"
        )

    assert gateway.visibility == "team"
    assert tool.visibility == "team"
    assert resource.visibility == "team"
    assert prompt.visibility == "team"


@pytest.mark.asyncio
async def test_transfer_scoped_token_cannot_mutate_gateway_outside_scope(service, mock_db):
    """Scoped administrators cannot transfer gateways outside their token teams."""
    gateway = MagicMock()
    gateway.visibility = "public"
    gateway.team_id = "foreign-team"
    gateway.owner_email = "old@example.com"

    mock_db.execute.return_value = _scalar_result(MagicMock())  # target user found

    with patch("mcpgateway.services.gateway_service.get_for_update", return_value=gateway):
        with pytest.raises(ValueError, match="outside.*scope"):
            await service.transfer_gateway_ownership(
                mock_db,
                "gw-1",
                "target@example.com",
                "actor@example.com",
                token_teams=["allowed-team"],
            )

    mock_db.commit.assert_not_called()
