# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/rbac.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

RBAC Permission Checking Middleware.

This module provides middleware for FastAPI to enforce role-based access control
on API endpoints. It includes permission decorators and dependency injection
functions for protecting routes.
"""

# Standard
import functools
from functools import wraps
import logging
from typing import Callable, Generator, List, Optional
import uuid

# Third-Party
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import fresh_db_session, SessionLocal
from mcpgateway.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

# HTTP Bearer security scheme for token extraction
security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    DEPRECATED: Use fresh_db_session() context manager instead to avoid session accumulation.
    This function is kept for backwards compatibility with endpoints that still use Depends(get_db).

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Examples:
        >>> gen = get_db()
        >>> db = next(gen)
        >>> hasattr(db, 'query')
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


async def get_permission_service(db: Session = Depends(get_db)) -> PermissionService:
    """Get permission service instance for dependency injection.

    DEPRECATED: Use PermissionService(db) directly with fresh_db_session() context manager instead.
    This function is kept for backwards compatibility with endpoints that still use dependency injection.

    Args:
        db: Database session

    Returns:
        PermissionService: Permission checking service instance

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_permission_service)
        True
    """
    return PermissionService(db)


async def get_current_user_with_permissions(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_token: Optional[str] = Cookie(default=None)):
    """Extract current user from JWT token and prepare for permission checking.

    Uses fresh_db_session() context manager to avoid session accumulation under high load.
    Database sessions are created only when needed and closed immediately after use.

    Args:
        request: FastAPI request object for IP/user-agent extraction
        credentials: HTTP Bearer credentials
        jwt_token: JWT token from cookie

    Returns:
        dict: User information with permission checking context

    Raises:
        HTTPException: If authentication fails

    Examples:
        Use as FastAPI dependency::

            @app.get("/protected-endpoint")
            async def protected_route(user = Depends(get_current_user_with_permissions)):
                return {"user": user["email"]}
    """
    # Check for proxy authentication first (if MCP client auth is disabled)
    if not settings.mcp_client_auth_enabled:
        # Read plugin context from request.state for cross-hook context sharing
        # (set by HttpAuthMiddleware for passing contexts between different hook types)
        plugin_context_table = getattr(request.state, "plugin_context_table", None)
        plugin_global_context = getattr(request.state, "plugin_global_context", None)

        if settings.trust_proxy_auth:
            # Extract user from proxy header
            proxy_user = request.headers.get(settings.proxy_user_header)
            if proxy_user:
                # Lookup user in DB to get is_admin status, or check platform_admin_email
                is_admin = False
                full_name = proxy_user
                if proxy_user == settings.platform_admin_email:
                    is_admin = True
                    full_name = "Platform Admin"
                else:
                    # Try to lookup user in EmailUser table for is_admin status
                    try:
                        # Third-Party
                        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                        # First-Party
                        from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel

                        # Use fresh_db_session for short-lived database access
                        with fresh_db_session() as db:
                            user = db.execute(select(EmailUser).where(EmailUser.email == proxy_user)).scalar_one_or_none()
                            if user:
                                is_admin = user.is_admin
                                full_name = user.full_name or proxy_user
                    except Exception as e:
                        logger.debug(f"Could not lookup proxy user in DB: {e}")
                        # Continue with is_admin=False if lookup fails

                return {
                    "email": proxy_user,
                    "full_name": full_name,
                    "is_admin": is_admin,
                    "ip_address": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                    "db": None,  # Session closed; use endpoint's db param instead
                    "auth_method": "proxy",
                    "request_id": getattr(request.state, "request_id", None),
                    "team_id": getattr(request.state, "team_id", None),
                    "plugin_context_table": plugin_context_table,
                    "plugin_global_context": plugin_global_context,
                }

            # No proxy header - check auth_required to align with WebSocket behavior
            # For browser requests, redirect to login; for API requests, return 401
            if settings.auth_required:
                accept_header = request.headers.get("accept", "")
                is_htmx = request.headers.get("hx-request") == "true"
                if "text/html" in accept_header or is_htmx:
                    raise HTTPException(
                        status_code=status.HTTP_302_FOUND,
                        detail="Authentication required",
                        headers={"Location": f"{settings.app_root_path}/admin/login"},
                    )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Proxy authentication header required",
                )

            # auth_required=false: allow anonymous access

            return {
                "email": "anonymous",
                "full_name": "Anonymous User",
                "is_admin": False,
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "db": None,  # Session closed; use endpoint's db param instead
                "auth_method": "anonymous",
                "request_id": getattr(request.state, "request_id", None),
                "team_id": getattr(request.state, "team_id", None),
                "plugin_context_table": plugin_context_table,
                "plugin_global_context": plugin_global_context,
            }

        # Warning: MCP auth disabled without proxy trust - security risk!
        # This case is already warned about in config validation
        # Still check auth_required for consistency
        if settings.auth_required:
            accept_header = request.headers.get("accept", "")
            is_htmx = request.headers.get("hx-request") == "true"
            if "text/html" in accept_header or is_htmx:
                raise HTTPException(
                    status_code=status.HTTP_302_FOUND,
                    detail="Authentication required",
                    headers={"Location": f"{settings.app_root_path}/admin/login"},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required but no auth method configured",
            )

        return {
            "email": "anonymous",
            "full_name": "Anonymous User",
            "is_admin": False,
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "db": None,  # Session closed; use endpoint's db param instead
            "auth_method": "anonymous",
            "request_id": getattr(request.state, "request_id", None),
            "team_id": getattr(request.state, "team_id", None),
            "plugin_context_table": plugin_context_table,
            "plugin_global_context": plugin_global_context,
        }

    # Standard JWT authentication flow
    # Try multiple sources for the token, prioritizing Authorization header for API requests
    token = None
    token_from_cookie = False

    # 1. First try Authorization header (preferred for API requests)
    if credentials and credentials.credentials:
        token = credentials.credentials

    # 2. Try manual cookie reading (for browser requests)
    if not token and request.cookies:
        # Try both jwt_token and access_token cookie names
        manual_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")
        if manual_token:
            token = manual_token
            token_from_cookie = True

    # 3. Finally try FastAPI Cookie dependency (fallback)
    if not token and jwt_token:
        token = jwt_token
        token_from_cookie = True

    # Check if this is a browser/admin-UI request (not an external API request)
    accept_header = request.headers.get("accept", "")
    is_htmx = request.headers.get("hx-request") == "true"
    referer = request.headers.get("referer", "")
    is_admin_ui_request = "/admin" in referer
    is_browser_request = "text/html" in accept_header or is_htmx or is_admin_ui_request

    # SECURITY: Reject cookie-only authentication for API requests
    # Cookies should only be used for browser/HTML requests (including admin UI fetch calls)
    if token_from_cookie and not is_browser_request:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cookie authentication not allowed for API requests. Use Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token:
        # For browser requests (HTML Accept header or HTMX), redirect to login
        if is_browser_request:
            raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Authentication required", headers={"Location": f"{settings.app_root_path}/admin/login"})

        # If auth is disabled, return the stock admin user
        if not settings.auth_required:
            return {
                "email": settings.platform_admin_email,
                "full_name": "Platform Admin",
                "is_admin": True,
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "db": None,  # Session closed; use endpoint's db param instead
                "auth_method": "disabled",
                "request_id": getattr(request.state, "request_id", None),
                "team_id": getattr(request.state, "team_id", None),
            }

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token required")

    try:
        # Create credentials object if we got token from cookie
        if not credentials:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Extract user from token using the email auth function
        # Pass request to get_current_user so plugins can store auth_method in request.state
        user = await get_current_user(credentials, request=request)

        # Read auth_method and request_id from request.state
        # (auth_method set by plugin in get_current_user, request_id set by HTTP middleware)
        auth_method = getattr(request.state, "auth_method", None)
        request_id = getattr(request.state, "request_id", None)
        team_id = getattr(request.state, "team_id", None)

        # Read plugin context data from request.state for cross-hook context sharing
        # (set by HttpAuthMiddleware for passing contexts between different hook types)
        plugin_context_table = getattr(request.state, "plugin_context_table", None)
        plugin_global_context = getattr(request.state, "plugin_global_context", None)

        # Get token_use from request.state (set by get_current_user)
        token_use = getattr(request.state, "token_use", None)

        # Add request context for permission auditing
        return {
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "db": None,  # Session closed; use endpoint's db param instead
            "auth_method": auth_method,  # Include auth_method from plugin
            "request_id": request_id,  # Include request_id from middleware
            "team_id": team_id,  # Include team_id from token
            "token_use": token_use,  # Include token_use for RBAC team derivation
            "plugin_context_table": plugin_context_table,  # Plugin contexts for cross-hook sharing
            "plugin_global_context": plugin_global_context,  # Global context for consistency
        }
    except Exception as e:
        logger.error(f"Authentication failed: {type(e).__name__}: {e}")

        # For browser requests (HTML Accept header or HTMX), redirect to login
        accept_header = request.headers.get("accept", "")
        is_htmx = request.headers.get("hx-request") == "true"
        if "text/html" in accept_header or is_htmx:
            raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Authentication required", headers={"Location": f"{settings.app_root_path}/admin/login"})

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")


# --- Team derivation helpers for multi-team session tokens ---


@functools.lru_cache(maxsize=1)
def _get_resource_param_to_model():
    """Lazy-initialize the resource param to model mapping.

    Returns:
        dict: Mapping of URL parameter names to SQLAlchemy model classes.
    """
    # First-Party
    from mcpgateway.db import A2AAgent, Gateway, Prompt, Resource, Server, Tool  # pylint: disable=import-outside-toplevel

    return {
        "tool_id": Tool,
        "server_id": Server,
        "resource_id": Resource,
        "prompt_id": Prompt,
        "gateway_id": Gateway,
        "agent_id": A2AAgent,
    }


def _derive_team_from_resource(kwargs, db_session) -> Optional[str]:
    """Look up resource's team_id from DB for RBAC context (Tier 1).

    For endpoints that target a specific resource (get, update, delete, execute),
    derive the team context from the resource's owner team.

    Args:
        kwargs: Endpoint function kwargs containing resource ID params
        db_session: Active SQLAlchemy session

    Returns:
        team_id string if found, None otherwise
    """
    mapping = _get_resource_param_to_model()
    for param_name, model_cls in mapping.items():
        resource_id = kwargs.get(param_name)
        if resource_id:
            try:
                resource = db_session.get(model_cls, resource_id)
                if resource:
                    return getattr(resource, "team_id", None)
            except Exception:  # nosec B110 - DB lookup failure falls through to None
                pass
            return None  # Resource not found; let endpoint handle 404
    return None  # No resource ID param


async def _derive_team_from_payload(kwargs) -> Optional[str]:
    """Extract team_id from create payload objects or form data (Tier 3).

    For create endpoints, derive team context from the Pydantic payload or form data.

    Args:
        kwargs: Endpoint function kwargs

    Returns:
        team_id string if found, None otherwise
    """
    # Try Pydantic payload objects (API endpoints)
    for param_name in ("gateway", "tool", "server", "resource", "prompt", "agent"):
        payload_obj = kwargs.get(param_name)
        if payload_obj and hasattr(payload_obj, "team_id"):
            tid = getattr(payload_obj, "team_id", None)
            if tid:
                return tid

    # Try request form data (admin UI endpoints)
    # Note: use 'is not None' rather than truthiness check because some
    # objects (e.g. Pydantic models) may be truthy yet lack .headers.
    request = kwargs.get("request")
    if request is not None and isinstance(request, Request):
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            try:
                form = await request.form()
                tid = form.get("team_id")
                if tid:
                    return tid
            except Exception:  # nosec B110 - Form parse failure is non-fatal
                pass

    return None


# Permissions that indicate create/mutate operations (not safe for "any-team" aggregation)
_MUTATE_PERMISSION_ACTIONS = frozenset(
    {
        "create",
        "update",
        "delete",
        "execute",
        "invoke",
        "toggle",
        "set_state",
        "revoke",
        "manage_members",
        "join",
        "manage",
        "share",
        "invite",
        "use",
    }
)


def _is_mutate_permission(permission: str) -> bool:
    """Check if a permission string represents a mutate operation.

    Handles both dot-separated (tools.create) and colon-separated
    (admin.sso_providers:create) permission formats.

    Args:
        permission: Permission string like 'tools.create' or 'admin.sso_providers:create'.

    Returns:
        bool: True if the permission's action component is a mutating operation.
    """
    # Handle colon separator: admin.sso_providers:create → action is "create"
    if ":" in permission:
        action = permission.rsplit(":", 1)[-1]
        return action in _MUTATE_PERMISSION_ACTIONS
    parts = permission.split(".")
    return parts[-1] in _MUTATE_PERMISSION_ACTIONS if len(parts) >= 2 else False


def _log_policy_decision(user_context, permission, resource_type, decision_str, engines):
    """Log a policy decision if audit is enabled."""
    if settings.policy_audit_enabled:
        try:
            from mcpgateway.services.policy_decision_service import policy_decision_service  # pylint: disable=import-outside-toplevel

            policy_decision_service.log_decision(
                action=permission,
                decision=decision_str,
                subject_id=user_context.get("email"),
                subject_email=user_context.get("email"),
                resource_type=resource_type,
                ip_address=user_context.get("ip_address"),
                user_agent=user_context.get("user_agent"),
                request_id=user_context.get("request_id"),
                policy_engines_used=engines,
                severity="info" if decision_str == "allow" else "warning",
            )
        except Exception as audit_err:
            logger.warning(f"Policy decision logging failed: {audit_err}")


def require_permission(permission: str, resource_type: Optional[str] = None, allow_admin_bypass: bool = True):
    """Decorator to require specific permission for accessing an endpoint.

    Args:
        permission: Required permission (e.g., 'tools.create')
        resource_type: Optional resource type for resource-specific permissions
        allow_admin_bypass: If True (default), admin users bypass all permission checks.
                           If False, even admins must have explicit permissions.
                           Use False for admin UI routes to enforce granular RBAC.

    Returns:
        Callable: Decorated function that enforces the permission requirement

    Examples:
        >>> decorator = require_permission("tools.create", "tools")
        >>> callable(decorator)
        True

        Execute wrapped function when permission granted:
        >>> import asyncio
        >>> class DummyPS:
        ...     def __init__(self, db):
        ...         pass
        ...     async def check_permission(self, **kwargs):
        ...         return True
        >>> @require_permission("tools.read")
        ... async def demo(user=None):
        ...     return "ok"
        >>> from unittest.mock import patch
        >>> with patch('mcpgateway.middleware.rbac.PermissionService', DummyPS):
        ...     asyncio.run(demo(user={"email": "u", "db": object()}))
        'ok'
    """

    def decorator(func: Callable) -> Callable:
        """Decorator function that wraps the original function with permission checking.

        Args:
            func: The function to be decorated

        Returns:
            Callable: The wrapped function with permission checking
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Async wrapper function that performs permission check before calling original function.

            Args:
                *args: Positional arguments passed to the wrapped function
                **kwargs: Keyword arguments passed to the wrapped function

            Returns:
                Any: Result from the wrapped function if permission check passes

            Raises:
                HTTPException: If user authentication or permission check fails
            """
            # Extract user context from named kwargs only (security: avoid picking up request body dicts)
            user_context = kwargs.get("user") or kwargs.get("_user") or kwargs.get("current_user") or kwargs.get("current_user_ctx")
            if not user_context or not isinstance(user_context, dict) or "email" not in user_context:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User authentication required")

            # Extract team_id from path parameters if available
            team_id = kwargs.get("team_id")

            # If team_id is None or blank in kwargs then check
            if not team_id:
                # check if user_context has team_id
                team_id = user_context.get("team_id", None)

            # For multi-team session tokens (team_id is None), derive team from context
            check_any_team = False
            if not team_id and user_context.get("token_use") == "session":
                db_session = kwargs.get("db") or user_context.get("db")
                if db_session:
                    # Tier 1: Try to derive team from existing resource
                    team_id = _derive_team_from_resource(kwargs, db_session)
                    # Tier 3: Try to derive team from create payload / form
                    if team_id is None:
                        team_id = await _derive_team_from_payload(kwargs)
                # If still no team_id, check permission across all of the user's teams.
                # This separates authorization ("does this user have the permission?")
                # from resource scoping ("which team owns this resource?"). Team
                # assignment is enforced downstream by endpoint logic (e.g.
                # verify_team_for_user, token team membership checks).
                if not team_id:
                    check_any_team = True

            # First, check if any plugins want to handle permission checking
            # First-Party
            from mcpgateway.plugins.framework import get_plugin_manager, GlobalContext, HttpAuthCheckPermissionPayload, HttpHookType  # pylint: disable=import-outside-toplevel

            plugin_manager = get_plugin_manager()
            if plugin_manager and plugin_manager.has_hooks_for(HttpHookType.HTTP_AUTH_CHECK_PERMISSION):
                # Get plugin contexts from user_context (stored in request.state by HttpAuthMiddleware)
                # These enable cross-hook context sharing between HTTP_PRE_REQUEST and HTTP_AUTH_CHECK_PERMISSION
                plugin_context_table = user_context.get("plugin_context_table")
                plugin_global_context = user_context.get("plugin_global_context")

                # Reuse existing global context from middleware if available for consistency
                # Otherwise create a new one (fallback for cases where middleware didn't run)
                if plugin_global_context:
                    global_context = plugin_global_context
                else:
                    request_id = user_context.get("request_id") or uuid.uuid4().hex
                    global_context = GlobalContext(
                        request_id=request_id,
                        server_id=None,
                        tenant_id=None,
                    )

                # Invoke permission check hook, passing plugin contexts from HTTP_PRE_REQUEST hook
                result, _ = await plugin_manager.invoke_hook(
                    HttpHookType.HTTP_AUTH_CHECK_PERMISSION,
                    payload=HttpAuthCheckPermissionPayload(
                        user_email=user_context["email"],
                        permission=permission,
                        resource_type=resource_type,
                        team_id=team_id,
                        is_admin=user_context.get("is_admin", False),
                        auth_method=user_context.get("auth_method"),
                        client_host=user_context.get("ip_address"),
                        user_agent=user_context.get("user_agent"),
                    ),
                    global_context=global_context,
                    local_contexts=plugin_context_table,  # Pass context table for cross-hook state
                )

                # If a plugin made a decision, respect it
                if result and result.modified_payload:
                    plugin_decision_str = "allow" if result.modified_payload.granted else "deny"
                    _log_policy_decision(user_context, permission, resource_type, plugin_decision_str, ["plugin"])
                    if result.modified_payload.granted:
                        logger.info(f"Permission granted by plugin: user={user_context['email']}, " f"permission={permission}, reason={result.modified_payload.reason}")
                        return await func(*args, **kwargs)
                    logger.warning(f"Permission denied by plugin: user={user_context['email']}, " f"permission={permission}, reason={result.modified_payload.reason}")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Insufficient permissions. Required: {permission}",
                    )

            # No plugin handled it, fall through to standard RBAC check
            # Get db session: prefer endpoint's db param, then user_context["db"], then create fresh
            db_session = kwargs.get("db") or user_context.get("db")
            if db_session:
                # Use existing session from endpoint or user_context
                permission_service = PermissionService(db_session)
                granted = await permission_service.check_permission(
                    user_email=user_context["email"],
                    permission=permission,
                    resource_type=resource_type,
                    team_id=team_id,
                    ip_address=user_context.get("ip_address"),
                    user_agent=user_context.get("user_agent"),
                    allow_admin_bypass=allow_admin_bypass,
                    check_any_team=check_any_team,
                )
            else:
                # Create fresh db session for permission check
                with fresh_db_session() as db:
                    permission_service = PermissionService(db)
                    granted = await permission_service.check_permission(
                        user_email=user_context["email"],
                        permission=permission,
                        resource_type=resource_type,
                        team_id=team_id,
                        ip_address=user_context.get("ip_address"),
                        user_agent=user_context.get("user_agent"),
                        allow_admin_bypass=allow_admin_bypass,
                        check_any_team=check_any_team,
                    )

            # Log policy decision if enabled
            _log_policy_decision(user_context, permission, resource_type, "allow" if granted else "deny", ["rbac"])

            if not granted:
                logger.warning(f"Permission denied: user={user_context['email']}, permission={permission}, resource_type={resource_type}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Insufficient permissions. Required: {permission}")

            # Permission granted, execute the original function
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_admin_permission():
    """Decorator to require admin permissions for accessing an endpoint.

    Returns:
        Callable: Decorated function that enforces admin permission requirement

    Examples:
        >>> decorator = require_admin_permission()
        >>> callable(decorator)
        True

        Execute when admin permission granted:
        >>> import asyncio
        >>> class DummyPS:
        ...     def __init__(self, db):
        ...         pass
        ...     async def check_admin_permission(self, email):
        ...         return True
        >>> @require_admin_permission()
        ... async def demo(user=None):
        ...     return "admin-ok"
        >>> from unittest.mock import patch
        >>> with patch('mcpgateway.middleware.rbac.PermissionService', DummyPS):
        ...     asyncio.run(demo(user={"email": "u", "db": object()}))
        'admin-ok'
    """

    def decorator(func: Callable) -> Callable:
        """Decorator function that wraps the original function with admin permission checking.

        Args:
            func: The function to be decorated

        Returns:
            Callable: The wrapped function with admin permission checking
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Async wrapper function that performs admin permission check before calling original function.

            Args:
                *args: Positional arguments passed to the wrapped function
                **kwargs: Keyword arguments passed to the wrapped function

            Returns:
                Any: Result from the wrapped function if admin permission check passes

            Raises:
                HTTPException: If user authentication or admin permission check fails
            """
            # Extract user context from named kwargs only (security: avoid picking up request body dicts)
            user_context = kwargs.get("user") or kwargs.get("_user") or kwargs.get("current_user") or kwargs.get("current_user_ctx")
            if not user_context or not isinstance(user_context, dict) or "email" not in user_context:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User authentication required")

            # Get db session: prefer endpoint's db param, then user_context["db"], then create fresh
            db_session = kwargs.get("db") or user_context.get("db")
            if db_session:
                # Use existing session from endpoint or user_context
                permission_service = PermissionService(db_session)
                has_admin_permission = await permission_service.check_admin_permission(user_context["email"])
            else:
                # Create fresh db session for permission check
                with fresh_db_session() as db:
                    permission_service = PermissionService(db)
                    has_admin_permission = await permission_service.check_admin_permission(user_context["email"])

            if not has_admin_permission:
                logger.warning(f"Admin permission denied: user={user_context['email']}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required")

            # Admin permission granted, execute the original function
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_any_permission(permissions: List[str], resource_type: Optional[str] = None, allow_admin_bypass: bool = True):
    """Decorator to require any of the specified permissions for accessing an endpoint.

    Args:
        permissions: List of permissions, user needs at least one
        resource_type: Optional resource type for resource-specific permissions
        allow_admin_bypass: If True (default), admin users bypass all permission checks.
                           If False, even admins must have explicit permissions.

    Returns:
        Callable: Decorated function that enforces the permission requirements

    Examples:
        >>> decorator = require_any_permission(["tools.read", "tools.execute"], "tools")
        >>> callable(decorator)
        True

        Execute when any permission granted:
        >>> import asyncio
        >>> class DummyPS:
        ...     def __init__(self, db):
        ...         pass
        ...     async def check_permission(self, **kwargs):
        ...         return True
        >>> @require_any_permission(["tools.read", "tools.execute"], "tools")
        ... async def demo(user=None):
        ...     return "any-ok"
        >>> from unittest.mock import patch
        >>> with patch('mcpgateway.middleware.rbac.PermissionService', DummyPS):
        ...     asyncio.run(demo(user={"email": "u", "db": object()}))
        'any-ok'
    """

    def decorator(func: Callable) -> Callable:
        """Decorator function that wraps the original function with any-permission checking.

        Args:
            func: The function to be decorated

        Returns:
            Callable: The wrapped function with any-permission checking
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Async wrapper function that performs any-permission check before calling original function.

            Args:
                *args: Positional arguments passed to the wrapped function
                **kwargs: Keyword arguments passed to the wrapped function

            Returns:
                Any: Result from the wrapped function if any-permission check passes

            Raises:
                HTTPException: If user authentication or any-permission check fails
            """
            # Extract user context from named kwargs only (security: avoid picking up request body dicts)
            user_context = kwargs.get("user") or kwargs.get("_user") or kwargs.get("current_user") or kwargs.get("current_user_ctx")
            if not user_context or not isinstance(user_context, dict) or "email" not in user_context:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User authentication required")

            # Extract team_id from path parameters if available
            team_id = kwargs.get("team_id")

            # If team_id is None or blank in kwargs then check
            if not team_id:
                # check if user_context has team_id
                team_id = user_context.get("team_id", None)

            # For multi-team session tokens (team_id is None), derive team from context
            check_any_team = False
            if not team_id and user_context.get("token_use") == "session":
                db_session = kwargs.get("db") or user_context.get("db")
                if db_session:
                    # Tier 1: Try to derive team from existing resource
                    team_id = _derive_team_from_resource(kwargs, db_session)
                    # Tier 3: Try to derive team from create payload / form
                    if team_id is None:
                        team_id = await _derive_team_from_payload(kwargs)
                # If still no team_id, check permission across all of the user's teams.
                # Authorization ("does this user have the permission?") is separate
                # from resource scoping ("which team owns this resource?").
                if not team_id:
                    check_any_team = True

            # Get db session: prefer endpoint's db param, then user_context["db"], then create fresh
            db_session = kwargs.get("db") or user_context.get("db")
            if db_session:
                # Use existing session from endpoint or user_context
                permission_service = PermissionService(db_session)
                # Check if user has any of the required permissions
                granted = False
                for permission in permissions:
                    if await permission_service.check_permission(
                        user_email=user_context["email"],
                        permission=permission,
                        resource_type=resource_type,
                        team_id=team_id,
                        ip_address=user_context.get("ip_address"),
                        user_agent=user_context.get("user_agent"),
                        allow_admin_bypass=allow_admin_bypass,
                        check_any_team=check_any_team,
                    ):
                        granted = True
                        break
            else:
                # Create fresh db session for permission check
                with fresh_db_session() as db:
                    permission_service = PermissionService(db)
                    # Check if user has any of the required permissions
                    granted = False
                    for permission in permissions:
                        if await permission_service.check_permission(
                            user_email=user_context["email"],
                            permission=permission,
                            resource_type=resource_type,
                            team_id=team_id,
                            ip_address=user_context.get("ip_address"),
                            user_agent=user_context.get("user_agent"),
                            allow_admin_bypass=allow_admin_bypass,
                            check_any_team=check_any_team,
                        ):
                            granted = True
                            break

            if not granted:
                logger.warning(f"Permission denied: user={user_context['email']}, permissions={permissions}, resource_type={resource_type}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Insufficient permissions. Required one of: {', '.join(permissions)}")

            # Permission granted, execute the original function
            return await func(*args, **kwargs)

        return wrapper

    return decorator


class PermissionChecker:
    """Context manager for manual permission checking.

    Useful for complex permission logic that can't be handled by decorators.

    Examples:
        >>> from unittest.mock import Mock
        >>> checker = PermissionChecker({"email": "user@example.com", "db": Mock()})
        >>> hasattr(checker, 'has_permission') and hasattr(checker, 'has_admin_permission')
        True
    """

    def __init__(self, user_context: dict):
        """Initialize permission checker with user context.

        Args:
            user_context: User context from get_current_user_with_permissions
        """
        self.user_context = user_context
        self.db_session = user_context.get("db")

    async def has_permission(self, permission: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None, team_id: Optional[str] = None) -> bool:
        """Check if user has specific permission.

        Args:
            permission: Permission to check
            resource_type: Optional resource type
            resource_id: Optional resource ID
            team_id: Optional team context

        Returns:
            bool: True if user has permission
        """
        if self.db_session:
            # Use existing session
            permission_service = PermissionService(self.db_session)
            return await permission_service.check_permission(
                user_email=self.user_context["email"],
                permission=permission,
                resource_type=resource_type,
                resource_id=resource_id,
                team_id=team_id,
                ip_address=self.user_context.get("ip_address"),
                user_agent=self.user_context.get("user_agent"),
            )
        # Create fresh db session
        with fresh_db_session() as db:
            permission_service = PermissionService(db)
            return await permission_service.check_permission(
                user_email=self.user_context["email"],
                permission=permission,
                resource_type=resource_type,
                resource_id=resource_id,
                team_id=team_id,
                ip_address=self.user_context.get("ip_address"),
                user_agent=self.user_context.get("user_agent"),
            )

    async def has_admin_permission(self) -> bool:
        """Check if user has admin permissions.

        Returns:
            bool: True if user has admin permissions
        """
        if self.db_session:
            # Use existing session
            permission_service = PermissionService(self.db_session)
            return await permission_service.check_admin_permission(self.user_context["email"])
        # Create fresh db session
        with fresh_db_session() as db:
            permission_service = PermissionService(db)
            return await permission_service.check_admin_permission(self.user_context["email"])

    async def has_any_permission(self, permissions: List[str], resource_type: Optional[str] = None, team_id: Optional[str] = None) -> bool:
        """Check if user has any of the specified permissions.

        Args:
            permissions: List of permissions to check
            resource_type: Optional resource type
            team_id: Optional team context

        Returns:
            bool: True if user has at least one permission
        """
        if self.db_session:
            # Use existing session for all checks
            permission_service = PermissionService(self.db_session)
            for permission in permissions:
                if await permission_service.check_permission(
                    user_email=self.user_context["email"],
                    permission=permission,
                    resource_type=resource_type,
                    team_id=team_id,
                    ip_address=self.user_context.get("ip_address"),
                    user_agent=self.user_context.get("user_agent"),
                ):
                    return True
            return False
        # Create single fresh session for all checks (avoid N sessions for N permissions)
        with fresh_db_session() as db:
            permission_service = PermissionService(db)
            for permission in permissions:
                if await permission_service.check_permission(
                    user_email=self.user_context["email"],
                    permission=permission,
                    resource_type=resource_type,
                    team_id=team_id,
                    ip_address=self.user_context.get("ip_address"),
                    user_agent=self.user_context.get("user_agent"),
                ):
                    return True
            return False

    async def require_permission(self, permission: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None, team_id: Optional[str] = None) -> None:
        """Require specific permission, raise HTTPException if not granted.

        Args:
            permission: Required permission
            resource_type: Optional resource type
            resource_id: Optional resource ID
            team_id: Optional team context

        Raises:
            HTTPException: If permission is not granted
        """
        if not await self.has_permission(permission, resource_type, resource_id, team_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Insufficient permissions. Required: {permission}")
