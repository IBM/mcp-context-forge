# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_async_lifecycle.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for GatewayService async lifecycle field handling (Issue #5127).
Tests convert_gateway_to_read() includes all 8 async lifecycle fields.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService


def _make_gateway_with_lifecycle_fields(
    gateway_id: str = "gw-test-123",
    name: str = "test-gateway",
    url: str = "http://test-server:8000",
    status: str = "pending",
    status_message: str = "Connecting to server",
    registration_attempts: int = 3,
    next_retry_at: datetime | None = None,
    last_error: str | None = "Connection timeout",
    lifecycle_claimed_by: str | None = "worker-1",
    lifecycle_claimed_at: datetime | None = None,
    lifecycle_claim_expires_at: datetime | None = None,
) -> MagicMock:
    """Create a mock gateway with all async lifecycle fields."""
    gateway = MagicMock(spec=DbGateway)
    gateway.id = gateway_id
    gateway.name = name
    gateway.url = url
    gateway.enabled = True
    gateway.reachable = True
    gateway.transport = "SSE"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.oauth_config = None
    gateway.ca_certificate = None
    gateway.ca_certificate_sig = None
    gateway.client_cert = None
    gateway.client_key = None
    gateway.auth_query_params = None
    gateway.visibility = "public"
    gateway.last_refresh_at = None
    gateway.refresh_interval_seconds = None
    gateway.team_id = None
    gateway.owner_email = "admin@example.com"
    gateway.capabilities = {}
    gateway.gateway_mode = "cache"
    gateway.team = None
    gateway.created_by = "admin@example.com"
    gateway.created_from_ip = "127.0.0.1"
    gateway.created_via = "api"
    gateway.created_user_agent = "test"
    gateway.modified_by = None
    gateway.modified_from_ip = None
    gateway.modified_via = None
    gateway.modified_user_agent = None
    gateway.updated_at = datetime.now(timezone.utc)
    gateway.last_seen = datetime.now(timezone.utc)
    gateway.created_at = datetime.now(timezone.utc)
    gateway.slug = "test-gateway"
    gateway.description = None
    gateway.import_batch_id = None
    gateway.federation_source = None
    gateway.signing_algorithm = "ed25519"
    gateway.passthrough_headers = None
    gateway.tags = []
    gateway.version = 1

    # Async lifecycle fields
    gateway.status = status
    gateway.status_message = status_message
    gateway.registration_attempts = registration_attempts
    gateway.next_retry_at = next_retry_at
    gateway.last_error = last_error
    gateway.lifecycle_claimed_by = lifecycle_claimed_by
    gateway.lifecycle_claimed_at = lifecycle_claimed_at
    gateway.lifecycle_claim_expires_at = lifecycle_claim_expires_at

    return gateway


class TestConvertGatewayToReadAsyncLifecycle:
    """Tests for convert_gateway_to_read with async lifecycle fields."""

    def test_convert_gateway_includes_all_async_lifecycle_fields(self):
        """Test all 8 async lifecycle fields are present in GatewayRead."""
        gateway = _make_gateway_with_lifecycle_fields(
            status="pending",
            status_message="Connecting to server",
            registration_attempts=3,
            next_retry_at=datetime(2026, 6, 24, 14, 30, 0, tzinfo=timezone.utc),
            last_error="Connection timeout",
            lifecycle_claimed_by="worker-1",
            lifecycle_claimed_at=datetime(2026, 6, 24, 14, 25, 0, tzinfo=timezone.utc),
            lifecycle_claim_expires_at=datetime(2026, 6, 24, 14, 35, 0, tzinfo=timezone.utc),
        )

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        # Verify all async lifecycle fields are present
        assert result.status == "pending"
        assert result.status_message == "Connecting to server"
        assert result.registration_attempts == 3
        assert result.next_retry_at == datetime(2026, 6, 24, 14, 30, 0, tzinfo=timezone.utc)
        assert result.last_error == "Connection timeout"
        assert result.lifecycle_claimed_by == "worker-1"
        assert result.lifecycle_claimed_at == datetime(2026, 6, 24, 14, 25, 0, tzinfo=timezone.utc)
        assert result.lifecycle_claim_expires_at == datetime(2026, 6, 24, 14, 35, 0, tzinfo=timezone.utc)

    def test_convert_gateway_default_values_for_none_fields(self):
        """Test default values when async lifecycle fields are None."""
        gateway = _make_gateway_with_lifecycle_fields(
            status="active",  # Not None, but testing active state
            status_message=None,
            registration_attempts=0,
            next_retry_at=None,
            last_error=None,
            lifecycle_claimed_by=None,
            lifecycle_claimed_at=None,
            lifecycle_claim_expires_at=None,
        )

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        # Verify defaults for None fields
        assert result.status == "active"  # Explicit "active" value
        assert result.status_message is None
        assert result.registration_attempts == 0
        assert result.next_retry_at is None
        assert result.last_error is None
        assert result.lifecycle_claimed_by is None
        assert result.lifecycle_claimed_at is None
        assert result.lifecycle_claim_expires_at is None

    def test_convert_gateway_missing_status_defaults_to_active(self):
        """Test status defaults to 'active' when missing from gateway."""
        gateway = _make_gateway_with_lifecycle_fields()
        # Remove status attribute to test default
        delattr(gateway, "status")
        gateway.__dict__.pop("status", None)

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        # Default status should be "active"
        assert result.status == "active"

    def test_convert_gateway_missing_registration_attempts_defaults_to_zero(self):
        """Test registration_attempts defaults to 0 when missing."""
        gateway = _make_gateway_with_lifecycle_fields()
        delattr(gateway, "registration_attempts")
        gateway.__dict__.pop("registration_attempts", None)

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        # Default attempts should be 0
        assert result.registration_attempts == 0

    def test_convert_gateway_deleting_status(self):
        """Test gateway with status='deleting'."""
        gateway = _make_gateway_with_lifecycle_fields(
            status="deleting",
            status_message="Removing gateway resources",
        )

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        assert result.status == "deleting"
        assert result.status_message == "Removing gateway resources"

    def test_convert_gateway_active_status_with_previous_errors(self):
        """Test gateway that became active after previous errors."""
        gateway = _make_gateway_with_lifecycle_fields(
            status="active",
            status_message=None,
            registration_attempts=5,  # Had previous attempts
            next_retry_at=None,  # No more retries needed
            last_error="Previous: Connection timeout",  # Historical error
            lifecycle_claimed_by=None,  # No longer claimed
        )

        service = GatewayService()
        result = service.convert_gateway_to_read(gateway)

        assert result.status == "active"
        assert result.status_message is None
        assert result.registration_attempts == 5  # Preserved for history
        assert result.next_retry_at is None
        assert result.last_error == "Previous: Connection timeout"
        assert result.lifecycle_claimed_by is None
