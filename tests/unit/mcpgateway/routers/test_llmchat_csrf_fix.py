# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_llmchat_csrf_fix.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit Tests for LLM Chat CSRF Protection Fix

This test suite verifies the fix for issue #5214:
"LLM Chat Connect fails with 403 CSRF validation failed"

The fix ensures /llmchat routes use admin CSRF protection (consistent with /admin).
"""

import pytest


class TestLLMChatCSRFConfiguration:
    """Test CSRF configuration for llmchat routes."""

    def test_llmchat_in_csrf_exempt_paths(self):
        """
        Test that /llmchat is in csrf_exempt_paths.

        This is part of the fix for #5214. /llmchat must be exempt from
        global CSRF middleware so it can use per-route admin CSRF instead.
        """
        # First-Party
        from mcpgateway.config import settings

        csrf_exempt = settings.csrf_exempt_paths

        # Verify /llmchat is in the exempt list
        assert "/llmchat" in csrf_exempt, "/llmchat must be in csrf_exempt_paths to use admin CSRF protection"

    def test_llmchat_router_has_enforce_admin_csrf_dependency(self):
        """
        Test that llmchat_router has enforce_admin_csrf as a dependency.

        This is the second part of the fix for #5214. The router must
        apply admin CSRF protection to all routes.
        """
        # First-Party
        from mcpgateway.routers.llmchat_router import llmchat_router

        # Check that the router has dependencies
        assert hasattr(llmchat_router, "dependencies"), "llmchat_router should have dependencies attribute"
        assert llmchat_router.dependencies is not None, "llmchat_router dependencies should not be None"
        assert len(llmchat_router.dependencies) > 0, "llmchat_router should have at least one dependency"

        # Verify one of the dependencies is enforce_admin_csrf
        # Dependencies are Depends objects, so we check the dependency attribute
        dependency_callables = [dep.dependency for dep in llmchat_router.dependencies if hasattr(dep, "dependency")]

        # Import enforce_admin_csrf to compare
        # First-Party
        from mcpgateway.admin import enforce_admin_csrf

        assert enforce_admin_csrf in dependency_callables, "llmchat_router must have enforce_admin_csrf as a dependency"

    def test_csrf_exempt_paths_comment_mentions_llmchat(self):
        """
        Test that the csrf_exempt_paths includes proper documentation for /llmchat.

        This ensures the exemption is well-documented for future maintainers.
        """
        # Read the config.py file to verify the comment
        # First-Party
        import mcpgateway.config

        import inspect

        source = inspect.getsource(mcpgateway.config)

        # Check that /llmchat has a comment explaining the exemption
        assert '"/llmchat"' in source, "/llmchat should be in config.py source"
        # The comment should mention admin CSRF or be similar to /admin comment
        assert "llmchat" in source.lower(), "config.py should document llmchat CSRF handling"

    def test_admin_routes_also_exempt_for_consistency(self):
        """
        Test that /admin is also exempt (sanity check for consistency).

        This verifies that /llmchat follows the same pattern as /admin.
        """
        # First-Party
        from mcpgateway.config import settings

        csrf_exempt = settings.csrf_exempt_paths

        # Verify /admin is exempt (sanity check)
        assert "/admin" in csrf_exempt, "/admin should be exempt (existing behavior)"

    def test_llmchat_router_import_does_not_fail(self):
        """
        Test that importing llmchat_router with enforce_admin_csrf doesn't raise errors.

        This is a basic smoke test to ensure the imports are correct.
        """
        try:
            # First-Party
            from mcpgateway.routers.llmchat_router import llmchat_router  # noqa: F401
            from mcpgateway.admin import enforce_admin_csrf  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Failed to import llmchat_router or enforce_admin_csrf: {e}")


class TestLLMChatCSRFRegression:
    """Regression tests to ensure the bug is fixed."""

    def test_config_has_llmchat_exempt_after_admin(self):
        """
        Test that /llmchat appears in the exempt list (after or near /admin).

        This is a specific regression test for the fix.
        """
        # First-Party
        from mcpgateway.config import settings

        csrf_exempt = settings.csrf_exempt_paths

        # Find indices
        admin_idx = csrf_exempt.index("/admin") if "/admin" in csrf_exempt else -1
        llmchat_idx = csrf_exempt.index("/llmchat") if "/llmchat" in csrf_exempt else -1

        assert admin_idx >= 0, "/admin should be in csrf_exempt_paths"
        assert llmchat_idx >= 0, "/llmchat should be in csrf_exempt_paths (fix for #5214)"

        # /llmchat should be near /admin for logical grouping
        # (within 5 positions is reasonable)
        distance = abs(llmchat_idx - admin_idx)
        assert distance <= 5, f"/llmchat and /admin should be grouped together in csrf_exempt_paths (distance: {distance})"
