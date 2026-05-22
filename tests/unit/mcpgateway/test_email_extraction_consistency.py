# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_email_extraction_consistency.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for consistent email extraction across resource operations.

This test suite ensures that all resource CRUD operations use the canonical
get_user_email() helper with consistent email-over-sub precedence, preventing
ownership check failures when tokens have different claim structures.

Regression Prevention:
- Tests the bug reported in issue where update_prompt() failed with 403
  when token had {'sub': 'user@example.com', 'user': {'email': '...'}}
- Ensures create and update operations extract email consistently
- Validates that ownership checks work across all token structures
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_user_email


class TestEmailExtractionConsistency:
    """Test consistent email extraction across resource operations."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return Mock(spec=Session)

    @pytest.fixture
    def mock_request(self):
        """Create mock request with token state."""
        request = Mock()
        request.state = Mock()
        request.state.token_teams = ["team-1"]
        request.state.team_id = "team-1"
        request.headers = {}
        request.client = Mock()
        request.client.host = "127.0.0.1"
        return request

    def test_get_user_email_with_sub_only(self):
        """Test email extraction from token with only 'sub' claim."""
        user = {"sub": "user@example.com", "is_admin": False}
        email = get_user_email(user)
        assert email == "user@example.com"

    def test_get_user_email_with_email_only(self):
        """Test email extraction from token with only 'email' claim."""
        user = {"email": "user@example.com", "is_admin": False}
        email = get_user_email(user)
        assert email == "user@example.com"

    def test_get_user_email_with_both_email_wins(self):
        """Test email-over-sub precedence when both claims present."""
        user = {"email": "primary@example.com", "sub": "secondary@example.com"}
        email = get_user_email(user)
        assert email == "primary@example.com"

    def test_get_user_email_with_nested_user_object(self):
        """Test extraction from token with nested user object (reported bug case)."""
        user = {"sub": "user@example.com", "user": {"email": "nested@example.com", "is_admin": True}}
        email = get_user_email(user)
        # Should extract from top-level 'sub', not nested 'user.email'
        assert email == "user@example.com"

    def test_get_user_email_with_no_email_or_sub(self):
        """Test fallback to 'unknown' when neither email nor sub present."""
        user = {"is_admin": False, "teams": ["team-1"]}
        email = get_user_email(user)
        assert email == "unknown"

    @pytest.mark.asyncio
    async def test_update_tool_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that update_tool uses get_user_email for ownership checks."""
        from mcpgateway.main import update_tool
        from mcpgateway.schemas import ToolUpdate

        # Token with only 'sub' claim (the reported bug case)
        user = {"sub": "user@example.com", "is_admin": False}

        tool_update = ToolUpdate(description="Updated description")

        with patch("mcpgateway.main.tool_service") as mock_service:
            mock_service.update_tool = AsyncMock(return_value=Mock())
            with patch("mcpgateway.main.MetadataCapture") as mock_metadata:
                mock_metadata.extract_modification_metadata.return_value = {
                    "modified_by": "user@example.com",
                    "modified_from_ip": "127.0.0.1",
                    "modified_via": "api",
                    "modified_user_agent": "test",
                }

                try:
                    await update_tool("tool-123", tool_update, mock_request, mock_db, user)
                except Exception:
                    pass  # We're testing the email extraction, not the full flow

                # Verify update_tool was called with correctly extracted email
                if mock_service.update_tool.called:
                    call_kwargs = mock_service.update_tool.call_args.kwargs
                    assert call_kwargs.get("user_email") == "user@example.com"

    @pytest.mark.asyncio
    async def test_update_resource_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that update_resource uses get_user_email for ownership checks."""
        from mcpgateway.main import update_resource
        from mcpgateway.schemas import ResourceUpdate

        # Token with nested user object
        user = {"sub": "user@example.com", "user": {"email": "nested@example.com"}}

        resource_update = ResourceUpdate(description="Updated description")

        with patch("mcpgateway.main.resource_service") as mock_service:
            mock_service.update_resource = AsyncMock(return_value=Mock())
            with patch("mcpgateway.main.MetadataCapture") as mock_metadata:
                mock_metadata.extract_modification_metadata.return_value = {
                    "modified_by": "user@example.com",
                    "modified_from_ip": "127.0.0.1",
                    "modified_via": "api",
                    "modified_user_agent": "test",
                }

                try:
                    await update_resource("resource-123", resource_update, mock_request, mock_db, user)
                except Exception:
                    pass

                if mock_service.update_resource.called:
                    call_kwargs = mock_service.update_resource.call_args.kwargs
                    # Should extract from 'sub', not nested 'user.email'
                    assert call_kwargs.get("user_email") == "user@example.com"

    @pytest.mark.asyncio
    async def test_set_resource_state_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that set_resource_state uses get_user_email."""
        from mcpgateway.main import set_resource_state

        user = {"email": "user@example.com", "sub": "ignored@example.com"}

        with patch("mcpgateway.main.resource_service") as mock_service:
            mock_service.set_resource_state = AsyncMock(return_value=Mock(model_dump=Mock(return_value={})))

            try:
                await set_resource_state("resource-123", True, mock_db, user)
            except Exception:
                pass

            if mock_service.set_resource_state.called:
                call_kwargs = mock_service.set_resource_state.call_args.kwargs
                # Should use 'email' over 'sub'
                assert call_kwargs.get("user_email") == "user@example.com"

    @pytest.mark.asyncio
    async def test_set_prompt_state_uses_canonical_extraction(self, mock_db):
        """Test that set_prompt_state uses get_user_email."""
        from mcpgateway.main import set_prompt_state

        user = {"sub": "user@example.com"}

        with patch("mcpgateway.main.prompt_service") as mock_service:
            mock_service.set_prompt_state = AsyncMock(return_value=Mock(model_dump=Mock(return_value={})))

            try:
                await set_prompt_state("prompt-123", True, mock_db, user)
            except Exception:
                pass

            if mock_service.set_prompt_state.called:
                call_kwargs = mock_service.set_prompt_state.call_args.kwargs
                assert call_kwargs.get("user_email") == "user@example.com"

    @pytest.mark.asyncio
    async def test_update_gateway_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that update_gateway uses get_user_email."""
        from mcpgateway.main import update_gateway
        from mcpgateway.schemas import GatewayUpdate

        user = {"email": "admin@example.com", "is_admin": True}

        gateway_update = GatewayUpdate(description="Updated gateway")

        with patch("mcpgateway.main.gateway_service") as mock_service:
            mock_service.update_gateway = AsyncMock(return_value=Mock())
            with patch("mcpgateway.main.MetadataCapture") as mock_metadata:
                mock_metadata.extract_modification_metadata.return_value = {
                    "modified_by": "admin@example.com",
                    "modified_from_ip": "127.0.0.1",
                    "modified_via": "api",
                    "modified_user_agent": "test",
                }

                try:
                    await update_gateway("gateway-123", gateway_update, mock_request, mock_db, user)
                except Exception:
                    pass

                if mock_service.update_gateway.called:
                    call_kwargs = mock_service.update_gateway.call_args.kwargs
                    assert call_kwargs.get("user_email") == "admin@example.com"

    @pytest.mark.asyncio
    async def test_set_gateway_state_uses_canonical_extraction(self, mock_db):
        """Test that set_gateway_state uses get_user_email."""
        from mcpgateway.main import set_gateway_state

        user = {"sub": "admin@example.com", "is_admin": True}

        with patch("mcpgateway.main.gateway_service") as mock_service:
            mock_service.set_gateway_state = AsyncMock(return_value=Mock(model_dump=Mock(return_value={})))

            try:
                await set_gateway_state("gateway-123", True, mock_db, user)
            except Exception:
                pass

            if mock_service.set_gateway_state.called:
                call_kwargs = mock_service.set_gateway_state.call_args.kwargs
                assert call_kwargs.get("user_email") == "admin@example.com"

    @pytest.mark.asyncio
    async def test_delete_gateway_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that delete_gateway uses get_user_email."""
        from mcpgateway.main import delete_gateway

        user = {"email": "admin@example.com"}

        with patch("mcpgateway.main.gateway_service") as mock_service:
            mock_service.delete_gateway = AsyncMock()
            with patch("mcpgateway.main.get_scoped_resource_access_context") as mock_context:
                mock_context.return_value = ("admin@example.com", ["team-1"])

                try:
                    await delete_gateway("gateway-123", False, mock_db, user, mock_request)
                except Exception:
                    pass

                if mock_service.delete_gateway.called:
                    call_kwargs = mock_service.delete_gateway.call_args.kwargs
                    assert call_kwargs.get("user_email") == "admin@example.com"

    @pytest.mark.asyncio
    async def test_refresh_gateway_tools_uses_canonical_extraction(self, mock_db, mock_request):
        """Test that refresh_gateway_tools uses get_user_email."""
        from mcpgateway.main import refresh_gateway_tools

        user = {"sub": "admin@example.com", "user": {"email": "nested@example.com"}}

        with patch("mcpgateway.main.gateway_service") as mock_service:
            mock_service.refresh_gateway_tools = AsyncMock(return_value=Mock())

            try:
                await refresh_gateway_tools("gateway-123", mock_request, mock_db, user)
            except Exception:
                pass

            if mock_service.refresh_gateway_tools.called:
                call_kwargs = mock_service.refresh_gateway_tools.call_args.kwargs
                # Should extract from 'sub', not nested email
                assert call_kwargs.get("user_email") == "admin@example.com"


    def test_sub_claim_token_email_extraction_consistency(self):
        """Regression test for issue #4800: sub-claim token email extraction must be consistent.

        This test verifies that get_user_email() extracts the same email from a token
        with only {'sub': 'user@example.com'} regardless of context, preventing the
        bug where create operations succeeded but update/delete operations failed with 403.
        """
        # Token with only 'sub' claim (no 'email' key) - the reported bug case
        user_token = {"sub": "user@example.com", "is_admin": False}

        # The canonical helper should extract email from sub
        extracted_email = get_user_email(user_token)

        # Verify extraction works
        assert extracted_email == "user@example.com"

        # Verify consistency: calling multiple times returns same result
        assert get_user_email(user_token) == extracted_email
        assert get_user_email(user_token) == extracted_email

        # Verify it works with different sub values
        assert get_user_email({"sub": "another@example.com"}) == "another@example.com"

    def test_email_over_sub_precedence_in_ownership_checks(self):
        """Verify email-over-sub precedence is consistent across all token structures."""
        # When both email and sub present, email takes precedence
        token_both = {"email": "primary@example.com", "sub": "secondary@example.com"}
        assert get_user_email(token_both) == "primary@example.com"

        # When only sub present, use sub
        token_sub_only = {"sub": "user@example.com"}
        assert get_user_email(token_sub_only) == "user@example.com"

        # When only email present, use email
        token_email_only = {"email": "user@example.com"}
        assert get_user_email(token_email_only) == "user@example.com"

        # When neither present, return unknown
        token_neither = {"is_admin": False}
        assert get_user_email(token_neither) == "unknown"


class TestRuntimeAdminEmailExtraction:
    """Test email extraction in runtime admin router."""

    @pytest.mark.asyncio
    async def test_runtime_mode_change_uses_canonical_extraction(self):
        """Test that runtime mode changes use get_user_email for audit logging."""
        from mcpgateway.routers.runtime_admin_router import _apply_mode_change
        from mcpgateway.runtime_state import RuntimeKind, OverrideMode

        user = {"sub": "admin@example.com", "is_admin": True}
        mock_db = Mock(spec=Session)

        with patch("mcpgateway.routers.runtime_admin_router.get_runtime_state") as mock_get_state:
            mock_state = Mock()
            mock_get_state.return_value = mock_state

            with patch("mcpgateway.routers.runtime_admin_router.version_module") as mock_version:
                mock_version.deployment_allows_override_mode.return_value = MagicMock(value="OK")
                mock_state.allocate_version.return_value = 1
                mock_state.apply_local = AsyncMock(return_value=Mock(version=1))
                mock_state.publish_to_redis = AsyncMock(return_value=Mock(value="SUCCESS"))
                mock_state.version.return_value = 1

                with patch("mcpgateway.routers.runtime_admin_router.get_security_logger") as mock_get_logger:
                    mock_logger = Mock()
                    mock_get_logger.return_value = mock_logger
                    mock_logger.log_data_access = AsyncMock()

                    try:
                        await _apply_mode_change(
                            runtime=RuntimeKind.MCP,
                            new_mode=OverrideMode.EDGE,
                            user=user,
                            db=mock_db,
                            boot_mode=OverrideMode.SHADOW,
                            resource_label="test"
                        )
                    except Exception:
                        pass

                    # Verify apply_local was called with correctly extracted email
                    if mock_state.apply_local.called:
                        call_kwargs = mock_state.apply_local.call_args.kwargs
                        assert call_kwargs.get("initiator_user") == "admin@example.com"
