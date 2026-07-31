# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/auth_context_stack.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Registration helper for the CSRF / password-change-enforcement /
auth-context middleware stack.

Extracted from ``mcpgateway.main`` so the registration order can be
unit-tested against a bare FastAPI app without importing the assembled
application singleton (whose middleware composition depends on the settings
in effect at first import).
"""

# Standard
import logging

# Third-Party
from fastapi import FastAPI

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


def register_auth_context_middleware(app: FastAPI) -> None:
    """Register CSRF, password-change-enforcement, and auth-context middleware.

    Registration order is load-bearing (issue #5739): Starlette executes user
    middleware in reverse registration order, so CSRFMiddleware is registered
    first and AuthContextMiddleware last, meaning AuthContextMiddleware runs
    first and populates ``request.state.user`` before CSRFMiddleware resolves
    its identity. Getting this backwards makes CSRFMiddleware silently fall
    back to resolving identity from the raw JWT ``sub`` claim (EmailUser.id)
    instead of the email admin.py binds CSRF tokens to.

    Args:
        app: The FastAPI application to register the middleware on.
    """
    # Add authentication context middleware if security logging is enabled OR password change enforcement is enabled
    # This middleware extracts user context and logs security events (authentication attempts)
    # Note: SIEM export can also require auth event capture even when DB security logging is off.
    # Note: Password change enforcement also requires user context to be available
    siem_auth_source_enabled = settings.siem_export_enabled and "auth" in {str(item).lower() for item in getattr(settings, "siem_export_event_sources", [])}

    # Add CSRF protection middleware FIRST (runs LAST/innermost due to reverse order)
    # This validates CSRF tokens on state-changing requests to prevent Cross-Site Request Forgery attacks
    # Must be added before AuthContextMiddleware below so it executes AFTER it and request.state.user
    # is available for token validation (adding it later would make it run BEFORE AuthContextMiddleware,
    # leaving request.state.user unset and silently falling back to resolving identity from the raw JWT
    # `sub` claim (EmailUser.id) instead of the email admin.py binds CSRF tokens to).
    if settings.csrf_enabled:
        # First-Party
        from mcpgateway.middleware.csrf_middleware import CSRFMiddleware

        app.add_middleware(CSRFMiddleware)
        logger.info("🛡️  CSRF protection middleware enabled - validating tokens on state-changing requests")
    else:
        logger.info("🛡️  CSRF protection middleware disabled")

    # Add password change enforcement middleware FIRST (runs SECOND due to reverse order)
    # This middleware enforces mandatory password changes for users with password_change_required flag
    # Note: Runs after AuthContextMiddleware (added below) so request.state.user is available
    if settings.password_change_enforcement_enabled:
        # First-Party
        from mcpgateway.middleware.password_change_enforcement import PasswordChangeEnforcementMiddleware

        app.add_middleware(PasswordChangeEnforcementMiddleware)
        logger.info("🔒 Password change enforcement middleware enabled - blocking access for users requiring password change")
    else:
        logger.info("🔒 Password change enforcement middleware disabled")

    # Add authentication context middleware SECOND (runs FIRST due to reverse order)
    # This populates request.state.user for downstream middleware and handlers
    auth_context_required = settings.security_logging_enabled or siem_auth_source_enabled or settings.mcpgateway_admin_api_enabled or settings.password_change_enforcement_enabled
    if auth_context_required:
        # First-Party
        from mcpgateway.middleware.auth_middleware import AuthContextMiddleware

        app.add_middleware(AuthContextMiddleware)
        logger.info("🔐 Authentication context middleware enabled - capturing authentication security events")
    else:
        logger.info("🔐 Security event logging disabled")
