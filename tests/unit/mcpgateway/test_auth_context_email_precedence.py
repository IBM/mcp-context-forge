# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context_email_precedence.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for unified user-email extraction across auth helpers.

This test module verifies that all user-email extraction helpers converge on
the same canonical precedence order (email-over-sub) to ensure forensic accuracy
and consistency across visibility checks and audit logs.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway import admin
from mcpgateway import auth_context


class TestEmailSubPrecedenceConsistency:
    """Test that all email extraction helpers use consistent email-over-sub precedence."""

    def test_conflicting_email_and_sub_resolves_consistently(self):
        """Verify that when both email and sub are present, all helpers choose email."""
        user_dict = {"email": "primary@example.com", "sub": "secondary@example.com"}

        # All three call sites should resolve to the same identity
        auth_context_result = auth_context.get_user_email(user_dict)
        admin_result = admin.get_user_email(user_dict)

        # Create mock request for get_rpc_filter_context
        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state._jwt_verified_payload = None
        mock_request.state.token_teams = []

        rpc_email, _, _ = auth_context.get_rpc_filter_context(mock_request, user_dict)

        # All should resolve to email (primary), not sub (secondary)
        assert auth_context_result == "primary@example.com"
        assert admin_result == "primary@example.com"
        assert rpc_email == "primary@example.com"

        # Verify they all agree
        assert auth_context_result == admin_result == rpc_email

    def test_email_only_resolves_consistently(self):
        """Verify that when only email is present, all helpers use it."""
        user_dict = {"email": "only-email@example.com"}

        auth_context_result = auth_context.get_user_email(user_dict)
        admin_result = admin.get_user_email(user_dict)

        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state._jwt_verified_payload = None
        mock_request.state.token_teams = []

        rpc_email, _, _ = auth_context.get_rpc_filter_context(mock_request, user_dict)

        assert auth_context_result == "only-email@example.com"
        assert admin_result == "only-email@example.com"
        assert rpc_email == "only-email@example.com"

    def test_sub_only_resolves_consistently(self):
        """Verify that when only sub is present, all helpers use it."""
        user_dict = {"sub": "only-sub@example.com"}

        auth_context_result = auth_context.get_user_email(user_dict)
        admin_result = admin.get_user_email(user_dict)

        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state._jwt_verified_payload = None
        mock_request.state.token_teams = []

        rpc_email, _, _ = auth_context.get_rpc_filter_context(mock_request, user_dict)

        assert auth_context_result == "only-sub@example.com"
        assert admin_result == "only-sub@example.com"
        assert rpc_email == "only-sub@example.com"

    def test_no_email_no_sub_resolves_consistently(self):
        """Verify that when neither email nor sub is present, all helpers return 'unknown'."""
        user_dict = {"username": "someuser"}

        auth_context_result = auth_context.get_user_email(user_dict)
        admin_result = admin.get_user_email(user_dict)

        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state._jwt_verified_payload = None
        mock_request.state.token_teams = []

        rpc_email, _, _ = auth_context.get_rpc_filter_context(mock_request, user_dict)

        assert auth_context_result == "unknown"
        assert admin_result == "unknown"
        assert rpc_email is None  # get_rpc_filter_context returns None for "unknown"

    def test_object_with_email_resolves_consistently(self):
        """Verify that object with email attribute is handled consistently."""
        from types import SimpleNamespace

        user_obj = SimpleNamespace(email="object@example.com")

        auth_context_result = auth_context.get_user_email(user_obj)
        admin_result = admin.get_user_email(user_obj)

        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state._jwt_verified_payload = None
        mock_request.state.token_teams = []

        rpc_email, _, _ = auth_context.get_rpc_filter_context(mock_request, user_obj)

        assert auth_context_result == "object@example.com"
        assert admin_result == "object@example.com"
        assert rpc_email == "object@example.com"

    def test_object_with_falsy_email_returns_unknown(self):
        """Verify that object with falsy/empty email falls back to unknown."""
        from types import SimpleNamespace

        user_obj = SimpleNamespace(email="")

        assert auth_context.get_user_email(user_obj) == "unknown"
        assert admin.get_user_email(user_obj) == "unknown"

    def test_falsy_object_with_email_still_resolves(self):
        """Verify that falsy object with valid email attribute still resolves."""

        class FalsyUser:
            """A user class that evaluates to False in boolean context."""

            def __init__(self, email):
                self.email = email

            def __bool__(self):
                return False

        user_obj = FalsyUser("falsy@example.com")
        assert bool(user_obj) is False

        assert auth_context.get_user_email(user_obj) == "falsy@example.com"
        assert admin.get_user_email(user_obj) == "falsy@example.com"


class TestJwtPayloadEmailResolution:
    """Test JWT email extraction for UUID-sub tokens."""

    USER_ID = "11111111-1111-1111-1111-111111111111"

    def test_signed_user_email_wins_over_uuid_sub(self):
        """Signed nested user.email is the common UUID-sub token shape."""
        payload = {"sub": self.USER_ID, "user": {"email": "owner@example.com"}}

        assert auth_context.get_jwt_user_email_from_payload(payload) == "owner@example.com"

    def test_top_level_email_used_when_nested_email_missing(self):
        """Top-level email is accepted before legacy sub fallback."""
        payload = {"sub": self.USER_ID, "email": "top-level@example.com"}

        assert auth_context.get_jwt_user_email_from_payload(payload) == "top-level@example.com"

    def test_legacy_email_sub_is_returned(self):
        """Legacy email-sub tokens continue to resolve without DB lookup."""
        payload = {"sub": "legacy@example.com"}

        assert auth_context.get_jwt_user_email_from_payload(payload) == "legacy@example.com"

    def test_uuid_sub_without_metadata_is_not_returned_as_email(self):
        """A raw UUID subject is never treated as user_email."""
        payload = {"sub": self.USER_ID}

        assert auth_context.get_jwt_user_email_from_payload(payload) is None

    @pytest.mark.asyncio
    async def test_uuid_sub_resolves_with_injected_resolver(self):
        """UUID-sub fallback uses the injected resolver only when needed."""
        calls = []

        async def resolve_user_id(user_id: str) -> str | None:
            calls.append(user_id)
            return "resolved@example.com"

        payload = {"sub": self.USER_ID}

        assert await auth_context.resolve_jwt_user_email_from_payload(payload, uuid_email_resolver=resolve_user_id) == "resolved@example.com"
        assert calls == [self.USER_ID]

    @pytest.mark.asyncio
    async def test_unknown_uuid_sub_resolves_to_none(self):
        """Unknown UUID subjects stay unresolved instead of becoming user_email."""

        async def resolve_user_id(_user_id: str) -> str | None:
            return None

        payload = {"sub": self.USER_ID}

        assert await auth_context.resolve_jwt_user_email_from_payload(payload, uuid_email_resolver=resolve_user_id) is None

    @pytest.mark.asyncio
    async def test_signed_user_email_does_not_call_uuid_resolver(self):
        """Well-formed UUID-sub API tokens avoid a DB lookup."""

        async def resolve_user_id(_user_id: str) -> str | None:
            raise AssertionError("resolver should not be called")

        payload = {"sub": self.USER_ID, "user": {"email": "owner@example.com"}}

        assert await auth_context.resolve_jwt_user_email_from_payload(payload, uuid_email_resolver=resolve_user_id) == "owner@example.com"
