# -*- coding: utf-8 -*-
"""Location: ./tests/utils/rbac_mocks.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

RBAC Mocking Utilities for Tests.

This module provides comprehensive mocking utilities for Role-Based Access Control (RBAC)
functionality in tests. It allows tests to bypass permission checks while maintaining
the RBAC function signatures and behavior.

The utilities provided here create mock users with admin privileges and mock permission
services that always grant access, ensuring tests can execute without authentication
barriers while preserving the ability to test RBAC functionality when needed.
"""

# Standard
from typing import Dict, Optional
from unittest.mock import AsyncMock, MagicMock

# Third-Party


def create_mock_user_context(
    email: str = "test@example.com",
    full_name: str = "Test User",
    is_admin: bool = True,
    ip_address: str = "127.0.0.1",
    user_agent: str = "test-client",
    auth_method: str = "jwt",
) -> Dict:
    """Create a mock user context for RBAC testing.

    Args:
        email: User email address
        full_name: User's full name
        is_admin: Whether user has admin privileges
        ip_address: User's IP address
        user_agent: User agent string
        auth_method: Authentication method for interactive-session gating

    Returns:
        Dict: Mock user context suitable for RBAC functions
    """
    return {
        "email": email,
        "full_name": full_name,
        "is_admin": is_admin,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "auth_method": auth_method,
        "db": MagicMock(),  # Mock database session
    }


def create_mock_email_user(
    email: str = "test@example.com",
    full_name: str = "Test User",
    is_admin: bool = True,
    is_active: bool = True,
):
    """Create a mock EmailUser instance for authentication.

    Args:
        email: User email address
        full_name: User's full name
        is_admin: Whether user has admin privileges
        is_active: Whether user account is active

    Returns:
        MagicMock: Mock EmailUser instance
    """
    mock_user = MagicMock()
    mock_user.email = email
    mock_user.full_name = full_name
    mock_user.is_admin = is_admin
    mock_user.is_active = is_active
    return mock_user


class MockPermissionService:
    """Mock permission service that always grants permissions.

    This service can be configured to either always grant access (default)
    or to use specific permission rules for testing permission logic.
    """

    def __init__(self, always_grant: bool = True, custom_permissions: Optional[Dict[str, bool]] = None):
        """Initialize the mock permission service.

        Args:
            always_grant: If True, all permission checks return True
            custom_permissions: Dict mapping permission strings to boolean results
        """
        self.always_grant = always_grant
        self.custom_permissions = custom_permissions or {}

    async def check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        team_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """Mock permission check that returns configured result.

        Args:
            user_email: User email
            permission: Permission to check
            resource_type: Optional resource type
            resource_id: Optional resource ID
            team_id: Optional team context
            ip_address: Optional IP address
            user_agent: Optional user agent

        Returns:
            bool: Permission result
        """
        if self.always_grant:
            return True
        return self.custom_permissions.get(permission, False)

    async def check_admin_permission(self, user_email: str) -> bool:
        """Mock admin permission check.

        Args:
            user_email: User email

        Returns:
            bool: Admin permission result
        """
        return self.always_grant or self.custom_permissions.get("admin", True)


async def mock_get_current_user_with_permissions(*args, **kwargs) -> Dict:
    """Mock implementation of get_current_user_with_permissions.

    This function returns a mock user context that will pass all RBAC checks.
    Using *args, **kwargs to match any signature.

    Returns:
        Dict: Mock user context
    """
    return create_mock_user_context()


async def mock_get_current_user(credentials=None, db=None):
    """Mock implementation of get_current_user.

    Args:
        credentials: HTTP authorization credentials (ignored)
        db: Database session (ignored)

    Returns:
        MagicMock: Mock EmailUser instance
    """
    return create_mock_email_user()


def mock_get_permission_service(db=None) -> MockPermissionService:
    """Mock implementation of get_permission_service.

    Args:
        db: Database session (ignored)

    Returns:
        MockPermissionService: Mock permission service instance
    """
    return MockPermissionService(always_grant=True)


def mock_get_db():
    """Mock database session generator.

    Returns:
        MagicMock: Mock database session
    """
    return MagicMock()


# Create async mock versions for functions that need them
mock_get_current_user_async = AsyncMock(side_effect=mock_get_current_user)
mock_get_current_user_with_permissions_async = AsyncMock(side_effect=mock_get_current_user_with_permissions)
mock_get_permission_service_async = AsyncMock(side_effect=mock_get_permission_service)


def create_rbac_dependency_overrides() -> Dict:
    """Create a dictionary of dependency overrides for RBAC functions.

    This function returns a dictionary that can be used with FastAPI's
    dependency_overrides to replace RBAC dependencies with mocks.

    Returns:
        Dict: Dictionary mapping dependencies to mock implementations
    """
    # Import here to avoid circular imports
    # First-Party
    from mcpgateway.auth import get_current_user, get_db
    from mcpgateway.middleware.rbac import (
        get_current_user_with_permissions,
        get_permission_service,
    )

    return {
        get_current_user_with_permissions: mock_get_current_user_with_permissions,
        get_current_user: mock_get_current_user,
        get_permission_service: mock_get_permission_service,
        get_db: mock_get_db,
    }


class RBACMockManager:
    """Context manager for setting up and tearing down RBAC mocks.

    This manager handles the setup and cleanup of RBAC dependency overrides,
    making it easy to use in tests.

    Example:
        async def test_protected_endpoint(client):
            with RBACMockManager() as mock_manager:
                response = await client.get("/protected-endpoint")
                assert response.status_code == 200
    """

    def __init__(self, app=None, custom_user: Optional[Dict] = None):
        """Initialize the RBAC mock manager.

        Args:
            app: FastAPI application instance
            custom_user: Custom user context to use instead of default
        """
        self.app = app
        self.custom_user = custom_user
        self.original_overrides = {}
        self.permission_service = MockPermissionService()

    def __enter__(self):
        """Enter the context and set up mocks."""
        if self.app:
            # Store original overrides
            self.original_overrides = dict(self.app.dependency_overrides)

            # Set up new overrides
            overrides = create_rbac_dependency_overrides()

            # If custom user provided, create a custom mock function
            if self.custom_user:

                async def custom_user_mock(*args, **kwargs):
                    return self.custom_user

                overrides[get_current_user_with_permissions] = custom_user_mock

            self.app.dependency_overrides.update(overrides)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and restore original dependencies."""
        if self.app:
            # Restore original overrides
            self.app.dependency_overrides.clear()
            self.app.dependency_overrides.update(self.original_overrides)


def mock_require_permission_decorator(permission: str, resource_type: Optional[str] = None):
    """Mock version of the require_permission decorator that always allows access.

    This decorator bypasses all permission checks and simply executes the
    decorated function without any RBAC validation.

    Args:
        permission: Required permission (ignored in mock)
        resource_type: Optional resource type (ignored in mock)

    Returns:
        Callable: A decorator that doesn't perform any permission checks
    """

    def decorator(func):
        # Return the function unchanged - no permission checking
        # Don't wrap the function at all to preserve the original signature
        return func

    return decorator


def mock_require_admin_permission():
    """Mock version of require_admin_permission that always allows access.

    Returns:
        Callable: A decorator that doesn't perform any permission checks
    """

    def decorator(func):
        # Return the function unchanged - no admin permission checking
        return func

    return decorator


def mock_require_any_permission(permissions, resource_type: Optional[str] = None):
    """Mock version of require_any_permission that always allows access.

    Args:
        permissions: List of permissions (ignored in mock)
        resource_type: Optional resource type (ignored in mock)

    Returns:
        Callable: A decorator that doesn't perform any permission checks
    """

    def decorator(func):
        # Return the function unchanged - no permission checking
        return func

    return decorator


def setup_rbac_mocks_for_app(app, custom_user_context: Optional[Dict] = None):
    """Set up RBAC mocks for a FastAPI application.

    This function configures dependency overrides to mock all RBAC-related
    dependencies, allowing tests to run without authentication barriers.
    It also patches the RBAC decorators to bypass permission checks.

    Args:
        app: FastAPI application instance
        custom_user_context: Optional custom user context to use
    """
    # Set up dependency overrides
    overrides = create_rbac_dependency_overrides()

    # If custom user context provided, override the user context function
    if custom_user_context:

        async def custom_user_mock(*args, **kwargs):
            print(f"DEBUG: custom_user_mock called with args={args}, kwargs={kwargs}")
            return custom_user_context

        # First-Party
        from mcpgateway.middleware.rbac import get_current_user_with_permissions

        overrides[get_current_user_with_permissions] = custom_user_mock

    app.dependency_overrides.update(overrides)


def patch_rbac_decorators():
    """Patch RBAC decorators at the module level to bypass permission checks.

    This function should be called before importing modules that use RBAC decorators.

    Returns:
        Dict: Original functions for restoration later
    """
    # First-Party
    import mcpgateway.middleware.rbac as rbac_module

    # Store original functions
    originals = {
        "require_permission": rbac_module.require_permission,
        "require_admin_permission": rbac_module.require_admin_permission,
        "require_any_permission": rbac_module.require_any_permission,
    }

    # Replace with mock versions
    rbac_module.require_permission = mock_require_permission_decorator
    rbac_module.require_admin_permission = mock_require_admin_permission
    rbac_module.require_any_permission = mock_require_any_permission

    return originals


def restore_rbac_decorators(originals: Dict):
    """Restore original RBAC decorators.

    Args:
        originals: Dictionary of original functions returned by patch_rbac_decorators
    """
    # First-Party
    import mcpgateway.middleware.rbac as rbac_module

    rbac_module.require_permission = originals["require_permission"]
    rbac_module.require_admin_permission = originals["require_admin_permission"]
    rbac_module.require_any_permission = originals["require_any_permission"]


def teardown_rbac_mocks_for_app(app):
    """Remove RBAC mocks from a FastAPI application.

    This function clears the dependency overrides that were set up by
    setup_rbac_mocks_for_app.

    Args:
        app: FastAPI application instance
    """
    # First-Party
    from mcpgateway.auth import get_current_user, get_db
    from mcpgateway.middleware.rbac import (
        get_current_user_with_permissions,
        get_permission_service,
    )

    # Remove the specific RBAC-related overrides
    rbac_dependencies = [
        get_current_user_with_permissions,
        get_current_user,
        get_permission_service,
        get_db,
    ]

    for dep in rbac_dependencies:
        app.dependency_overrides.pop(dep, None)
