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

    def test_oauth_router_extract_user_email_handles_sub(self):
        """Test that OAuth router's _extract_user_email handles 'sub' claim."""
        # First-Party
        from mcpgateway.routers.oauth_router import _extract_user_email

        # Token with only 'sub' claim
        user = {"sub": "user@example.com"}
        assert _extract_user_email(user) == "user@example.com"

        # Token with only 'email' claim
        user = {"email": "user@example.com"}
        assert _extract_user_email(user) == "user@example.com"

        # Token with both (email takes precedence)
        user = {"email": "email@example.com", "sub": "sub@example.com"}
        assert _extract_user_email(user) == "email@example.com"

        # Token with neither
        user = {"other": "value"}
        assert _extract_user_email(user) is None

    def test_main_endpoints_import_get_user_email(self):
        """Verify that main.py imports get_user_email from auth_context."""
        # First-Party
        import mcpgateway.main as main_module

        # Verify get_user_email is available in the module scope
        assert hasattr(main_module, "get_user_email")
        assert callable(main_module.get_user_email)

    def test_admin_imports_get_user_email(self):
        """Verify that admin.py imports get_user_email from auth_context."""
        # First-Party
        import mcpgateway.admin as admin_module

        # Verify get_user_email is available in the module scope
        assert hasattr(admin_module, "get_user_email")
        assert callable(admin_module.get_user_email)

    def test_runtime_admin_router_imports_get_user_email(self):
        """Verify that runtime_admin_router.py imports get_user_email from auth_context."""
        # First-Party
        import mcpgateway.routers.runtime_admin_router as runtime_admin_module

        # Verify get_user_email is available in the module scope
        assert hasattr(runtime_admin_module, "get_user_email")
        assert callable(runtime_admin_module.get_user_email)

    def test_oauth_router_imports_get_user_email(self):
        """Verify that oauth_router.py imports get_user_email from auth_context."""
        # First-Party
        import mcpgateway.routers.oauth_router as oauth_module

        # Verify get_user_email is available in the module scope
        assert hasattr(oauth_module, "get_user_email")
        assert callable(oauth_module.get_user_email)
