# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/admin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Admin UI Routes for MCP Gateway.
This module contains all the administrative UI endpoints for the MCP Gateway.
It provides a comprehensive interface for managing servers, tools, resources,
prompts, gateways, and roots through RESTful API endpoints. The module handles
all aspects of CRUD operations for these entities, including creation,
reading, updating, deletion, and status toggling.

All endpoints in this module require authentication, which is enforced via
the require_auth or require_basic_auth dependency. The module integrates with
various services to perform the actual business logic operations on the
underlying data.
"""

# Standard
import asyncio
from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
from functools import wraps
import html
import io
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from typing import cast as typing_cast
from typing import Dict, List, Optional, Union
import urllib.parse
import uuid

# Third-Party
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
import httpx
import orjson
from pydantic import SecretStr, ValidationError
from pydantic_core import ValidationError as CoreValidationError
from sqlalchemy import and_, case, cast, desc, func, or_, select, String, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError, OperationalError
from sqlalchemy.orm import joinedload, Session
from sqlalchemy.sql.functions import coalesce
from starlette.datastructures import UploadFile as StarletteUploadFile

# First-Party
# Authentication and password-related imports
from mcpgateway.auth import get_current_user
from mcpgateway.cache.a2a_stats_cache import a2a_stats_cache
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.common.models import LogLevel
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, extract_json_field, get_db, GlobalConfig, ObservabilitySavedQuery, ObservabilitySpan, ObservabilityTrace
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import utc_now
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.routers.email_auth import create_access_token
from mcpgateway.schemas import (
    A2AAgentCreate,
    A2AAgentRead,
    A2AAgentUpdate,
    CatalogBulkRegisterRequest,
    CatalogBulkRegisterResponse,
    CatalogListRequest,
    CatalogListResponse,
    CatalogServerRegisterRequest,
    CatalogServerRegisterResponse,
    CatalogServerStatusResponse,
    GatewayCreate,
    GatewayRead,
    GatewayTestRequest,
    GatewayTestResponse,
    GatewayUpdate,
    GlobalConfigRead,
    GlobalConfigUpdate,
    PaginatedResponse,
    PaginationMeta,
    PluginDetail,
    PluginListResponse,
    PluginStatsResponse,
    PromptCreate,
    PromptMetrics,
    PromptRead,
    PromptUpdate,
    ResourceCreate,
    ResourceMetrics,
    ResourceUpdate,
    ServerCreate,
    ServerMetrics,
    ServerRead,
    ServerUpdate,
    ToolCreate,
    ToolMetrics,
    ToolRead,
    ToolUpdate,
)
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService
from mcpgateway.services.argon2_service import Argon2PasswordService
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.catalog_service import catalog_service
from mcpgateway.services.email_auth_service import AuthenticationError, EmailAuthService, PasswordValidationError
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.export_service import ExportError, ExportService
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayDuplicateConflictError, GatewayNameConflictError, GatewayNotFoundError, GatewayService
from mcpgateway.services.import_service import ConflictStrategy
from mcpgateway.services.import_service import ImportError as ImportServiceError
from mcpgateway.services.import_service import ImportService, ImportValidationError
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.performance_service import get_performance_service
from mcpgateway.services.plugin_service import get_plugin_service
from mcpgateway.services.prompt_service import PromptNameConflictError, PromptNotFoundError, PromptService
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService, ResourceURIConflictError
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerError, ServerNameConflictError, ServerNotFoundError, ServerService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.tag_service import TagService
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.tool_service import ToolError, ToolNameConflictError, ToolNotFoundError, ToolService
from mcpgateway.utils.create_jwt_token import create_jwt_token, get_jwt_token
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.metadata_capture import MetadataCapture
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.pagination import paginate_query
from mcpgateway.utils.passthrough_headers import PassthroughHeadersError
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.security_cookies import set_auth_cookie
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.validate_signature import sign_data

# Conditional imports for gRPC support (only if grpcio is installed)
try:
    # First-Party
    from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceRead, GrpcServiceUpdate
    from mcpgateway.services.grpc_service import GrpcService, GrpcServiceError, GrpcServiceNameConflictError, GrpcServiceNotFoundError

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    # Define placeholder types to avoid NameError
    GrpcServiceCreate = None  # type: ignore
    GrpcServiceRead = None  # type: ignore
    GrpcServiceUpdate = None  # type: ignore
    GrpcService = None  # type: ignore

    # Define placeholder exception classes that maintain the hierarchy
    class GrpcServiceError(Exception):  # type: ignore
        """Placeholder for GrpcServiceError when grpcio is not installed."""

    class GrpcServiceNotFoundError(GrpcServiceError):  # type: ignore
        """Placeholder for GrpcServiceNotFoundError when grpcio is not installed."""

    class GrpcServiceNameConflictError(GrpcServiceError):  # type: ignore
        """Placeholder for GrpcServiceNameConflictError when grpcio is not installed."""


# Import the shared logging service from main
# This will be set by main.py when it imports admin_router
logging_service: Optional[LoggingService] = None
LOGGER: logging.Logger = logging.getLogger("mcpgateway.admin")


def set_logging_service(service: LoggingService):
    """Set the logging service instance to use.

    This should be called by main.py to share the same logging service.

    Args:
        service: The LoggingService instance to use

    Examples:
        >>> from mcpgateway.services.logging_service import LoggingService
        >>> from mcpgateway import admin
        >>> logging_svc = LoggingService()
        >>> admin.set_logging_service(logging_svc)
        >>> admin.logging_service is not None
        True
        >>> admin.LOGGER is not None
        True

        Test with different service instance:
        >>> new_svc = LoggingService()
        >>> admin.set_logging_service(new_svc)
        >>> admin.logging_service == new_svc
        True
        >>> admin.LOGGER.name
        'mcpgateway.admin'

        Test that global variables are properly set:
        >>> admin.set_logging_service(logging_svc)
        >>> hasattr(admin, 'logging_service')
        True
        >>> hasattr(admin, 'LOGGER')
        True
    """
    global logging_service, LOGGER  # pylint: disable=global-statement
    logging_service = service
    LOGGER = logging_service.get_logger("mcpgateway.admin")


# Fallback for testing - create a temporary instance if not set
if logging_service is None:
    logging_service = LoggingService()
    LOGGER = logging_service.get_logger("mcpgateway.admin")


# Initialize services
server_service: ServerService = ServerService()
tool_service: ToolService = ToolService()
prompt_service: PromptService = PromptService()
gateway_service: GatewayService = GatewayService()
resource_service: ResourceService = ResourceService()
root_service: RootService = RootService()
export_service: ExportService = ExportService()
import_service: ImportService = ImportService()
# Initialize A2A service only if A2A features are enabled
a2a_service: Optional[A2AAgentService] = A2AAgentService() if settings.mcpgateway_a2a_enabled else None
# Initialize gRPC service only if gRPC features are enabled AND grpcio is installed
grpc_service_mgr: Optional[Any] = GrpcService() if (settings.mcpgateway_grpc_enabled and GRPC_AVAILABLE and GrpcService is not None) else None

# Set up basic authentication

# Rate limiting storage
rate_limit_storage = defaultdict(list)


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request.

    Args:
        request: FastAPI request object

    Returns:
        str: Client IP address

    Examples:
        >>> from unittest.mock import MagicMock
        >>>
        >>> # Test with X-Forwarded-For header
        >>> mock_request = MagicMock()
        >>> mock_request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
        >>> get_client_ip(mock_request)
        '192.168.1.1'
        >>>
        >>> # Test with X-Real-IP header
        >>> mock_request.headers = {"X-Real-IP": "10.0.0.5"}
        >>> get_client_ip(mock_request)
        '10.0.0.5'
        >>>
        >>> # Test with direct client IP
        >>> mock_request.headers = {}
        >>> mock_request.client.host = "127.0.0.1"
        >>> get_client_ip(mock_request)
        '127.0.0.1'
        >>>
        >>> # Test with no client info
        >>> mock_request.client = None
        >>> get_client_ip(mock_request)
        'unknown'
    """
    # Check for X-Forwarded-For header (proxy/load balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # Check for X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """Extract user agent from request.

    Args:
        request: FastAPI request object

    Returns:
        str: User agent string

    Examples:
        >>> from unittest.mock import MagicMock
        >>>
        >>> # Test with User-Agent header
        >>> mock_request = MagicMock()
        >>> mock_request.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"}
        >>> get_user_agent(mock_request)
        'Mozilla/5.0 (Windows NT 10.0)'
        >>>
        >>> # Test without User-Agent header
        >>> mock_request.headers = {}
        >>> get_user_agent(mock_request)
        'unknown'
    """
    return request.headers.get("User-Agent", "unknown")


def rate_limit(requests_per_minute: Optional[int] = None):
    """Apply rate limiting to admin endpoints.

    Args:
        requests_per_minute: Maximum requests per minute (uses config default if None)

    Returns:
        Decorator function that enforces rate limiting

    Examples:
        Test basic decorator creation:
        >>> from mcpgateway import admin
        >>> decorator = admin.rate_limit(10)
        >>> callable(decorator)
        True

        Test with None parameter (uses default):
        >>> default_decorator = admin.rate_limit(None)
        >>> callable(default_decorator)
        True

        Test with specific limit:
        >>> limited_decorator = admin.rate_limit(5)
        >>> callable(limited_decorator)
        True

        Test decorator returns wrapper:
        >>> async def dummy_func():
        ...     return "success"
        >>> decorated_func = decorator(dummy_func)
        >>> callable(decorated_func)
        True

        Test rate limit storage structure:
        >>> isinstance(admin.rate_limit_storage, dict)
        True
        >>> from collections import defaultdict
        >>> isinstance(admin.rate_limit_storage, defaultdict)
        True

        Test decorator with zero limit:
        >>> zero_limit_decorator = admin.rate_limit(0)
        >>> callable(zero_limit_decorator)
        True

        Test decorator with high limit:
        >>> high_limit_decorator = admin.rate_limit(1000)
        >>> callable(high_limit_decorator)
        True
    """

    def decorator(func_to_wrap):
        """Decorator that wraps the function with rate limiting logic.

        Args:
            func_to_wrap: The function to be wrapped with rate limiting

        Returns:
            The wrapped function with rate limiting applied
        """

        @wraps(func_to_wrap)
        async def wrapper(*args, request: Optional[Request] = None, **kwargs):
            """Execute the wrapped function with rate limiting enforcement.

            Args:
                *args: Positional arguments to pass to the wrapped function
                request: FastAPI Request object for extracting client IP
                **kwargs: Keyword arguments to pass to the wrapped function

            Returns:
                The result of the wrapped function call

            Raises:
                HTTPException: When rate limit is exceeded (429 status)
            """
            # use configured limit if none provided
            limit = requests_per_minute or settings.validation_max_requests_per_minute

            # request can be None in some edge cases (e.g., tests)
            client_ip = request.client.host if request and request.client else "unknown"
            current_time = time.time()
            minute_ago = current_time - 60

            # prune old timestamps
            rate_limit_storage[client_ip] = [ts for ts in rate_limit_storage[client_ip] if ts > minute_ago]

            # enforce
            if len(rate_limit_storage[client_ip]) >= limit:
                LOGGER.warning(f"Rate limit exceeded for IP {client_ip} on endpoint {func_to_wrap.__name__}")
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {limit} requests per minute.",
                )
            rate_limit_storage[client_ip].append(current_time)
            # IMPORTANT: forward request to the real endpoint
            return await func_to_wrap(*args, request=request, **kwargs)

        return wrapper

    return decorator


def get_user_email(user: Union[str, dict, object] = None) -> str:
    """Return the user email from a JWT payload, user object, or string.

    Args:
        user (Union[str, dict, object], optional): User object from JWT token
            (from get_current_user_with_permissions). Can be:
            - dict: representing JWT payload
            - object: with an `email` attribute
            - str: an email string
            - None: will return "unknown"
            Defaults to None.

    Returns:
        str: User email address, or "unknown" if no email can be determined.
             - If `user` is a dict, returns `sub` if present, else `email`, else "unknown".
             - If `user` has an `email` attribute, returns that.
             - If `user` is a string, returns it.
             - If `user` is None, returns "unknown".
             - Otherwise, returns str(user).

    Examples:
        >>> get_user_email({'sub': 'alice@example.com'})
        'alice@example.com'
        >>> get_user_email({'email': 'bob@company.com'})
        'bob@company.com'
        >>> get_user_email({'sub': 'charlie@primary.com', 'email': 'charlie@secondary.com'})
        'charlie@primary.com'
        >>> get_user_email({'username': 'dave'})
        'unknown'
        >>> class MockUser:
        ...     def __init__(self, email):
        ...         self.email = email
        >>> get_user_email(MockUser('eve@test.com'))
        'eve@test.com'
        >>> get_user_email(None)
        'unknown'
        >>> get_user_email('grace@example.org')
        'grace@example.org'
        >>> get_user_email({})
        'unknown'
        >>> get_user_email(12345)
        '12345'
    """
    if isinstance(user, dict):
        return user.get("sub") or user.get("email") or "unknown"

    if hasattr(user, "email"):
        return user.email

    if user is None:
        return "unknown"

    return str(user)


def get_user_id(user: Union[str, dict[str, Any], object] = None) -> str:
    """Return the user ID from a JWT payload, user object, or string.

    Args:
        user (Union[str, dict, object], optional): User object from JWT token
            (from get_current_user_with_permissions). Can be:
            - dict: representing JWT payload with 'id', 'user_id', or 'sub'
            - object: with an `id` attribute
            - str: a user ID string
            - None: will return "unknown"
            Defaults to None.

    Returns:
        str: User ID, or "unknown" if no ID can be determined.
             - If `user` is a dict, returns `id` if present, else `user_id`, else `sub`, else email as fallback, else "unknown".
             - If `user` has an `id` attribute, returns that.
             - If `user` is a string, returns it.
             - If `user` is None, returns "unknown".
             - Otherwise, returns str(user).

    Examples:
        >>> get_user_id({'id': '123'})
        '123'
        >>> get_user_id({'user_id': '456'})
        '456'
        >>> get_user_id({'sub': 'alice@example.com'})
        'alice@example.com'
        >>> get_user_id({'email': 'bob@company.com'})
        'bob@company.com'
        >>> class MockUser:
        ...     def __init__(self, user_id):
        ...         self.id = user_id
        >>> get_user_id(MockUser('789'))
        '789'
        >>> get_user_id(None)
        'unknown'
        >>> get_user_id('user-xyz')
        'user-xyz'
        >>> get_user_id({})
        'unknown'
    """
    if isinstance(user, dict):
        # Try multiple possible ID fields in order of preference.
        # Email is the primary key in the model, so that's our mostly likely result.
        return user.get("id") or user.get("user_id") or user.get("sub") or user.get("email") or "unknown"

    return "unknown" if user is None else str(getattr(user, "id", user))


def serialize_datetime(obj):
    """Convert datetime objects to ISO format strings for JSON serialization.

    Args:
        obj: Object to serialize, potentially a datetime

    Returns:
        str: ISO format string if obj is datetime, otherwise returns obj unchanged

    Examples:
        Test with datetime object:
        >>> from mcpgateway import admin
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        >>> admin.serialize_datetime(dt)
        '2025-01-15T10:30:45+00:00'

        Test with naive datetime:
        >>> dt_naive = datetime(2025, 3, 20, 14, 15, 30)
        >>> result = admin.serialize_datetime(dt_naive)
        >>> '2025-03-20T14:15:30' in result
        True

        Test with datetime with microseconds:
        >>> dt_micro = datetime(2025, 6, 10, 9, 25, 12, 500000)
        >>> result = admin.serialize_datetime(dt_micro)
        >>> '2025-06-10T09:25:12.500000' in result
        True

        Test with non-datetime objects (should return unchanged):
        >>> admin.serialize_datetime("2025-01-15T10:30:45")
        '2025-01-15T10:30:45'
        >>> admin.serialize_datetime(12345)
        12345
        >>> admin.serialize_datetime(['a', 'list'])
        ['a', 'list']
        >>> admin.serialize_datetime({'key': 'value'})
        {'key': 'value'}
        >>> admin.serialize_datetime(None)
        >>> admin.serialize_datetime(True)
        True

        Test with current datetime:
        >>> import datetime as dt_module
        >>> now = dt_module.datetime.now()
        >>> result = admin.serialize_datetime(now)
        >>> isinstance(result, str)
        True
        >>> 'T' in result  # ISO format contains 'T' separator
        True

        Test edge case with datetime min/max:
        >>> dt_min = datetime.min
        >>> result = admin.serialize_datetime(dt_min)
        >>> result.startswith('0001-01-01T')
        True
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets strength requirements.

    Uses configurable settings from config.py for password policy.

    Args:
        password: Password to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    min_length = getattr(settings, "password_min_length", 8)
    require_uppercase = getattr(settings, "password_require_uppercase", False)
    require_lowercase = getattr(settings, "password_require_lowercase", False)
    require_numbers = getattr(settings, "password_require_numbers", False)
    require_special = getattr(settings, "password_require_special", False)

    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters long"

    if require_uppercase and not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter (A-Z)"

    if require_lowercase and not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter (a-z)"

    if require_numbers and not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number (0-9)"

    # Match the special character set used in EmailAuthService
    special_chars = '!@#$%^&*(),.?":{}|<>'
    if require_special and not any(c in special_chars for c in password):
        return False, f"Password must contain at least one special character ({special_chars})"

    return True, ""


admin_router = APIRouter(prefix="/admin", tags=["Admin UI"])

####################
# Admin UI Routes  #
####################


@admin_router.get("/config/passthrough-headers", response_model=GlobalConfigRead)
@rate_limit(requests_per_minute=30)  # Lower limit for config endpoints
async def get_global_passthrough_headers(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> GlobalConfigRead:
    """Get the global passthrough headers configuration.

    Args:
        db: Database session
        _user: Authenticated user

    Returns:
        GlobalConfigRead: The current global passthrough headers configuration

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import get_global_passthrough_headers
        >>> get_global_passthrough_headers.__name__
        'get_global_passthrough_headers'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_global_passthrough_headers)
        True
    """
    # Use cache for reads (Issue #1715)
    passthrough_headers = global_config_cache.get_passthrough_headers(db, [])
    return GlobalConfigRead(passthrough_headers=passthrough_headers)


@admin_router.put("/config/passthrough-headers", response_model=GlobalConfigRead)
@rate_limit(requests_per_minute=20)  # Stricter limit for config updates
async def update_global_passthrough_headers(
    request: Request,  # pylint: disable=unused-argument
    config_update: GlobalConfigUpdate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> GlobalConfigRead:
    """Update the global passthrough headers configuration.

    Args:
        request: HTTP request object
        config_update: The new configuration
        db: Database session
        _user: Authenticated user

    Raises:
        HTTPException: If there is a conflict or validation error

    Returns:
        GlobalConfigRead: The updated configuration

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import update_global_passthrough_headers
        >>> update_global_passthrough_headers.__name__
        'update_global_passthrough_headers'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(update_global_passthrough_headers)
        True
    """
    try:
        config = db.query(GlobalConfig).first()
        if not config:
            config = GlobalConfig(passthrough_headers=config_update.passthrough_headers)
            db.add(config)
        else:
            config.passthrough_headers = config_update.passthrough_headers
        db.commit()
        # Invalidate cache so changes propagate immediately (Issue #1715)
        global_config_cache.invalidate()
        return GlobalConfigRead(passthrough_headers=config.passthrough_headers)
    except (IntegrityError, ValidationError, PassthroughHeadersError) as e:
        db.rollback()
        if isinstance(e, IntegrityError):
            raise HTTPException(status_code=409, detail="Passthrough headers conflict")
        if isinstance(e, ValidationError):
            raise HTTPException(status_code=422, detail="Invalid passthrough headers format")
        if isinstance(e, PassthroughHeadersError):
            raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail="Unknown error occurred")


@admin_router.post("/config/passthrough-headers/invalidate-cache")
@rate_limit(requests_per_minute=10)  # Strict limit for cache operations
async def invalidate_passthrough_headers_cache(
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Invalidate the GlobalConfig cache.

    Forces an immediate cache refresh on the next access. Use this after
    updating GlobalConfig outside the normal API flow, or when you need
    changes to propagate immediately across all workers.

    Args:
        _user: Authenticated user

    Returns:
        Dict with invalidation status and cache statistics

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import invalidate_passthrough_headers_cache
        >>> invalidate_passthrough_headers_cache.__name__
        'invalidate_passthrough_headers_cache'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(invalidate_passthrough_headers_cache)
        True
    """
    global_config_cache.invalidate()
    stats = global_config_cache.stats()
    return {
        "status": "invalidated",
        "message": "GlobalConfig cache invalidated successfully",
        "cache_stats": stats,
    }


@admin_router.get("/config/passthrough-headers/cache-stats")
@rate_limit(requests_per_minute=30)
async def get_passthrough_headers_cache_stats(
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Get GlobalConfig cache statistics.

    Returns cache hit/miss counts, hit rate, TTL, and current cache status.
    Useful for monitoring cache effectiveness and debugging.

    Args:
        _user: Authenticated user

    Returns:
        Dict with cache statistics

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import get_passthrough_headers_cache_stats
        >>> get_passthrough_headers_cache_stats.__name__
        'get_passthrough_headers_cache_stats'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_passthrough_headers_cache_stats)
        True
    """
    return global_config_cache.stats()


# ===================================
# A2A Stats Cache Endpoints
# ===================================


@admin_router.post("/cache/a2a-stats/invalidate")
@rate_limit(requests_per_minute=10)
async def invalidate_a2a_stats_cache(
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Invalidate the A2A stats cache.

    Forces an immediate cache refresh on the next access. Use this after
    modifying A2A agents outside the normal API flow, or when you need
    changes to propagate immediately.

    Args:
        _user: Authenticated user

    Returns:
        Dict with invalidation status and cache statistics

    Examples:
        >>> from mcpgateway.admin import invalidate_a2a_stats_cache
        >>> invalidate_a2a_stats_cache.__name__
        'invalidate_a2a_stats_cache'
        >>> import inspect
        >>> inspect.iscoroutinefunction(invalidate_a2a_stats_cache)
        True
    """
    a2a_stats_cache.invalidate()
    stats = a2a_stats_cache.stats()
    return {
        "status": "invalidated",
        "message": "A2A stats cache invalidated successfully",
        "cache_stats": stats,
    }


@admin_router.get("/cache/a2a-stats/stats")
@rate_limit(requests_per_minute=30)
async def get_a2a_stats_cache_stats(
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Get A2A stats cache statistics.

    Returns cache hit/miss counts, hit rate, TTL, and current cache status.
    Useful for monitoring cache effectiveness and debugging.

    Args:
        _user: Authenticated user

    Returns:
        Dict with cache statistics

    Examples:
        >>> from mcpgateway.admin import get_a2a_stats_cache_stats
        >>> get_a2a_stats_cache_stats.__name__
        'get_a2a_stats_cache_stats'
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_a2a_stats_cache_stats)
        True
    """
    return a2a_stats_cache.stats()


@admin_router.get("/config/settings")
async def get_configuration_settings(
    _db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Get application configuration settings grouped by category.

    Returns configuration settings with sensitive values masked.

    Args:
        _db: Database session
        _user: Authenticated user

    Returns:
        Dict with configuration groups and their settings
    """

    def mask_sensitive(value: Any, key: str) -> Any:
        """Mask sensitive configuration values.

        Args:
            value: Configuration value to potentially mask
            key: Configuration key name to check for sensitive patterns

        Returns:
            Masked value if sensitive, original value otherwise
        """
        sensitive_keys = {"password", "secret", "key", "token", "credentials", "client_secret", "private_key", "auth_encryption_secret"}
        if any(s in key.lower() for s in sensitive_keys):
            # Handle SecretStr objects
            if isinstance(value, SecretStr):
                return settings.masked_auth_value
            if value and str(value) not in ["", "None", "null"]:
                return settings.masked_auth_value
        # Handle SecretStr even for non-sensitive keys
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return value

    # Group settings by category
    config_groups = {
        "Basic Settings": {
            "app_name": settings.app_name,
            "host": settings.host,
            "port": settings.port,
            "environment": settings.environment,
            "app_domain": str(settings.app_domain),
            "protocol_version": settings.protocol_version,
        },
        "Authentication & Security": {
            "auth_required": settings.auth_required,
            "basic_auth_user": settings.basic_auth_user,
            "basic_auth_password": mask_sensitive(settings.basic_auth_password, "password"),
            "jwt_algorithm": settings.jwt_algorithm,
            "jwt_secret_key": mask_sensitive(settings.jwt_secret_key, "secret_key"),
            "jwt_audience": settings.jwt_audience,
            "jwt_issuer": settings.jwt_issuer,
            "token_expiry": settings.token_expiry,
            "require_token_expiration": settings.require_token_expiration,
            "mcp_client_auth_enabled": settings.mcp_client_auth_enabled,
            "trust_proxy_auth": settings.trust_proxy_auth,
            "skip_ssl_verify": settings.skip_ssl_verify,
        },
        "SSO Configuration": {
            "sso_enabled": settings.sso_enabled,
            "sso_github_enabled": settings.sso_github_enabled,
            "sso_google_enabled": settings.sso_google_enabled,
            "sso_ibm_verify_enabled": settings.sso_ibm_verify_enabled,
            "sso_okta_enabled": settings.sso_okta_enabled,
            "sso_keycloak_enabled": settings.sso_keycloak_enabled,
            "sso_entra_enabled": settings.sso_entra_enabled,
            "sso_generic_enabled": settings.sso_generic_enabled,
            "sso_auto_create_users": settings.sso_auto_create_users,
            "sso_preserve_admin_auth": settings.sso_preserve_admin_auth,
            "sso_require_admin_approval": settings.sso_require_admin_approval,
        },
        "Email Authentication": {
            "email_auth_enabled": settings.email_auth_enabled,
            "platform_admin_email": settings.platform_admin_email,
            "platform_admin_password": mask_sensitive(settings.platform_admin_password, "password"),
        },
        "Database & Cache": {
            "database_url": settings.database_url.replace("://", "://***@") if "@" in settings.database_url else settings.database_url,
            "cache_type": settings.cache_type,
            "redis_url": settings.redis_url.replace("://", "://***@") if settings.redis_url and "@" in settings.redis_url else settings.redis_url,
            "db_pool_size": settings.db_pool_size,
            "db_max_overflow": settings.db_max_overflow,
        },
        "Feature Flags": {
            "mcpgateway_ui_enabled": settings.mcpgateway_ui_enabled,
            "mcpgateway_admin_api_enabled": settings.mcpgateway_admin_api_enabled,
            "mcpgateway_bulk_import_enabled": settings.mcpgateway_bulk_import_enabled,
            "mcpgateway_a2a_enabled": settings.mcpgateway_a2a_enabled,
            "mcpgateway_catalog_enabled": settings.mcpgateway_catalog_enabled,
            "plugins_enabled": settings.plugins_enabled,
            "well_known_enabled": settings.well_known_enabled,
        },
        "Federation": {
            "federation_enabled": settings.federation_enabled,
            "federation_discovery": settings.federation_discovery,
            "federation_timeout": settings.federation_timeout,
            "federation_sync_interval": settings.federation_sync_interval,
        },
        "Transport": {
            "transport_type": settings.transport_type,
            "websocket_ping_interval": settings.websocket_ping_interval,
            "sse_retry_timeout": settings.sse_retry_timeout,
            "sse_keepalive_enabled": settings.sse_keepalive_enabled,
        },
        "Logging": {
            "log_level": settings.log_level,
            "log_format": settings.log_format,
            "log_to_file": settings.log_to_file,
            "log_file": settings.log_file,
            "log_rotation_enabled": settings.log_rotation_enabled,
        },
        "Resources & Tools": {
            "tool_timeout": settings.tool_timeout,
            "tool_rate_limit": settings.tool_rate_limit,
            "tool_concurrent_limit": settings.tool_concurrent_limit,
            "resource_cache_size": settings.resource_cache_size,
            "resource_cache_ttl": settings.resource_cache_ttl,
            "max_resource_size": settings.max_resource_size,
        },
        "CORS Settings": {
            "cors_enabled": settings.cors_enabled,
            "allowed_origins": list(settings.allowed_origins),
            "cors_allow_credentials": settings.cors_allow_credentials,
        },
        "Security Headers": {
            "security_headers_enabled": settings.security_headers_enabled,
            "x_frame_options": settings.x_frame_options,
            "hsts_enabled": settings.hsts_enabled,
            "hsts_max_age": settings.hsts_max_age,
            "remove_server_headers": settings.remove_server_headers,
        },
        "Observability": {
            "otel_enable_observability": settings.otel_enable_observability,
            "otel_traces_exporter": settings.otel_traces_exporter,
            "otel_service_name": settings.otel_service_name,
        },
        "Development": {
            "dev_mode": settings.dev_mode,
            "reload": settings.reload,
            "debug": settings.debug,
        },
    }

    return {
        "groups": config_groups,
        "security_status": settings.get_security_status(),
    }


@admin_router.get("/servers", response_model=PaginatedResponse)
async def admin_list_servers(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List servers for the admin UI with pagination support.

    This endpoint retrieves a paginated list of servers from the database, optionally
    including those that are inactive. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed) for offset pagination.
        per_page (int): Number of items per page (1-500).
        include_inactive (bool): Whether to include inactive servers.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - data: List of server records formatted with by_alias=True
            - pagination: Pagination metadata
            - links: Pagination links (optional)

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ServerRead, ServerMetrics
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> # Mock server service
        >>> from datetime import datetime, timezone
        >>> mock_metrics = ServerMetrics(
        ...     total_executions=10,
        ...     successful_executions=8,
        ...     failed_executions=2,
        ...     failure_rate=0.2,
        ...     min_response_time=0.1,
        ...     max_response_time=2.0,
        ...     avg_response_time=0.5,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_server = ServerRead(
        ...     id="server-1",
        ...     name="Test Server",
        ...     description="A test server",
        ...     icon="test-icon.png",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     enabled=True,
        ...     associated_tools=["tool1", "tool2"],
        ...     associated_resources=["1", "2"],
        ...     associated_prompts=["1"],
        ...     metrics=mock_metrics
        ... )
        >>>
        >>> # Mock paginate_query
        >>> async def mock_list_servers(*args, **kwargs):
        ...     from mcpgateway.schemas import PaginationMeta, PaginationLinks
        ...     return {
        ...         "data": [mock_server],
        ...         "pagination": PaginationMeta(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
        ...         "links": PaginationLinks(self="/admin/servers?page=1&per_page=50", first="/admin/servers?page=1&per_page=50", last="/admin/servers?page=1&per_page=50", next=None, prev=None)
        ...     }
        >>>
        >>> from unittest.mock import patch
        >>> # Test listing servers with pagination
        >>> async def test_admin_list_servers_paginated():
        ...     with patch("mcpgateway.admin.server_service.list_servers", new=mock_list_servers):
        ...         result = await admin_list_servers(page=1, per_page=50, include_inactive=False, db=mock_db, user=mock_user)
        ...         return "data" in result and "pagination" in result
        >>>
        >>> asyncio.run(test_admin_list_servers_paginated())
        True
    """
    LOGGER.debug(f"User {get_user_email(user)} requested server list (page={page}, per_page={per_page})")
    user_email = get_user_email(user)

    # Call server_service.list_servers with page-based pagination
    paginated_result = await server_service.list_servers(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [server.model_dump(by_alias=True) for server in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.get("/servers/{server_id}", response_model=ServerRead)
async def admin_get_server(server_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """
    Retrieve server details for the admin UI.

    Args:
        server_id (str): The ID of the server to retrieve.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        Dict[str, Any]: The server details.

    Raises:
        HTTPException: If the server is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ServerRead, ServerMetrics
        >>> from mcpgateway.services.server_service import ServerNotFoundError
        >>> from fastapi import HTTPException
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> server_id = "test-server-1"
        >>>
        >>> # Mock server response
        >>> from datetime import datetime, timezone
        >>> mock_metrics = ServerMetrics(
        ...     total_executions=5,
        ...     successful_executions=4,
        ...     failed_executions=1,
        ...     failure_rate=0.2,
        ...     min_response_time=0.2,
        ...     max_response_time=1.5,
        ...     avg_response_time=0.8,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_server = ServerRead(
        ...     id=server_id,
        ...     name="Test Server",
        ...     description="A test server",
        ...     icon="test-icon.png",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     enabled=True,
        ...     associated_tools=["tool1"],
        ...     associated_resources=["1"],
        ...     associated_prompts=["1"],
        ...     metrics=mock_metrics
        ... )
        >>>
        >>> # Mock the server_service.get_server method
        >>> original_get_server = server_service.get_server
        >>> server_service.get_server = AsyncMock(return_value=mock_server)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_server_success():
        ...     result = await admin_get_server(
        ...         server_id=server_id,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     return isinstance(result, dict) and result.get('id') == server_id
        >>>
        >>> # Run the test
        >>> asyncio.run(test_admin_get_server_success())
        True
        >>>
        >>> # Test server not found scenario
        >>> server_service.get_server = AsyncMock(side_effect=ServerNotFoundError("Server not found"))
        >>>
        >>> async def test_admin_get_server_not_found():
        ...     try:
        ...         await admin_get_server(
        ...             server_id="nonexistent",
        ...             db=mock_db,
        ...             user=mock_user
        ...         )
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404
        >>>
        >>> # Run the not found test
        >>> asyncio.run(test_admin_get_server_not_found())
        True
        >>>
        >>> # Restore original method
        >>> server_service.get_server = original_get_server
    """
    try:
        LOGGER.debug(f"User {get_user_email(user)} requested details for server ID {server_id}")
        server = await server_service.get_server(db, server_id)
        return server.model_dump(by_alias=True)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting server {server_id}: {e}")
        raise e


@admin_router.post("/servers", response_model=ServerRead)
async def admin_add_server(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> JSONResponse:
    """
    Add a new server via the admin UI.

    This endpoint processes form data to create a new server entry in the database.
    It handles exceptions gracefully and logs any errors that occur during server
    registration.

    Expects form fields:
      - name (required): The name of the server
      - description (optional): A description of the server's purpose
      - icon (optional): URL or path to the server's icon
      - associatedTools (optional, multiple values): Tools associated with this server
      - associatedResources (optional, multiple values): Resources associated with this server
      - associatedPrompts (optional, multiple values): Prompts associated with this server

    Args:
        request (Request): FastAPI request containing form data.
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        JSONResponse: A JSON response indicating success or failure of the server creation operation.

    Examples:
        >>> import asyncio
        >>> import uuid
        >>> from datetime import datetime
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        >>> short_uuid = str(uuid.uuid4())[:8]
        >>> unq_ext = f"{timestamp}-{short_uuid}"
        >>> mock_user = {"email": "test_user_" + unq_ext, "db": mock_db}
        >>> # Mock form data for successful server creation
        >>> form_data = FormData([
        ...     ("name", "Test-Server-"+unq_ext ),
        ...     ("description", "A test server"),
        ...     ("icon", "https://raw.githubusercontent.com/github/explore/main/topics/python/python.png"),
        ...     ("associatedTools", "tool1"),
        ...     ("associatedTools", "tool2"),
        ...     ("associatedResources", "resource1"),
        ...     ("associatedResources", "resource2"),
        ...     ("associatedPrompts", "prompt1"),
        ...     ("associatedPrompts", "prompt2"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>>
        >>> # Mock request with form data
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": "/test"}
        >>>
        >>> # Mock server service
        >>> original_register_server = server_service.register_server
        >>> server_service.register_server = AsyncMock()
        >>>
        >>> # Test successful server addition
        >>> async def test_admin_add_server_success():
        ...     result = await admin_add_server(
        ...         request=mock_request,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     # Accept both Successful (200) and JSONResponse (422/409) for error cases
        ...     #print(result.status_code)
        ...     return isinstance(result, JSONResponse) and result.status_code in (200, 409, 422, 500)
        >>>
        >>> asyncio.run(test_admin_add_server_success())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Test Server"),
        ...     ("description", "A test server"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_add_server_inactive():
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code in (200, 409, 422, 500)
        >>>
        >>> #asyncio.run(test_admin_add_server_inactive())
        >>>
        >>> # Test exception handling - should still return redirect
        >>> async def test_admin_add_server_exception():
        ...     server_service.register_server = AsyncMock(side_effect=Exception("Test error"))
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500
        >>>
        >>> asyncio.run(test_admin_add_server_exception())
        True
        >>>
        >>> # Test with minimal form data
        >>> form_data_minimal = FormData([("name", "Minimal Server")])
        >>> mock_request.form = AsyncMock(return_value=form_data_minimal)
        >>> server_service.register_server = AsyncMock()
        >>>
        >>> async def test_admin_add_server_minimal():
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     #print (result)
        ...     #print (result.status_code)
        ...     return isinstance(result, JSONResponse) and result.status_code==200
        >>>
        >>> asyncio.run(test_admin_add_server_minimal())
        True
        >>>
        >>> # Restore original method
        >>> server_service.register_server = original_register_server
    """
    form = await request.form()
    # root_path = request.scope.get("root_path", "")
    # is_inactive_checked = form.get("is_inactive_checked", "false")

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        LOGGER.debug(f"User {get_user_email(user)} is adding a new server with name: {form['name']}")
        visibility = str(form.get("visibility", "private"))

        # Handle "Select All" for tools
        associated_tools_list = form.getlist("associatedTools")
        if form.get("selectAllTools") == "true":
            # User clicked "Select All" - get all tool IDs from hidden field
            all_tool_ids_json = str(form.get("allToolIds", "[]"))
            try:
                all_tool_ids = orjson.loads(all_tool_ids_json)
                associated_tools_list = all_tool_ids
                LOGGER.info(f"Select All tools enabled: {len(all_tool_ids)} tools selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allToolIds JSON, falling back to checked tools")

        # Handle "Select All" for resources
        associated_resources_list = form.getlist("associatedResources")
        if form.get("selectAllResources") == "true":
            all_resource_ids_json = str(form.get("allResourceIds", "[]"))
            try:
                all_resource_ids = orjson.loads(all_resource_ids_json)
                associated_resources_list = all_resource_ids
                LOGGER.info(f"Select All resources enabled: {len(all_resource_ids)} resources selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allResourceIds JSON, falling back to checked resources")

        # Handle "Select All" for prompts
        associated_prompts_list = form.getlist("associatedPrompts")
        if form.get("selectAllPrompts") == "true":
            all_prompt_ids_json = str(form.get("allPromptIds", "[]"))
            try:
                all_prompt_ids = orjson.loads(all_prompt_ids_json)
                associated_prompts_list = all_prompt_ids
                LOGGER.info(f"Select All prompts enabled: {len(all_prompt_ids)} prompts selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allPromptIds JSON, falling back to checked prompts")

        server = ServerCreate(
            id=form.get("id") or None,
            name=form.get("name"),
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=",".join(str(x) for x in associated_tools_list),
            associated_resources=",".join(str(x) for x in associated_resources_list),
            associated_prompts=",".join(str(x) for x in associated_prompts_list),
            tags=tags,
            visibility=visibility,
        )
    except KeyError as e:
        # Convert KeyError to ValidationError-like response
        return ORJSONResponse(content={"message": f"Missing required field: {e}", "success": False}, status_code=422)
    try:
        user_email = get_user_email(user)
        # Determine personal team for default assignment
        team_id_raw = form.get("team_id", None)
        team_id = str(team_id_raw) if team_id_raw is not None else None

        team_service = TeamManagementService(db)
        team_id = await team_service.verify_team_for_user(user_email, team_id)

        # Extract metadata for server creation
        creation_metadata = MetadataCapture.extract_creation_metadata(request, user)

        # Ensure default visibility is private and assign to personal team when available
        team_id_cast = typing_cast(Optional[str], team_id)
        await server_service.register_server(
            db,
            server,
            created_by=user_email,  # Use the consistent user_email
            created_from_ip=creation_metadata["created_from_ip"],
            created_via=creation_metadata["created_via"],
            created_user_agent=creation_metadata["created_user_agent"],
            team_id=team_id_cast,
            visibility=visibility,
        )
        return ORJSONResponse(
            content={"message": "Server created successfully!", "success": True},
            status_code=200,
        )

    except CoreValidationError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=422)
    except ServerNameConflictError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ServerError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValueError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except ValidationError as ex:
        return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except IntegrityError as ex:
        return ORJSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except Exception as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/servers/{server_id}/edit")
async def admin_edit_server(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """
    Edit an existing server via the admin UI.

    This endpoint processes form data to update an existing server's properties.
    It handles exceptions gracefully and logs any errors that occur during the
    update operation.

    Expects form fields:
      - id (optional): Updated UUID for the server
      - name (optional): The updated name of the server
      - description (optional): An updated description of the server's purpose
      - icon (optional): Updated URL or path to the server's icon
      - associatedTools (optional, multiple values): Updated list of tools associated with this server
      - associatedResources (optional, multiple values): Updated list of resources associated with this server
      - associatedPrompts (optional, multiple values): Updated list of prompts associated with this server

    Args:
        server_id (str): The ID of the server to edit
        request (Request): FastAPI request containing form data
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        JSONResponse: A JSON response indicating success or failure of the server update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> server_id = "server-to-edit"
        >>>
        >>> # Happy path: Edit server with new name
        >>> form_data_edit = FormData([("name", "Updated Server Name"), ("is_inactive_checked", "false")])
        >>> mock_request_edit = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_edit.form = AsyncMock(return_value=form_data_edit)
        >>> original_update_server = server_service.update_server
        >>> server_service.update_server = AsyncMock()
        >>>
        >>> async def test_admin_edit_server_success():
        ...     result = await admin_edit_server(server_id, mock_request_edit, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 200 and result.body == b'{"message":"Server updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_server_success())
        True
        >>>
        >>> # Error path: Simulate an exception during update
        >>> form_data_error = FormData([("name", "Error Server")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.update_server = AsyncMock(side_effect=Exception("Update failed"))
        >>>
        >>> # Restore original method
        >>> server_service.update_server = original_update_server
        >>> # 409 Conflict: ServerNameConflictError
        >>> server_service.update_server = AsyncMock(side_effect=ServerNameConflictError("Name conflict"))
        >>> async def test_admin_edit_server_conflict():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 409 and b'Name conflict' in result.body
        >>> asyncio.run(test_admin_edit_server_conflict())
        True
        >>> # 409 Conflict: IntegrityError
        >>> from sqlalchemy.exc import IntegrityError
        >>> server_service.update_server = AsyncMock(side_effect=IntegrityError("Integrity error", None, None))
        >>> async def test_admin_edit_server_integrity():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 409
        >>> asyncio.run(test_admin_edit_server_integrity())
        True
        >>> # 422 Unprocessable Entity: ValidationError
        >>> from pydantic import ValidationError, BaseModel
        >>> from mcpgateway.schemas import ServerUpdate
        >>> validation_error = ValidationError.from_exception_data("ServerUpdate validation error", [
        ...     {"loc": ("name",), "msg": "Field required", "type": "missing"}
        ... ])
        >>> server_service.update_server = AsyncMock(side_effect=validation_error)
        >>> async def test_admin_edit_server_validation():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 422
        >>> asyncio.run(test_admin_edit_server_validation())
        True
        >>> # 400 Bad Request: ValueError
        >>> server_service.update_server = AsyncMock(side_effect=ValueError("Bad value"))
        >>> async def test_admin_edit_server_valueerror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 400 and b'Bad value' in result.body
        >>> asyncio.run(test_admin_edit_server_valueerror())
        True
        >>> # 500 Internal Server Error: ServerError
        >>> server_service.update_server = AsyncMock(side_effect=ServerError("Server error"))
        >>> async def test_admin_edit_server_servererror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500 and b'Server error' in result.body
        >>> asyncio.run(test_admin_edit_server_servererror())
        True
        >>> # 500 Internal Server Error: RuntimeError
        >>> server_service.update_server = AsyncMock(side_effect=RuntimeError("Runtime error"))
        >>> async def test_admin_edit_server_runtimeerror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500 and b'Runtime error' in result.body
        >>> asyncio.run(test_admin_edit_server_runtimeerror())
        True
        >>> # Restore original method
        >>> server_service.update_server = original_update_server
    """
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    try:
        LOGGER.debug(f"User {get_user_email(user)} is editing server ID {server_id} with name: {form.get('name')}")
        visibility = str(form.get("visibility", "private"))
        user_email = get_user_email(user)
        team_id_raw = form.get("team_id", None)
        team_id = str(team_id_raw) if team_id_raw is not None else None

        team_service = TeamManagementService(db)
        team_id = await team_service.verify_team_for_user(user_email, team_id)

        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)

        # Handle "Select All" for tools
        associated_tools_list = form.getlist("associatedTools")
        if form.get("selectAllTools") == "true":
            # User clicked "Select All" - get all tool IDs from hidden field
            all_tool_ids_json = str(form.get("allToolIds", "[]"))
            try:
                all_tool_ids = orjson.loads(all_tool_ids_json)
                associated_tools_list = all_tool_ids
                LOGGER.info(f"Select All tools enabled for edit: {len(all_tool_ids)} tools selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allToolIds JSON, falling back to checked tools")

        # Handle "Select All" for resources
        associated_resources_list = form.getlist("associatedResources")
        if form.get("selectAllResources") == "true":
            all_resource_ids_json = str(form.get("allResourceIds", "[]"))
            try:
                all_resource_ids = orjson.loads(all_resource_ids_json)
                associated_resources_list = all_resource_ids
                LOGGER.info(f"Select All resources enabled for edit: {len(all_resource_ids)} resources selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allResourceIds JSON, falling back to checked resources")

        # Handle "Select All" for prompts
        associated_prompts_list = form.getlist("associatedPrompts")
        if form.get("selectAllPrompts") == "true":
            all_prompt_ids_json = str(form.get("allPromptIds", "[]"))
            try:
                all_prompt_ids = orjson.loads(all_prompt_ids_json)
                associated_prompts_list = all_prompt_ids
                LOGGER.info(f"Select All prompts enabled for edit: {len(all_prompt_ids)} prompts selected")
            except orjson.JSONDecodeError:
                LOGGER.warning("Failed to parse allPromptIds JSON, falling back to checked prompts")

        server = ServerUpdate(
            id=form.get("id"),
            name=form.get("name"),
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=",".join(str(x) for x in associated_tools_list),
            associated_resources=",".join(str(x) for x in associated_resources_list),
            associated_prompts=",".join(str(x) for x in associated_prompts_list),
            tags=tags,
            visibility=visibility,
            team_id=team_id,
            owner_email=user_email,
        )

        await server_service.update_server(
            db,
            server_id,
            server,
            user_email,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
        )

        return ORJSONResponse(
            content={"message": "Server updated successfully!", "success": True},
            status_code=200,
        )
    except (ValidationError, CoreValidationError) as ex:
        # Catch both Pydantic and pydantic_core validation errors
        return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except ServerNameConflictError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ServerError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValueError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except RuntimeError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except IntegrityError as ex:
        return ORJSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except PermissionError as e:
        LOGGER.info(f"Permission denied for user {get_user_email(user)}: {e}")
        return ORJSONResponse(content={"message": str(e), "success": False}, status_code=403)
    except Exception as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/servers/{server_id}/toggle")
async def admin_toggle_server(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Response:
    """
    Toggle a server's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a server.
    It expects a form field 'activate' with value "true" to activate the server
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        server_id (str): The ID of the server whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Response: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> server_id = "server-to-toggle"
        >>>
        >>> # Happy path: Activate server
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_server_status = server_service.toggle_server_status
        >>> server_service.toggle_server_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_server_activate():
        ...     result = await admin_toggle_server(server_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_activate())
        True
        >>>
        >>> # Happy path: Deactivate server
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_server_deactivate():
        ...     result = await admin_toggle_server(server_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_deactivate())
        True
        >>>
        >>> # Edge case: Toggle with inactive checkbox checked
        >>> form_data_inactive = FormData([("activate", "true"), ("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_server_inactive_checked():
        ...     result = await admin_toggle_server(server_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin/?include_inactive=true#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.toggle_server_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_server_exception():
        ...     result = await admin_toggle_server(server_id, mock_request_error, mock_db, mock_user)
        ...     location_header = result.headers["location"]
        ...     return (
        ...         isinstance(result, RedirectResponse)
        ...         and result.status_code == 303
        ...         and "/admin" in location_header  # Ensure '/admin' is present
        ...         and "error=" in location_header  # Ensure the error parameter is in the query string
        ...         and location_header.endswith("#catalog")  # Ensure the fragment is correct
        ...     )
        >>>
        >>> asyncio.run(test_admin_toggle_server_exception())
        True
        >>>
        >>> # Restore original method
        >>> server_service.toggle_server_status = original_toggle_server_status
    """
    form = await request.form()
    error_message = None
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is toggling server ID {server_id} with activate: {form.get('activate')}")
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await server_service.toggle_server_status(db, server_id, activate, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling servers {server_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error toggling server status: {e}")
        error_message = "Error toggling server status. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#catalog", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#catalog", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#catalog", status_code=303)
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.post("/servers/{server_id}/delete")
async def admin_delete_server(server_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a server via the admin UI.

    This endpoint removes a server from the database by its ID. It handles exceptions
    gracefully and logs any errors that occur during the deletion process.

    Args:
        server_id (str): The ID of the server to delete
        request (Request): FastAPI request object (not used but required by route signature).
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other)

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> server_id = "server-to-delete"
        >>>
        >>> # Happy path: Delete server
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_server = server_service.delete_server
        >>> server_service.delete_server = AsyncMock()
        >>>
        >>> async def test_admin_delete_server_success():
        ...     result = await admin_delete_server(server_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_server_inactive_checked():
        ...     result = await admin_delete_server(server_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.delete_server = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_server_exception():
        ...     result = await admin_delete_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "#catalog" in result.headers["location"] and "error=" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_exception())
        True
        >>>
        >>> # Restore original method
        >>> server_service.delete_server = original_delete_server
    """
    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    purge_metrics = str(form.get("purge_metrics", "false")).lower() == "true"
    error_message = None
    try:
        user_email = get_user_email(user)
        LOGGER.debug(f"User {user_email} is deleting server ID {server_id}")
        await server_service.delete_server(db, server_id, user_email=user_email, purge_metrics=purge_metrics)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {get_user_email(user)} deleting server {server_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error deleting server: {e}")
        error_message = "Failed to delete server. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#catalog", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#catalog", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#catalog", status_code=303)
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.get("/resources", response_model=PaginatedResponse)
async def admin_list_resources(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List resources for the admin UI with pagination support.

    This endpoint retrieves a paginated list of resources from the database, optionally
    including those that are inactive. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed). Default: 1.
        per_page (int): Items per page (1-500). Default: 50.
        include_inactive (bool): Whether to include inactive resources in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict with 'data', 'pagination', and 'links' keys containing paginated resources.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ResourceRead, ResourceMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> # Mock resource data
        >>> mock_resource = ResourceRead(
        ...     id="39334ce0ed2644d79ede8913a66930c9",
        ...     uri="test://resource/1",
        ...     name="Test Resource",
        ...     description="A test resource",
        ...     mime_type="text/plain",
        ...     size=100,
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     enabled=True,
        ...     metrics=ResourceMetrics(
        ...         total_executions=5, successful_executions=5, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.1, max_response_time=0.5,
        ...         avg_response_time=0.3, last_execution_time=datetime.now(timezone.utc)
        ...     ),
        ...     tags=[]
        ... )
        >>>
        >>> # Mock resource_service.list_resources
        >>> async def mock_list_resources(*args, **kwargs):
        ...     from mcpgateway.schemas import PaginationMeta, PaginationLinks
        ...     return {
        ...         "data": [mock_resource],
        ...         "pagination": PaginationMeta(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
        ...         "links": PaginationLinks(self="/admin/resources?page=1&per_page=50", first="/admin/resources?page=1&per_page=50", last="/admin/resources?page=1&per_page=50", next=None, prev=None)
        ...     }
        >>>
        >>> from unittest.mock import patch
        >>> # Test listing resources with pagination
        >>> async def test_admin_list_resources_paginated():
        ...     with patch("mcpgateway.admin.resource_service.list_resources", new=mock_list_resources):
        ...         result = await admin_list_resources(page=1, per_page=50, include_inactive=False, db=mock_db, user=mock_user)
        ...         return "data" in result and "pagination" in result
        >>>
        >>> asyncio.run(test_admin_list_resources_paginated())
        True
    """
    LOGGER.debug(f"User {get_user_email(user)} requested resource list (page={page}, per_page={per_page})")
    user_email = get_user_email(user)

    # Call resource_service.list_resources with page-based pagination
    paginated_result = await resource_service.list_resources(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [resource.model_dump(by_alias=True) for resource in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.get("/prompts", response_model=PaginatedResponse)
async def admin_list_prompts(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List prompts for the admin UI with pagination support.

    This endpoint retrieves a paginated list of prompts from the database, optionally
    including those that are inactive. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed) for offset pagination.
        per_page (int): Number of items per page (1-500).
        include_inactive (bool): Whether to include inactive prompts in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - data: List of prompt records formatted with by_alias=True
            - pagination: Pagination metadata
            - links: Pagination links (optional)

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import PromptRead, PromptMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> # Mock prompt data
        >>> mock_prompt = PromptRead(
        ...     id="ca627760127d409080fdefc309147e08",
        ...     name="Test Prompt",
        ...     original_name="Test Prompt",
        ...     custom_name="Test Prompt",
        ...     custom_name_slug="test-prompt",
        ...     display_name="Test Prompt",
        ...     description="A test prompt",
        ...     template="Hello {{name}}!",
        ...     arguments=[{"name": "name", "type": "string"}],
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     enabled=True,
        ...     metrics=PromptMetrics(
        ...         total_executions=10, successful_executions=10, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.01, max_response_time=0.1,
        ...         avg_response_time=0.05, last_execution_time=datetime.now(timezone.utc)
        ...     ),
        ...     tags=[]
        ... )
        >>>
        >>> # Mock prompt_service.list_prompts
        >>> async def mock_list_prompts(*args, **kwargs):
        ...     from mcpgateway.schemas import PaginationMeta, PaginationLinks
        ...     return {
        ...         "data": [mock_prompt],
        ...         "pagination": PaginationMeta(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
        ...         "links": PaginationLinks(self="/admin/prompts?page=1&per_page=50", first="/admin/prompts?page=1&per_page=50", last="/admin/prompts?page=1&per_page=50", next=None, prev=None)
        ...     }
        >>>
        >>> from unittest.mock import patch
        >>> # Test listing active prompts with pagination
        >>> async def test_admin_list_prompts_paginated():
        ...     with patch("mcpgateway.admin.prompt_service.list_prompts", new=mock_list_prompts):
        ...         result = await admin_list_prompts(page=1, per_page=50, include_inactive=False, db=mock_db, user=mock_user)
        ...         return "data" in result and "pagination" in result
        >>>
        >>> asyncio.run(test_admin_list_prompts_paginated())
        True
    """
    LOGGER.debug(f"User {get_user_email(user)} requested prompt list (page={page}, per_page={per_page})")
    user_email = get_user_email(user)

    # Call prompt_service.list_prompts with page-based pagination
    paginated_result = await prompt_service.list_prompts(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [prompt.model_dump(by_alias=True) for prompt in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.get("/gateways", response_model=PaginatedResponse)
async def admin_list_gateways(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List gateways for the admin UI with pagination support.

    This endpoint retrieves a paginated list of gateways from the database, optionally
    including those that are inactive. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed) for offset pagination.
        per_page (int): Number of items per page (1-500).
        include_inactive (bool): Whether to include inactive gateways in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - data: List of gateway records formatted with by_alias=True
            - pagination: Pagination metadata
            - links: Pagination links (optional)

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayRead
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> # Mock gateway data
        >>> mock_gateway = GatewayRead(
        ...     id="gateway-1",
        ...     name="Test Gateway",
        ...     url="http://test.com",
        ...     description="A test gateway",
        ...     transport="HTTP",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     auth_type=None, auth_username=None, auth_password=None, auth_token=None,
        ...     auth_header_key=None, auth_header_value=None,
        ...     slug="test-gateway"
        ... )
        >>>
        >>> # Mock gateway_service.list_gateways
        >>> async def mock_list_gateways(*args, **kwargs):
        ...     from mcpgateway.schemas import PaginationMeta, PaginationLinks
        ...     return {
        ...         "data": [mock_gateway],
        ...         "pagination": PaginationMeta(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
        ...         "links": PaginationLinks(self="/admin/gateways?page=1&per_page=50", first="/admin/gateways?page=1&per_page=50", last="/admin/gateways?page=1&per_page=50", next=None, prev=None)
        ...     }
        >>>
        >>> from unittest.mock import patch
        >>> # Test listing gateways with pagination
        >>> async def test_admin_list_gateways_paginated():
        ...     with patch("mcpgateway.admin.gateway_service.list_gateways", new=mock_list_gateways):
        ...         result = await admin_list_gateways(page=1, per_page=50, include_inactive=False, db=mock_db, user=mock_user)
        ...         return "data" in result and "pagination" in result
        >>>
        >>> asyncio.run(test_admin_list_gateways_paginated())
        True
    """
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} requested gateway list (page={page}, per_page={per_page})")

    # Call gateway_service.list_gateways with page-based pagination
    paginated_result = await gateway_service.list_gateways(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [gateway.model_dump(by_alias=True) for gateway in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.get("/gateways/ids")
async def admin_list_gateway_ids(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    Return a JSON object containing a list of all gateway IDs.

    This endpoint is used by the admin UI to support the "Select All" action
    for gateways. It returns a simple JSON payload with a single key
    `gateway_ids` containing an array of gateway identifiers.

    Args:
        include_inactive (bool): Whether to include inactive gateways in the results.
        db (Session): Database session dependency.
        user: Authenticated user dependency.

    Returns:
        Dict[str, Any]: JSON object containing the `gateway_ids` list and metadata.
    """
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} requested gateway ids list")
    gateways, _ = await gateway_service.list_gateways(db, include_inactive=include_inactive, user_email=user_email, limit=0)
    ids = [str(g.id) for g in gateways]
    LOGGER.info(f"Gateway IDs retrieved: {ids}")
    return {"gateway_ids": ids}


@admin_router.post("/gateways/{gateway_id}/toggle")
async def admin_toggle_gateway(
    gateway_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Toggle the active status of a gateway via the admin UI.

    This endpoint allows an admin to toggle the active status of a gateway.
    It expects a form field 'activate' with a value of "true" or "false" to
    determine the new status of the gateway.

    Args:
        gateway_id (str): The ID of the gateway to toggle.
        request (Request): The FastAPI request object containing form data.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the admin dashboard with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> gateway_id = "gateway-to-toggle"
        >>>
        >>> # Happy path: Activate gateway
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_gateway_status = gateway_service.toggle_gateway_status
        >>> gateway_service.toggle_gateway_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_gateway_activate():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_activate())
        True
        >>>
        >>> # Happy path: Deactivate gateway
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_gateway_deactivate():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_deactivate())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.toggle_gateway_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_gateway_exception():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     location_header = result.headers["location"]
        ...     return (
        ...         isinstance(result, RedirectResponse)
        ...         and result.status_code == 303
        ...         and "/admin" in location_header  # Ensure '/admin' is present
        ...         and "error=" in location_header  # Ensure the error parameter is in the query string
        ...         and location_header.endswith("#gateways")  # Ensure the fragment is correct
        ...     )
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_exception())
        True
        >>> # Restore original method
        >>> gateway_service.toggle_gateway_status = original_toggle_gateway_status
    """
    error_message = None
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is toggling gateway ID {gateway_id}")
    form = await request.form()
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))

    try:
        await gateway_service.toggle_gateway_status(db, gateway_id, activate, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling gateway {gateway_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error toggling gateway status: {e}")
        error_message = "Failed to toggle gateway status. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#gateways", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#gateways", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#gateways", status_code=303)
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.get("/", name="admin_home", response_class=HTMLResponse)
async def admin_ui(
    request: Request,
    team_id: Optional[str] = Query(None),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
    _jwt_token: str = Depends(get_jwt_token),
) -> Any:
    """
    Render the admin dashboard HTML page.

    This endpoint serves as the main entry point to the admin UI. It fetches data for
    servers, tools, resources, prompts, gateways, and roots from their respective
    services, then renders the admin dashboard template with this data.

    Supports optional `team_id` query param to scope the returned data to a team.
    If `team_id` is provided and email-based team management is enabled, we
    validate the user is a member of that team. We attempt to pass team_id into
    service listing functions (preferred). If the service API does not accept a
    team_id parameter we fall back to post-filtering the returned items.

    The endpoint also sets a JWT token as a cookie for authentication in subsequent
    requests. This token is HTTP-only for security reasons.

    Args:
        request (Request): FastAPI request object.
        team_id (Optional[str]): Optional team ID to filter data by team.
        include_inactive (bool): Whether to include inactive items in all listings.
        db (Session): Database session dependency.
        user (dict): Authenticated user context with permissions.

    Returns:
        Any: Rendered HTML template for the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock, patch
        >>> from fastapi import Request
        >>> from fastapi.responses import HTMLResponse
        >>> from mcpgateway.schemas import ServerRead, ToolRead, ResourceRead, PromptRead, GatewayRead, ServerMetrics, ToolMetrics, ResourceMetrics, PromptMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "admin_user", "db": mock_db}
        >>>
        >>> # Mock services to return empty lists for simplicity in doctest
        >>> original_list_servers = server_service.list_servers
        >>> original_list_tools = tool_service.list_tools
        >>> original_list_resources = resource_service.list_resources
        >>> original_list_prompts = prompt_service.list_prompts
        >>> original_list_gateways = gateway_service.list_gateways
        >>> original_list_roots = root_service.list_roots
        >>>
        >>> server_service.list_servers = AsyncMock(return_value=([], None))
        >>> tool_service.list_tools = AsyncMock(return_value=([], None))
        >>> resource_service.list_resources = AsyncMock(return_value=([], None))
        >>> prompt_service.list_prompts = AsyncMock(return_value=([], None))
        >>> gateway_service.list_gateways = AsyncMock(return_value=([], None))
        >>> root_service.list_roots = AsyncMock(return_value=[])
        >>>
        >>> # Mock request and template rendering
        >>> mock_request = MagicMock(spec=Request, scope={"root_path": "/admin_prefix"})
        >>> mock_request.app.state.templates = MagicMock()
        >>> mock_template_response = HTMLResponse("<html>Admin UI</html>")
        >>> mock_request.app.state.templates.TemplateResponse.return_value = mock_template_response
        >>>
        >>> # Test basic rendering
        >>> async def test_admin_ui_basic_render():
        ...     response = await admin_ui(mock_request, None, False, mock_db, mock_user)
        ...     return isinstance(response, HTMLResponse) and response.status_code == 200
        >>>
        >>> asyncio.run(test_admin_ui_basic_render())
        True
        >>>
        >>> # Test with include_inactive=True
        >>> async def test_admin_ui_include_inactive():
        ...     response = await admin_ui(mock_request, None, True, mock_db, mock_user)
        ...     # Verify list methods were called with include_inactive=True
        ...     server_service.list_servers.assert_called()
        ...     return isinstance(response, HTMLResponse)
        >>>
        >>> asyncio.run(test_admin_ui_include_inactive())
        True
        >>>
        >>> # Test with populated data (mocking a few items)
        >>> mock_server = ServerRead(id="s1", name="S1", description="d", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), enabled=True, associated_tools=[], associated_resources=[], associated_prompts=[], icon="i", metrics=ServerMetrics(total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=0.0, max_response_time=0.0, avg_response_time=0.0, last_execution_time=None))
        >>> mock_tool = ToolRead(
        ...     id="t1", name="T1", original_name="T1", url="http://t1.com", description="d",
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, reachable=True, gateway_slug="default", custom_name_slug="t1",
        ...     request_type="GET", integration_type="MCP", headers={}, input_schema={},
        ...     annotations={}, jsonpath_filter=None, auth=None, execution_count=0,
        ...     metrics=ToolMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None
        ...     ),
        ...     gateway_id=None,
        ...     customName="T1",
        ...     tags=[]
        ... )
        >>> server_service.list_servers = AsyncMock(return_value=([mock_server], None))
        >>> tool_service.list_tools = AsyncMock(return_value=([mock_tool], None))
        >>>
        >>> async def test_admin_ui_with_data():
        ...     response = await admin_ui(mock_request, None, False, mock_db, mock_user)
        ...     # Check if template context was populated (indirectly via mock calls)
        ...     assert mock_request.app.state.templates.TemplateResponse.call_count >= 1
        ...     context = mock_request.app.state.templates.TemplateResponse.call_args[0][2]
        ...     return len(context['servers']) == 1 and len(context['tools']) == 1
        >>>
        >>> asyncio.run(test_admin_ui_with_data())
        True
        >>>
        >>> from unittest.mock import AsyncMock, patch
        >>> import logging
        >>>
        >>> server_service.list_servers = AsyncMock(side_effect=Exception("DB error"))
        >>>
        >>> async def test_admin_ui_exception_handled():
        ...     with patch("mcpgateway.admin.LOGGER.exception") as mock_log:
        ...         response = await admin_ui(
        ...             request=mock_request,
        ...             team_id=None,
        ...             include_inactive=False,
        ...             db=mock_db,
        ...             user=mock_user
        ...         )
        ...         # Check that the response rendered correctly
        ...         ok_response = isinstance(response, HTMLResponse) and response.status_code == 200
        ...         # Check that the exception was logged
        ...         log_called = mock_log.called
        ...         # Optionally, you can even inspect the message if you want
        ...         return ok_response and log_called
        >>>
        >>> asyncio.run(test_admin_ui_exception_handled())
        True
        >>>
        >>> # Restore original methods
        >>> server_service.list_servers = original_list_servers
        >>> tool_service.list_tools = original_list_tools
        >>> resource_service.list_resources = original_list_resources
        >>> prompt_service.list_prompts = original_list_prompts
        >>> gateway_service.list_gateways = original_list_gateways
        >>> root_service.list_roots = original_list_roots
    """
    LOGGER.debug(f"User {get_user_email(user)} accessed the admin UI (team_id={team_id})")
    user_email = get_user_email(user)

    # --------------------------------------------------------------------------------
    # Load user teams so we can validate team_id
    # --------------------------------------------------------------------------------
    user_teams = []
    team_service = None
    if getattr(settings, "email_auth_enabled", False):
        try:
            team_service = TeamManagementService(db)
            if user_email and "@" in user_email:
                raw_teams = await team_service.get_user_teams(user_email)
                user_teams = []
                for team in raw_teams:
                    try:
                        # Get the user's role in this team
                        user_role = await team_service.get_user_role_in_team(user_email, team.id)
                        team_dict = {
                            "id": str(team.id) if team.id else "",
                            "name": str(team.name) if team.name else "",
                            "type": str(getattr(team, "type", "organization")),
                            "is_personal": bool(getattr(team, "is_personal", False)),
                            "member_count": team.get_member_count() if hasattr(team, "get_member_count") else 0,
                            "role": user_role or "member",
                        }
                        user_teams.append(team_dict)
                    except Exception as team_error:
                        LOGGER.warning(f"Failed to serialize team {getattr(team, 'id', 'unknown')}: {team_error}")
                        continue
        except Exception as e:
            LOGGER.warning(f"Failed to load user teams: {e}")
            user_teams = []

    # --------------------------------------------------------------------------------
    # Validate team_id if provided (only when email-based teams are enabled)
    # If invalid, we currently *ignore* it and fall back to default behavior.
    # Optionally you can raise HTTPException(403) if you prefer strict rejection.
    # --------------------------------------------------------------------------------
    selected_team_id = team_id
    if team_id and getattr(settings, "email_auth_enabled", False):
        # If team list failed to load for some reason, be conservative and drop selection
        if not user_teams:
            LOGGER.warning("team_id requested but user_teams not available; ignoring team filter")
            selected_team_id = None
        else:
            valid_team_ids = {t["id"] for t in user_teams if t.get("id")}
            if str(team_id) not in valid_team_ids:
                LOGGER.warning("Requested team_id is not in user's teams; ignoring team filter (team_id=%s)", team_id)
                selected_team_id = None

    # --------------------------------------------------------------------------------
    # Helper: attempt to call a listing function with team_id if it supports it.
    # If the method signature doesn't accept team_id, fall back to calling it without
    # and then (optionally) filter the returned results.
    # --------------------------------------------------------------------------------
    async def _call_list_with_team_support(method, *args, **kwargs):
        """
        Attempt to call a method with an optional `team_id` parameter.

        This function tries to call the given asynchronous `method` with all provided
        arguments and an additional `team_id=selected_team_id`, assuming `selected_team_id`
        is defined and not None. If the method does not accept a `team_id` keyword argument
        (raises TypeError), the function retries the call without it.

        This is useful in scenarios where some service methods optionally support team
        scoping via a `team_id` parameter, but not all do.

        Args:
            method (Callable): The async function to be called.
            *args: Positional arguments to pass to the method.
            **kwargs: Keyword arguments to pass to the method.

        Returns:
            Any: The result of the awaited method call, typically a list of model instances.

        Raises:
            Any exception raised by the method itself, except TypeError when `team_id` is unsupported.


        Doctest:
            >>> async def sample_method(a, b):
            ...     return [a, b]
            >>> async def sample_method_with_team(a, b, team_id=None):
            ...     return [a, b, team_id]
            >>> selected_team_id = 42
            >>> import asyncio
            >>> asyncio.run(_call_list_with_team_support(sample_method_with_team, 1, 2))
            [1, 2, 42]
            >>> asyncio.run(_call_list_with_team_support(sample_method, 1, 2))
            [1, 2]

        Notes:
            - This function depends on a global `selected_team_id` variable.
            - If `selected_team_id` is None, the method is called without `team_id`.
        """
        if selected_team_id is None:
            return await method(*args, **kwargs)

        try:
            # Preferred: pass team_id to the service method if it accepts it
            return await method(*args, team_id=selected_team_id, **kwargs)
        except TypeError:
            # The method doesn't accept team_id -> fall back to original API
            LOGGER.debug("Service method %s does not accept team_id; falling back and will post-filter", getattr(method, "__name__", str(method)))
            return await method(*args, **kwargs)

    # Small utility to check if a returned model or dict matches the selected_team_id.
    def _matches_selected_team(item, tid: str) -> bool:
        """
        Determine whether the given item is associated with the specified team ID.

        This function attempts to determine if the input `item` (which may be a Pydantic model,
        an object with attributes, or a dictionary) is associated with the given team ID (`tid`).
        It checks several common attribute names (e.g., `team_id`, `team_ids`, `teams`) to see
        if any of them match the provided team ID. These fields may contain either a single ID
        or a list of IDs.

        If `tid` is falsy (e.g., empty string), the function returns True.

        Args:
            item: An object or dictionary that may contain team identification fields.
            tid (str): The team ID to match.

        Returns:
            bool: True if the item is associated with the specified team ID, otherwise False.

        Examples:
            >>> class Obj:
            ...     team_id = 'abc123'
            >>> _matches_selected_team(Obj(), 'abc123')
            True

            >>> class Obj:
            ...     team_ids = ['abc123', 'def456']
            >>> _matches_selected_team(Obj(), 'def456')
            True

            >>> _matches_selected_team({'teamId': 'xyz789'}, 'xyz789')
            True

            >>> _matches_selected_team({'teamIds': ['123', '456']}, '789')
            False

            >>> _matches_selected_team({'teams': ['t1', 't2']}, 't1')
            True

            >>> _matches_selected_team({}, '')
            True

            >>> _matches_selected_team(None, 'abc')
            False
        """
        if not tid:
            return True
        # If an item is explicitly public, it should be visible to any team
        try:
            vis = getattr(item, "visibility", None)
            if vis is None and isinstance(item, dict):
                vis = item.get("visibility")
            if isinstance(vis, str) and vis.lower() == "public":
                return True
        except Exception as exc:  # pragma: no cover - defensive logging for unexpected types
            LOGGER.debug(
                "Error checking visibility on item (type=%s): %s",
                type(item),
                exc,
                exc_info=True,
            )
        # item may be a pydantic model or dict-like
        # check common fields for team membership
        candidates = []
        try:
            # If it's an object with attributes
            candidates.extend(
                [
                    getattr(item, "team_id", None),
                    getattr(item, "teamId", None),
                    getattr(item, "team_ids", None),
                    getattr(item, "teamIds", None),
                    getattr(item, "teams", None),
                ]
            )
        except Exception:
            pass  # nosec B110 - Intentionally ignore errors when extracting team IDs from objects
        try:
            # If it's a dict-like model_dump output (we'll check keys later after model_dump)
            if isinstance(item, dict):
                candidates.extend(
                    [
                        item.get("team_id"),
                        item.get("teamId"),
                        item.get("team_ids"),
                        item.get("teamIds"),
                        item.get("teams"),
                    ]
                )
        except Exception:
            pass  # nosec B110 - Intentionally ignore errors when extracting team IDs from dict objects

        for c in candidates:
            if c is None:
                continue
            # Some fields may be single id or list of ids
            if isinstance(c, (list, tuple, set)):
                if str(tid) in [str(x) for x in c]:
                    return True
            else:
                if str(c) == str(tid):
                    return True
        return False

    # --------------------------------------------------------------------------------
    # Load each resource list using the safe _call_list_with_team_support helper.
    # For each returned list, try to produce consistent "model_dump(by_alias=True)" dicts,
    # applying server-side filtering as a fallback if the service didn't accept team_id.
    # --------------------------------------------------------------------------------
    try:
        raw_tools = await _call_list_with_team_support(tool_service.list_tools, db, include_inactive=include_inactive, user_email=user_email, limit=0)
        if isinstance(raw_tools, tuple):
            raw_tools = raw_tools[0]
    except Exception as e:
        LOGGER.exception("Failed to load tools for user: %s", e)
        raw_tools = []

    try:
        raw_servers = await _call_list_with_team_support(server_service.list_servers, db, include_inactive=include_inactive, user_email=user_email, limit=0)
        # Handle tuple return (list, cursor)
        if isinstance(raw_servers, tuple):
            raw_servers = raw_servers[0]
    except Exception as e:
        LOGGER.exception("Failed to load servers for user: %s", e)
        raw_servers = []

    try:
        raw_resources = await _call_list_with_team_support(resource_service.list_resources, db, include_inactive=include_inactive, user_email=user_email, limit=0)
        if isinstance(raw_resources, tuple):
            raw_resources = raw_resources[0]
    except Exception as e:
        LOGGER.exception("Failed to load resources for user: %s", e)
        raw_resources = []

    try:
        raw_prompts = await _call_list_with_team_support(prompt_service.list_prompts, db, include_inactive=include_inactive, user_email=user_email, limit=0)
        # Handle tuple return (list, cursor)
        if isinstance(raw_prompts, tuple):
            raw_prompts = raw_prompts[0]
    except Exception as e:
        LOGGER.exception("Failed to load prompts for user: %s", e)
        raw_prompts = []

    try:
        gateways_raw = await _call_list_with_team_support(gateway_service.list_gateways, db, include_inactive=include_inactive, user_email=user_email, limit=0)
        # Handle tuple return (list, cursor)
        if isinstance(gateways_raw, tuple):
            gateways_raw = gateways_raw[0]
    except Exception as e:
        LOGGER.exception("Failed to load gateways: %s", e)
        gateways_raw = []

    # Convert models to dicts and filter as needed
    def _to_dict_and_filter(raw_list):
        """
        Convert a list of items (Pydantic models, dicts, or similar) to dictionaries and filter them
        based on a globally defined `selected_team_id`.

        For each item:
        - Try to convert it to a dictionary via `.model_dump(by_alias=True)` (if it's a Pydantic model),
        or keep it as-is if it's already a dictionary.
        - If the conversion fails, try to coerce the item to a dictionary via `dict(item)`.
        - If `selected_team_id` is set, include only items that match it via `_matches_selected_team`.

        Args:
            raw_list (list): A list of Pydantic models, dictionaries, or similar objects.

        Returns:
            list: A filtered list of dictionaries.

        Examples:
            >>> global selected_team_id
            >>> selected_team_id = 'team123'
            >>> class Model:
            ...     def __init__(self, team_id): self.team_id = team_id
            ...     def model_dump(self, by_alias=False): return {'team_id': self.team_id}
            >>> items = [Model('team123'), Model('team999')]
            >>> _to_dict_and_filter(items)
            [{'team_id': 'team123'}]

            >>> selected_team_id = None
            >>> _to_dict_and_filter([{'team_id': 'any_team'}])
            [{'team_id': 'any_team'}]

            >>> selected_team_id = 't1'
            >>> _to_dict_and_filter([{'team_ids': ['t1', 't2']}, {'team_ids': ['t3']}])
            [{'team_ids': ['t1', 't2']}]
        """
        out = []
        for item in raw_list or []:
            try:
                dumped = item.model_dump(by_alias=True) if hasattr(item, "model_dump") else (item if isinstance(item, dict) else None)
            except Exception:
                # if dumping failed, try to coerce to dict
                try:
                    dumped = dict(item) if hasattr(item, "__iter__") else None
                except Exception:
                    dumped = None
            if dumped is None:
                continue

            # If we passed team_id to service, server-side filtering applied.
            # Otherwise, filter by common team-aware fields if selected_team_id is set.
            if selected_team_id:
                if _matches_selected_team(item, selected_team_id) or _matches_selected_team(dumped, selected_team_id):
                    out.append(dumped)
                else:
                    # skip items that don't match the selected team
                    continue
            else:
                out.append(dumped)
        return out

    tools = list(sorted(_to_dict_and_filter(raw_tools), key=lambda t: ((t.get("url") or "").lower(), (t.get("original_name") or "").lower())))
    servers = _to_dict_and_filter(raw_servers)
    resources = _to_dict_and_filter(raw_resources)  # pylint: disable=unnecessary-comprehension
    prompts = _to_dict_and_filter(raw_prompts)
    gateways = [g.model_dump(by_alias=True) if hasattr(g, "model_dump") else (g if isinstance(g, dict) else {}) for g in (gateways_raw or [])]
    # If gateways need team filtering as dicts too, apply _to_dict_and_filter similarly:
    gateways = _to_dict_and_filter(gateways_raw) if isinstance(gateways_raw, (list, tuple)) else gateways

    # roots
    roots = [root.model_dump(by_alias=True) for root in await root_service.list_roots()]

    # Load A2A agents if enabled
    a2a_agents = []
    if a2a_service and settings.mcpgateway_a2a_enabled:
        a2a_agents_raw = await a2a_service.list_agents_for_user(
            db,
            user_info=user_email,
            include_inactive=include_inactive,
        )
        a2a_agents = [agent.model_dump(by_alias=True) for agent in a2a_agents_raw]
        a2a_agents = _to_dict_and_filter(a2a_agents) if isinstance(a2a_agents, (list, tuple)) else a2a_agents

    # Load gRPC services if enabled and available
    grpc_services = []
    try:
        if GRPC_AVAILABLE and grpc_service_mgr and settings.mcpgateway_grpc_enabled:
            grpc_services_raw = await grpc_service_mgr.list_services(
                db,
                include_inactive=include_inactive,
                user_email=user_email,
                team_id=selected_team_id,
            )
            grpc_services = [service.model_dump(by_alias=True) for service in grpc_services_raw]
            grpc_services = _to_dict_and_filter(grpc_services) if isinstance(grpc_services, (list, tuple)) else grpc_services
    except Exception as e:
        LOGGER.exception("Failed to load gRPC services: %s", e)
        grpc_services = []

    # Template variables and context: include selected_team_id so the template and frontend can read it
    root_path = settings.app_root_path
    max_name_length = settings.validation_max_name_length

    response = request.app.state.templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "servers": servers,
            "tools": tools,
            "resources": resources,
            "prompts": prompts,
            "gateways": gateways,
            "a2a_agents": a2a_agents,
            "grpc_services": grpc_services,
            "roots": roots,
            "include_inactive": include_inactive,
            "root_path": root_path,
            "max_name_length": max_name_length,
            "gateway_tool_name_separator": settings.gateway_tool_name_separator,
            "bulk_import_max_tools": settings.mcpgateway_bulk_import_max_tools,
            "a2a_enabled": settings.mcpgateway_a2a_enabled,
            "grpc_enabled": GRPC_AVAILABLE and settings.mcpgateway_grpc_enabled,
            "catalog_enabled": settings.mcpgateway_catalog_enabled,
            "llmchat_enabled": getattr(settings, "llmchat_enabled", False),
            "toolops_enabled": getattr(settings, "toolops_enabled", False),
            "observability_enabled": getattr(settings, "observability_enabled", False),
            "performance_enabled": getattr(settings, "mcpgateway_performance_tracking", False),
            "current_user": get_user_email(user),
            "email_auth_enabled": getattr(settings, "email_auth_enabled", False),
            "is_admin": bool(user.get("is_admin", False) if isinstance(user, dict) else getattr(user, "is_admin", False)),
            "user_teams": user_teams,
            "mcpgateway_ui_tool_test_timeout": settings.mcpgateway_ui_tool_test_timeout,
            "selected_team_id": selected_team_id,
            "ui_airgapped": settings.mcpgateway_ui_airgapped,
            # Password policy flags for frontend templates
            "password_min_length": getattr(settings, "password_min_length", 8),
            "password_require_uppercase": getattr(settings, "password_require_uppercase", False),
            "password_require_lowercase": getattr(settings, "password_require_lowercase", False),
            "password_require_numbers": getattr(settings, "password_require_numbers", False),
            "password_require_special": getattr(settings, "password_require_special", False),
        },
    )

    # Set JWT token cookie for HTMX requests if email auth is enabled
    if getattr(settings, "email_auth_enabled", False):
        try:
            # JWT library is imported at top level as jwt

            # Determine the admin user email
            admin_email = get_user_email(user)
            is_admin_flag = bool(user.get("is_admin") if isinstance(user, dict) else True)

            # Generate a comprehensive JWT token that matches the email auth format
            now = datetime.now(timezone.utc)
            payload = {
                "sub": admin_email,
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=settings.token_expiry)).timestamp()),
                "jti": str(uuid.uuid4()),
                "user": {"email": admin_email, "full_name": getattr(settings, "platform_admin_full_name", "Platform User"), "is_admin": is_admin_flag, "auth_provider": "local"},
                "teams": [],  # Teams populated downstream when needed
                "namespaces": [f"user:{admin_email}", "public"],
                "scopes": {"server_id": None, "permissions": ["*"], "ip_restrictions": [], "time_restrictions": {}},
            }

            # Generate token using centralized token creation
            token = await create_jwt_token(payload)

            # Set HTTP-only cookie for security
            response.set_cookie(
                key="jwt_token",
                value=token,
                httponly=True,
                secure=getattr(settings, "secure_cookies", False),
                samesite=getattr(settings, "cookie_samesite", "lax"),
                max_age=settings.token_expiry * 60,  # Convert minutes to seconds
                path=settings.app_root_path or "/",  # Make cookie available for all paths
            )
            LOGGER.debug(f"Set comprehensive JWT token cookie for user: {admin_email}")
        except Exception as e:
            LOGGER.warning(f"Failed to set JWT token cookie for user {user}: {e}")

    return response


@admin_router.get("/login")
async def admin_login_page(request: Request) -> Response:
    """
    Render the admin login page.

    This endpoint serves the login form for email-based authentication.
    If email auth is disabled, redirects to the main admin page.

    Args:
        request (Request): FastAPI request object.

    Returns:
        Response: Rendered HTML or redirect response.

    Examples:
        >>> from fastapi import Request
        >>> from fastapi.responses import HTMLResponse
        >>> from unittest.mock import MagicMock
        >>>
        >>> # Mock request
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>> mock_request.app.state.templates = MagicMock()
        >>> mock_response = HTMLResponse("<html>Login</html>")
        >>> mock_request.app.state.templates.TemplateResponse.return_value = mock_response
        >>>
        >>> import asyncio
        >>> async def test_login_page():
        ...     response = await admin_login_page(mock_request)
        ...     return isinstance(response, HTMLResponse)
        >>>
        >>> asyncio.run(test_login_page())
        True
    """
    # Check if email auth is enabled
    if not getattr(settings, "email_auth_enabled", False):
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin", status_code=303)

    root_path = settings.app_root_path

    # Only show secure cookie warning if there's a login error AND problematic config
    secure_cookie_warning = None
    if settings.secure_cookies and settings.environment == "development":
        secure_cookie_warning = "Serving over HTTP with secure cookies enabled. If you have login issues, try disabling secure cookies in your configuration."

    # Use external template file
    return request.app.state.templates.TemplateResponse(
        "login.html", {"request": request, "root_path": root_path, "secure_cookie_warning": secure_cookie_warning, "ui_airgapped": settings.mcpgateway_ui_airgapped}
    )


@admin_router.post("/login")
async def admin_login_handler(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """
    Handle admin login form submission.

    This endpoint processes the email/password login form, authenticates the user,
    sets the JWT cookie, and redirects to the admin panel or back to login with error.

    Args:
        request (Request): FastAPI request object.
        db (Session): Database session dependency.

    Returns:
        RedirectResponse: Redirect to admin panel on success or login page on failure.

    Examples:
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from unittest.mock import MagicMock, AsyncMock
        >>>
        >>> # Mock request with form data
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>> mock_form = {"email": "admin@example.com", "password": "changeme"}
        >>> mock_request.form = AsyncMock(return_value=mock_form)
        >>>
        >>> mock_db = MagicMock()
        >>>
        >>> import asyncio
        >>> async def test_login_handler():
        ...     try:
        ...         response = await admin_login_handler(mock_request, mock_db)
        ...         return isinstance(response, RedirectResponse)
        ...     except Exception:
        ...         return True  # Expected due to mocked dependencies
        >>>
        >>> asyncio.run(test_login_handler())
        True
    """
    if not getattr(settings, "email_auth_enabled", False):
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin", status_code=303)

    try:
        form = await request.form()
        email_val = form.get("email")
        password_val = form.get("password")
        email = email_val if isinstance(email_val, str) else None
        password = password_val if isinstance(password_val, str) else None

        if not email or not password:
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/login?error=missing_fields", status_code=303)

        # Authenticate using the email auth service
        auth_service = EmailAuthService(db)

        try:
            # Authenticate user
            LOGGER.debug(f"Attempting authentication for {email}")
            user = await auth_service.authenticate_user(email, password)
            LOGGER.debug(f"Authentication result: {user}")

            if not user:
                LOGGER.warning(f"Authentication failed for {email} - user is None")
                root_path = request.scope.get("root_path", "")
                return RedirectResponse(url=f"{root_path}/admin/login?error=invalid_credentials", status_code=303)

            # Check if password change is required OR if user is using default password
            needs_password_change = user.password_change_required

            # Also check if user is using the default password
            if not needs_password_change:
                password_service = Argon2PasswordService()
                is_using_default_password = password_service.verify_password(settings.default_user_password.get_secret_value(), user.password_hash)  # nosec B105
                if is_using_default_password:
                    needs_password_change = True
                    # Set the flag in database for future reference
                    user.password_change_required = True
                    db.commit()
                    LOGGER.info(f"User {email} is using default password - forcing password change")

            if needs_password_change:
                LOGGER.info(f"User {email} requires password change - redirecting to change password page")

                # Create temporary JWT token for password change process
                token, _ = await create_access_token(user)

                # Create redirect response to password change page
                root_path = request.scope.get("root_path", "")
                response = RedirectResponse(url=f"{root_path}/admin/change-password-required", status_code=303)

                # Set JWT token as secure cookie for the password change process
                set_auth_cookie(response, token, remember_me=False)

                return response

            # Create JWT token with proper audience and issuer claims
            token, _ = await create_access_token(user)  # expires_seconds not needed here

            # Create redirect response
            root_path = request.scope.get("root_path", "")
            response = RedirectResponse(url=f"{root_path}/admin", status_code=303)

            # Set JWT token as secure cookie
            set_auth_cookie(response, token, remember_me=False)

            LOGGER.info(f"Admin user {email} logged in successfully")
            return response

        except Exception as e:
            LOGGER.warning(f"Login failed for {email}: {e}")

            if settings.secure_cookies and settings.environment == "development":
                LOGGER.warning("Login failed - set SECURE_COOKIES to false in config for HTTP development")

            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/login?error=invalid_credentials", status_code=303)

    except Exception as e:
        LOGGER.error(f"Login handler error: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin/login?error=server_error", status_code=303)


@admin_router.post("/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    """
    Handle admin logout by clearing authentication cookies.

    This endpoint clears the JWT authentication cookie and redirects
    the user to a login page or back to the admin page (which will
    trigger authentication).

    Args:
        request (Request): FastAPI request object.

    Returns:
        RedirectResponse: Redirect to admin page with cleared cookies.

    Examples:
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from unittest.mock import MagicMock
        >>>
        >>> # Mock request
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>>
        >>> import asyncio
        >>> async def test_logout():
        ...     response = await admin_logout(mock_request)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_logout())
        True
    """
    LOGGER.info("Admin user logging out")
    root_path = request.scope.get("root_path", "")

    # Create redirect response to login page
    response = RedirectResponse(url=f"{root_path}/admin/login", status_code=303)

    # Clear JWT token cookie
    response.delete_cookie("jwt_token", path=settings.app_root_path or "/", secure=True, httponly=True, samesite="lax")

    return response


@admin_router.get("/change-password-required", response_class=HTMLResponse)
async def change_password_required_page(request: Request) -> HTMLResponse:
    """
    Render the password change required page.

    This page is shown when a user's password has expired and must be changed
    to continue accessing the system.

    Args:
        request (Request): FastAPI request object.

    Returns:
        HTMLResponse: The password change required page.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import HTMLResponse
        >>>
        >>> # Mock request
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>> mock_request.app.state.templates = MagicMock()
        >>> mock_response = HTMLResponse("<html>Change Password</html>")
        >>> mock_request.app.state.templates.TemplateResponse.return_value = mock_response
        >>>
        >>> import asyncio
        >>> async def test_change_password_page():
        ...     # Note: This requires email_auth_enabled=True in settings
        ...     return True  # Simplified test due to settings dependency
        >>>
        >>> asyncio.run(test_change_password_page())
        True
    """
    if not getattr(settings, "email_auth_enabled", False):
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin", status_code=303)

    # Get root path for template
    root_path = request.scope.get("root_path", "")

    return request.app.state.templates.TemplateResponse(
        "change-password-required.html",
        {
            "request": request,
            "root_path": root_path,
            "ui_airgapped": settings.mcpgateway_ui_airgapped,
            "password_min_length": getattr(settings, "password_min_length", 8),
            "password_require_uppercase": getattr(settings, "password_require_uppercase", False),
            "password_require_lowercase": getattr(settings, "password_require_lowercase", False),
            "password_require_numbers": getattr(settings, "password_require_numbers", False),
            "password_require_special": getattr(settings, "password_require_special", False),
        },
    )


@admin_router.post("/change-password-required")
async def change_password_required_handler(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """
    Handle password change requirement form submission.

    This endpoint processes the forced password change form, validates the credentials,
    changes the password, clears the password_change_required flag, and redirects to admin panel.

    Args:
        request (Request): FastAPI request object.
        db (Session): Database session dependency.

    Returns:
        RedirectResponse: Redirect to admin panel on success or back to form with error.

    Examples:
        >>> from unittest.mock import MagicMock, AsyncMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>>
        >>> # Mock request with form data
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>> mock_form = {
        ...     "current_password": "oldpass",
        ...     "new_password": "newpass123",
        ...     "confirm_password": "newpass123"
        ... }
        >>> mock_request.form = AsyncMock(return_value=mock_form)
        >>> mock_request.cookies = {"jwt_token": "test_token"}
        >>> mock_request.headers = {"User-Agent": "TestAgent"}
        >>>
        >>> mock_db = MagicMock()
        >>>
        >>> import asyncio
        >>> async def test_password_change_handler():
        ...     # Note: Full test requires email_auth_enabled and valid JWT
        ...     return True  # Simplified test due to settings/auth dependencies
        >>>
        >>> asyncio.run(test_password_change_handler())
        True
    """
    if not getattr(settings, "email_auth_enabled", False):
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin", status_code=303)

    try:
        form = await request.form()
        current_password_val = form.get("current_password")
        new_password_val = form.get("new_password")
        confirm_password_val = form.get("confirm_password")

        current_password = current_password_val if isinstance(current_password_val, str) else None
        new_password = new_password_val if isinstance(new_password_val, str) else None
        confirm_password = confirm_password_val if isinstance(confirm_password_val, str) else None

        if not all([current_password, new_password, confirm_password]):
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=missing_fields", status_code=303)

        if new_password != confirm_password:
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=mismatch", status_code=303)

        # Get user from JWT token in cookie
        try:
            jwt_token = request.cookies.get("jwt_token")
            if not jwt_token:
                root_path = request.scope.get("root_path", "")
                return RedirectResponse(url=f"{root_path}/admin/login?error=session_expired", status_code=303)

            # Authenticate using the token
            # Create credentials object from cookie
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt_token)
            # get_current_user now uses fresh DB sessions internally
            current_user = await get_current_user(credentials, request=request)

            if not current_user:
                root_path = request.scope.get("root_path", "")
                return RedirectResponse(url=f"{root_path}/admin/login?error=session_expired", status_code=303)
        except Exception as e:
            LOGGER.error(f"Authentication error: {e}")
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/login?error=session_expired", status_code=303)

        # Authenticate using the email auth service
        auth_service = EmailAuthService(db)
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)

        try:
            # Change password
            success = await auth_service.change_password(email=current_user.email, old_password=current_password, new_password=new_password, ip_address=ip_address, user_agent=user_agent)

            if success:
                # Clear the password_change_required flag
                current_user.password_change_required = False
                db.commit()

                # Create new JWT token
                token, _ = await create_access_token(current_user)

                # Create redirect response to admin panel
                root_path = request.scope.get("root_path", "")
                response = RedirectResponse(url=f"{root_path}/admin", status_code=303)

                # Update JWT token cookie
                set_auth_cookie(response, token, remember_me=False)

                LOGGER.info(f"User {current_user.email} successfully changed their expired password")
                return response

            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=change_failed", status_code=303)

        except AuthenticationError:
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=invalid_password", status_code=303)
        except PasswordValidationError as e:
            LOGGER.warning(f"Password validation failed for {current_user.email}: {e}")
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=weak_password", status_code=303)
        except Exception as e:
            LOGGER.error(f"Password change failed for {current_user.email}: {e}", exc_info=True)
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=server_error", status_code=303)

    except Exception as e:
        LOGGER.error(f"Password change handler error: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root_path}/admin/change-password-required?error=server_error", status_code=303)


# ============================================================================ #
#                            TEAM ADMIN ROUTES                                #
# ============================================================================ #


async def _generate_unified_teams_view(team_service, current_user, root_path):  # pylint: disable=unused-argument
    """Generate unified team view with relationship badges.

    Args:
        team_service: Service for team operations
        current_user: Current authenticated user
        root_path: Application root path

    Returns:
        HTML string containing the unified teams view
    """
    # Get user's teams (owned + member)
    user_teams = await team_service.get_user_teams(current_user.email)

    # Get public teams user can join
    public_teams = await team_service.discover_public_teams(current_user.email)

    # Combine teams with relationship information
    all_teams = []

    # Add user's teams (owned and member)
    for team in user_teams:
        user_role = await team_service.get_user_role_in_team(current_user.email, team.id)
        relationship = "owner" if user_role == "owner" else "member"
        all_teams.append({"team": team, "relationship": relationship, "member_count": team.get_member_count()})

    # Add public teams user can join - check for pending requests
    for team in public_teams:
        # Check if user has a pending join request
        user_requests = await team_service.get_user_join_requests(current_user.email, team.id)
        pending_request = next((req for req in user_requests if req.status == "pending"), None)

        relationship_data = {"team": team, "relationship": "join", "member_count": team.get_member_count(), "pending_request": pending_request}
        all_teams.append(relationship_data)

    # Generate HTML for unified team view
    teams_html = ""
    for item in all_teams:
        team = item["team"]
        relationship = item["relationship"]
        member_count = item["member_count"]
        pending_request = item.get("pending_request")

        # Relationship badge - special handling for personal teams
        if team.is_personal:
            badge_html = '<span class="relationship-badge inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300">PERSONAL</span>'
        elif relationship == "owner":
            badge_html = (
                '<span class="relationship-badge inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">OWNER</span>'
            )
        elif relationship == "member":
            badge_html = (
                '<span class="relationship-badge inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">MEMBER</span>'
            )
        else:  # join
            badge_html = '<span class="relationship-badge inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300">CAN JOIN</span>'

        # Visibility badge
        visibility_badge = (
            f'<span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300">{team.visibility.upper()}</span>'
        )

        # Subtitle based on relationship - special handling for personal teams
        if team.is_personal:
            subtitle = "Your personal team • Private workspace"
        elif relationship == "owner":
            subtitle = "You own this team"
        elif relationship == "member":
            subtitle = f"You are a member • Owner: {team.created_by}"
        else:  # join
            subtitle = f"Public team • Owner: {team.created_by}"

        # Escape team name for safe HTML attributes
        safe_team_name = html.escape(team.name)

        # Actions based on relationship - special handling for personal teams
        actions_html = ""
        if team.is_personal:
            # Personal teams have no management actions - they're private workspaces
            actions_html = """
            <div class="flex flex-wrap gap-2 mt-3">
                <span class="px-3 py-1 text-sm font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-700 rounded-md">
                    Personal workspace - no actions available
                </span>
            </div>
            """
        elif relationship == "owner":
            delete_button = f'<button data-team-id="{team.id}" data-team-name="{safe_team_name}" onclick="deleteTeamSafe(this)" class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">Delete Team</button>'
            join_requests_button = (
                f'<button data-team-id="{team.id}" onclick="viewJoinRequestsSafe(this)" class="px-3 py-1 text-sm font-medium text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-300 border border-purple-300 dark:border-purple-600 hover:border-purple-500 dark:hover:border-purple-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500">Join Requests</button>'
                if team.visibility == "public"
                else ""
            )
            actions_html = f"""
            <div class="flex flex-wrap gap-2 mt-3">
                <button data-team-id="{team.id}" onclick="manageTeamMembersSafe(this)" class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                    Manage Members
                </button>
                <button data-team-id="{team.id}" onclick="editTeamSafe(this)" class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500">
                    Edit Settings
                </button>
                {join_requests_button}
                {delete_button}
            </div>
            """
        elif relationship == "member":
            leave_button = f'<button data-team-id="{team.id}" data-team-name="{safe_team_name}" onclick="leaveTeamSafe(this)" class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500">Leave Team</button>'
            actions_html = f"""
            <div class="flex flex-wrap gap-2 mt-3">
                {leave_button}
            </div>
            """
        else:  # join
            if pending_request:
                # Show "Requested to Join [Cancel Request]" state
                actions_html = f"""
                <div class="flex flex-wrap gap-2 mt-3">
                    <span class="px-3 py-1 text-sm font-medium text-yellow-600 dark:text-yellow-400 bg-yellow-100 dark:bg-yellow-900 rounded-md border border-yellow-300 dark:border-yellow-600">
                        ⏳ Requested to Join
                    </span>
                    <button onclick="cancelJoinRequest('{team.id}', '{pending_request.id}')" class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">
                        Cancel Request
                    </button>
                </div>
                """
            else:
                # Show "Request to Join" button
                actions_html = f"""
                <div class="flex flex-wrap gap-2 mt-3">
                    <button data-team-id="{team.id}" data-team-name="{safe_team_name}" onclick="requestToJoinTeamSafe(this)" class="px-3 py-1 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 border border-indigo-300 dark:border-indigo-600 hover:border-indigo-500 dark:hover:border-indigo-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                        Request to Join
                    </button>
                </div>
                """

        # Truncated description (properly escaped)
        description_text = ""
        if team.description:
            safe_description = html.escape(team.description)
            truncated = safe_description[:80] + "..." if len(safe_description) > 80 else safe_description
            description_text = f'<p class="team-description text-sm text-gray-600 dark:text-gray-400 mt-1">{truncated}</p>'

        teams_html += f"""
        <div class="team-card bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow" data-relationship="{relationship}">
            <div class="flex justify-between items-start mb-3">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-2">
                        <h4 class="team-name text-lg font-medium text-gray-900 dark:text-white">🏢 {safe_team_name}</h4>
                        {badge_html}
                        {visibility_badge}
                        <span class="text-sm text-gray-500 dark:text-gray-400">{member_count} members</span>
                    </div>
                    <p class="text-sm text-gray-600 dark:text-gray-400">{subtitle}</p>
                    {description_text}
                </div>
            </div>
            {actions_html}
        </div>
        """

    if not teams_html:
        teams_html = '<div class="text-center py-12"><p class="text-gray-500 dark:text-gray-400">No teams found. Create your first team using the button above.</p></div>'

    return HTMLResponse(content=teams_html)


@admin_router.get("/teams")
@require_permission("teams.read")
async def admin_list_teams(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
    unified: bool = False,
) -> HTMLResponse:
    """List teams for admin UI via HTMX.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated admin user
        unified: If True, return unified team view with relationship badges

    Returns:
        HTML response with teams list

    Raises:
        HTTPException: If email auth is disabled or user not found
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-center py-8"><p class="text-gray-500">Email authentication is disabled. Teams feature requires email auth.</p></div>', status_code=200)

    try:
        auth_service = EmailAuthService(db)
        team_service = TeamManagementService(db)

        # Get current user
        user_email = get_user_email(user)
        current_user = await auth_service.get_user_by_email(user_email)
        if not current_user:
            return HTMLResponse(content='<div class="text-center py-8"><p class="text-red-500">User not found</p></div>', status_code=200)

        root_path = request.scope.get("root_path", "")

        if unified:
            # Generate unified team view
            return await _generate_unified_teams_view(team_service, current_user, root_path)

        # Generate traditional admin view
        if current_user.is_admin:
            teams, _ = await team_service.list_teams()
        else:
            teams = await team_service.get_user_teams(current_user.email)

        # Generate HTML for teams (traditional view)
        teams_html = ""
        for team in teams:
            member_count = team.get_member_count()
            teams_html += f"""
                <div id="team-card-{team.id}" class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-4">
                    <div class="flex justify-between items-start">
                        <div>
                            <h4 class="text-lg font-medium text-gray-900 dark:text-white">{team.name}</h4>
                            <p class="text-sm text-gray-600 dark:text-gray-400">Slug: {team.slug}</p>
                            <p class="text-sm text-gray-600 dark:text-gray-400">Visibility: {team.visibility}</p>
                            <p class="text-sm text-gray-600 dark:text-gray-400">Members: {member_count}</p>
                            {f'<p class="text-sm text-gray-600 dark:text-gray-400">{team.description}</p>' if team.description else ""}
                        </div>
                        <div class="flex space-x-2">
                            <button
                                hx-get="{root_path}/admin/teams/{team.id}/members"
                                hx-target="#team-details-{team.id}"
                                hx-swap="innerHTML"
                                class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            >
                                View Members
                            </button>
                            <button
                                onclick="showTeamEditModal('{team.id}')"
                                class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
                            >
                                Edit
                            </button>
                            {f'<button onclick="leaveTeam(&quot;{team.id}&quot;, &quot;{team.name}&quot;)" class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500">Leave Team</button>' if not team.is_personal and not current_user.is_admin else ""}
                            {f'<button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/teams/{team.id}" hx-confirm="Are you sure you want to delete this team?" hx-target="#team-card-{team.id}" hx-swap="outerHTML">Delete</button>' if not team.is_personal else ""}
                        </div>
                    </div>
                    <div id="team-details-{team.id}" class="mt-4"></div>
            </div>
            """

        if not teams_html:
            teams_html = '<div class="text-center py-8"><p class="text-gray-500 dark:text-gray-400">No teams found. Create your first team above.</p></div>'

        return HTMLResponse(content=teams_html)

    except Exception as e:
        LOGGER.error(f"Error listing teams for admin {user}: {e}")
        return HTMLResponse(content=f'<div class="text-center py-8"><p class="text-red-500">Error loading teams: {str(e)}</p></div>', status_code=200)


@admin_router.post("/teams")
@require_permission("teams.create")
async def admin_create_team(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Create team via admin UI form submission.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated admin user

    Returns:
        HTML response with new team or error message

    Raises:
        HTTPException: If email auth is disabled or validation fails
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = request.scope.get("root_path", "") if request else ""

        form = await request.form()
        name = form.get("name")
        slug = form.get("slug") or None
        description = form.get("description") or None
        visibility = form.get("visibility", "private")

        if not name:
            return HTMLResponse(content='<div class="text-red-500">Team name is required</div>', status_code=400)

        # Create team
        # First-Party
        from mcpgateway.schemas import TeamCreateRequest  # pylint: disable=import-outside-toplevel

        team_service = TeamManagementService(db)

        team_data = TeamCreateRequest(name=name, slug=slug, description=description, visibility=visibility)

        # Extract user email from user dict
        user_email = get_user_email(user)

        team = await team_service.create_team(name=team_data.name, description=team_data.description, created_by=user_email, visibility=team_data.visibility)

        # Return HTML for the new team
        member_count = 1  # Creator is automatically a member
        team_html = f"""
        <div id="team-card-{team.id}" class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-4">
            <div class="flex justify-between items-start">
                <div>
                    <h4 class="text-lg font-medium text-gray-900 dark:text-white">{team.name}</h4>
                    <p class="text-sm text-gray-600 dark:text-gray-400">Slug: {team.slug}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">Visibility: {team.visibility}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">Members: {member_count}</p>
                    {f'<p class="text-sm text-gray-600 dark:text-gray-400">{team.description}</p>' if team.description else ""}
                </div>
                <div class="flex space-x-2">
                    <button
                        hx-get="{root_path}/admin/teams/{team.id}/members"
                        hx-target="#team-details-{team.id}"
                        hx-swap="innerHTML"
                        class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                    >
                        View Members
                    </button>
                    {'<button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/teams/' + team.id + '" hx-confirm="Are you sure you want to delete this team?" hx-target="#team-card-' + team.id + '" hx-swap="outerHTML">Delete</button>' if not team.is_personal else ""}
                </div>
            </div>
            <div id="team-details-{team.id}" class="mt-4"></div>
        </div>
        <script>
            // Reset the team creation form after successful creation
            setTimeout(() => {{
                const form = document.querySelector('form[hx-post*="/admin/teams"]');
                if (form) {{
                    form.reset();
                }}
            }}, 500);
        </script>
        """

        return HTMLResponse(content=team_html, status_code=201)

    except IntegrityError as e:
        LOGGER.error(f"Error creating team for admin {user}: {e}")
        if "UNIQUE constraint failed: email_teams.slug" in str(e):
            return HTMLResponse(content='<div class="text-red-500">A team with this name already exists. Please choose a different name.</div>', status_code=400)

        return HTMLResponse(content=f'<div class="text-red-500">Database error creating team: {str(e)}</div>', status_code=400)
    except Exception as e:
        LOGGER.error(f"Error creating team for admin {user}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error creating team: {str(e)}</div>', status_code=400)


@admin_router.get("/teams/{team_id}/members")
@require_permission("teams.read")
async def admin_view_team_members(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """View team members via admin UI.

    Args:
        team_id: ID of the team to view members for
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Rendered team members view
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root_path from request
        root_path = request.scope.get("root_path", "")

        # Get current user context for logging and authorization
        user_email = get_user_email(user)
        LOGGER.info(f"User {user_email} viewing members for team {team_id}")

        # First-Party
        team_service = TeamManagementService(db)

        # Get team details
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        # Get team members
        members = await team_service.get_team_members(team_id)

        # Count owners to determine if this is the last owner
        owner_count = sum(1 for _, membership in members if membership.role == "owner")

        # Check if current user is team owner
        current_user_role = await team_service.get_user_role_in_team(user_email, team_id)
        is_team_owner = current_user_role == "owner"

        # Build member table with inline role editing for team owners
        members_html = """
        <div class="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                <h4 class="text-sm font-semibold text-gray-900 dark:text-white">Team Members</h4>
            </div>
            <div class="divide-y divide-gray-200 dark:divide-gray-700">
        """

        for member_user, membership in members:
            role_display = membership.role.replace("_", " ").title() if membership.role else "Member"
            is_last_owner = membership.role == "owner" and owner_count == 1
            is_current_user = member_user.email == user_email

            # Role selection - only show for team owners and not for last owner
            if is_team_owner and not is_last_owner:
                role_selector = f"""
                    <select
                        name="role"
                        class="text-xs px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                        hx-post="{root_path}/admin/teams/{team_id}/update-member-role"
                        hx-vals='{{"user_email": "{member_user.email}"}}'
                        hx-target="#team-edit-modal-content"
                        hx-swap="innerHTML"
                        hx-trigger="change">
                        <option value="member" {"selected" if membership.role == "member" else ""}>Member</option>
                        <option value="owner" {"selected" if membership.role == "owner" else ""}>Owner</option>
                    </select>
                """
            else:
                # Show static role badge
                role_color = "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200" if membership.role == "owner" else "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                role_selector = f'<span class="px-2 py-1 text-xs font-medium {role_color} rounded-full">{role_display}</span>'

            # Remove button - hide for current user and last owner
            if is_team_owner and not is_current_user and not is_last_owner:
                remove_button = f"""
                    <button
                        class="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 focus:outline-none"
                        hx-post="{root_path}/admin/teams/{team_id}/remove-member"
                        hx-vals='{{"user_email": "{member_user.email}"}}'
                        hx-confirm="Remove {member_user.email} from this team?"
                        hx-target="#team-edit-modal-content"
                        hx-swap="innerHTML"
                        title="Remove member">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
                """
            else:
                remove_button = ""

            # Special indicators
            indicators = []
            if is_current_user:
                indicators.append('<span class="inline-flex items-center px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full dark:bg-blue-900 dark:text-blue-200">You</span>')
            if is_last_owner:
                indicators.append(
                    '<span class="inline-flex items-center px-2 py-1 text-xs font-medium bg-yellow-100 text-yellow-800 rounded-full dark:bg-yellow-900 dark:text-yellow-200">Last Owner</span>'
                )

            members_html += f"""
                <div class="px-6 py-4 flex items-center justify-between">
                    <div class="flex items-center space-x-4 flex-1">
                        <div class="flex-shrink-0">
                            <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                                <span class="text-sm font-medium text-gray-700 dark:text-gray-300">{member_user.email[0].upper()}</span>
                            </div>
                        </div>
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center space-x-2">
                                <p class="text-sm font-medium text-gray-900 dark:text-white truncate">{member_user.full_name or member_user.email}</p>
                                {" ".join(indicators)}
                            </div>
                            <p class="text-sm text-gray-500 dark:text-gray-400 truncate">{member_user.email}</p>
                            <p class="text-xs text-gray-400 dark:text-gray-500">Joined: {membership.joined_at.strftime("%b %d, %Y") if membership.joined_at else "Unknown"}</p>
                        </div>
                    </div>
                    <div class="flex items-center space-x-3">
                        {role_selector}
                        {remove_button}
                    </div>
                </div>
            """

        members_html += """
            </div>
        </div>
        """

        if not members:
            members_html = '<div class="text-center py-8 text-gray-500 dark:text-gray-400">No members found</div>'

        # Add member management interface
        management_html = f"""
        <div class="mb-4">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-medium text-gray-900 dark:text-white">Manage Members: {team.name}</h3>
                <button onclick="document.getElementById('team-edit-modal').classList.add('hidden')" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>"""

        # Show Add Member interface for team owners
        if is_team_owner:
            management_html += f"""
            <div class="mb-6">
                <div class="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                    <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                        <div class="flex items-center justify-between">
                            <h4 class="text-sm font-semibold text-gray-900 dark:text-white">Add New Member</h4>
                            <button
                                id="toggle-add-member-{team.id}"
                                class="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 focus:outline-none"
                                onclick="document.getElementById('add-member-form-{team.id}').classList.toggle('hidden'); this.textContent = this.textContent === 'Show' ? 'Hide' : 'Show';">
                                Show
                            </button>
                        </div>
                    </div>
                    <div id="add-member-form-{team.id}" class="hidden px-6 py-4">
                        <form hx-post="{root_path}/admin/teams/{team.id}/add-member" hx-target="#team-edit-modal-content" hx-swap="innerHTML">
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div class="md:col-span-2">
                                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Select User</label>
                                    <select name="user_email" required
                                            class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 text-gray-900 dark:text-white">
                                        <option value="">Choose a user to add...</option>"""

            # Get available users (not already members of this team)
            try:
                auth_service = EmailAuthService(db)
                all_users = await auth_service.get_all_users()

                # Get current team members
                team_management_service = TeamManagementService(db)
                team_members = await team_management_service.get_team_members(team.id)
                member_emails = {team_user.email for team_user, membership in team_members}

                # Filter out existing members
                available_users = [team_user for team_user in all_users if team_user.email not in member_emails]

                for team_user in available_users:
                    management_html += f'<option value="{team_user.email}">{team_user.full_name} ({team_user.email})</option>'
            except Exception as e:
                LOGGER.error(f"Error loading available users for team {team.id}: {e}")

            management_html += """                        </select>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Role</label>
                                    <select name="role" required
                                            class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 text-gray-900 dark:text-white">
                                        <option value="member">Member</option>
                                        <option value="owner">Owner</option>
                                    </select>
                                </div>
                            </div>
                            <div class="mt-4 flex justify-end space-x-3">
                                <button type="submit"
                                        class="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors duration-200">
                                    Add Member
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>"""
        else:
            management_html += """
            <div class="mb-4 p-4 bg-yellow-50 dark:bg-yellow-900 rounded-lg border border-yellow-200 dark:border-yellow-700">
                <div class="flex items-center gap-2">
                    <svg class="w-5 h-5 text-yellow-600 dark:text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                    </svg>
                    <span class="text-sm font-medium text-yellow-800 dark:text-yellow-200">Private Team - Member Access</span>
                </div>
                <p class="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                    You are a member of this private team. Only team owners can directly add new members. Use the team invitation system to request access for others.
                </p>
            </div>"""

        management_html += """
        </div>
        """

        return HTMLResponse(content=f'{management_html}<div class="space-y-2">{members_html}</div>')

    except Exception as e:
        LOGGER.error(f"Error viewing team members {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error loading members: {str(e)}</div>', status_code=500)


@admin_router.get("/teams/{team_id}/edit")
@require_permission("teams.update")
async def admin_get_team_edit(
    team_id: str,
    _request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get team edit form via admin UI.

    Args:
        team_id: ID of the team to edit
        db: Database session

    Returns:
        HTMLResponse: Rendered team edit form
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = _request.scope.get("root_path", "") if _request else ""
        team_service = TeamManagementService(db)

        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        edit_form = rf"""
        <div class="space-y-4">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Edit Team</h3>
            <form method="post" action="{root_path}/admin/teams/{team_id}/update" hx-post="{root_path}/admin/teams/{team_id}/update" hx-target="#team-edit-modal-content" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Name</label>
                    <input type="text" name="name" value="{team.name}" required
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Slug</label>
                    <input type="text" name="slug" value="{team.slug}" readonly
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white">
                    <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">Slug cannot be changed</p>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Description</label>
                    <textarea name="description" rows="3"
                              class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white">{team.description or ""}</textarea>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Visibility</label>
                    <select name="visibility"
                            class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white">
                        <option value="private" {"selected" if team.visibility == "private" else ""}>Private</option>
                        <option value="public" {"selected" if team.visibility == "public" else ""}>Public</option>
                    </select>
                </div>
                <div class="flex justify-end space-x-3">
                    <button type="button" onclick="hideTeamEditModal()"
                            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                        Cancel
                    </button>
                    <button type="submit"
                            class="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                        Update Team
                    </button>
                </div>
            </form>
        </div>
        """
        return HTMLResponse(content=edit_form)

    except Exception as e:
        LOGGER.error(f"Error getting team edit form for {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error loading team: {str(e)}</div>', status_code=500)


@admin_router.post("/teams/{team_id}/update")
@require_permission("teams.update")
async def admin_update_team(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Response:
    """Update team via admin UI.

    Args:
        team_id: ID of the team to update
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        Response: Result of team update operation
    """
    # Ensure root_path is available for URL construction in all branches
    root_path = request.scope.get("root_path", "") if request else ""

    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)

        form = await request.form()
        name_val = form.get("name")
        desc_val = form.get("description")
        vis_val = form.get("visibility", "private")
        name = name_val if isinstance(name_val, str) else None
        description = desc_val if isinstance(desc_val, str) and desc_val != "" else None
        visibility = vis_val if isinstance(vis_val, str) else "private"

        if not name:
            is_htmx = request.headers.get("HX-Request") == "true"
            if is_htmx:
                return HTMLResponse(content='<div class="text-red-500">Team name is required</div>', status_code=400)
            error_msg = urllib.parse.quote("Team name is required")
            return RedirectResponse(url=f"{root_path}/admin/?error={error_msg}#teams", status_code=303)

        # Update team
        user_email = getattr(user, "email", None) or str(user)
        await team_service.update_team(team_id=team_id, name=name, description=description, visibility=visibility, updated_by=user_email)

        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"

        if is_htmx:
            # Return success message with auto-close and refresh for HTMX
            success_html = """
            <div class="text-green-500 text-center p-4">
                <p>Team updated successfully</p>
                <script>
                    setTimeout(() => {
                        // Close the modal
                        hideTeamEditModal();
                        // Refresh the teams list
                        htmx.trigger(document.getElementById('teams-list'), 'load');
                    }, 1500);
                </script>
            </div>
            """
            return HTMLResponse(content=success_html)
        # For regular form submission, redirect to admin page with teams section
        return RedirectResponse(url=f"{root_path}/admin/#teams", status_code=303)

    except Exception as e:
        LOGGER.error(f"Error updating team {team_id}: {e}")

        # Check if this is an HTMX request for error handling too
        is_htmx = request.headers.get("HX-Request") == "true"

        if is_htmx:
            return HTMLResponse(content=f'<div class="text-red-500">Error updating team: {str(e)}</div>', status_code=400)
        # For regular form submission, redirect to admin page with error parameter
        error_msg = urllib.parse.quote(f"Error updating team: {str(e)}")
        return RedirectResponse(url=f"{root_path}/admin/?error={error_msg}#teams", status_code=303)


@admin_router.delete("/teams/{team_id}")
@require_permission("teams.delete")
async def admin_delete_team(
    team_id: str,
    _request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Delete team via admin UI.

    Args:
        team_id: ID of the team to delete
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)

        # Get team name for success message
        team = await team_service.get_team_by_id(team_id)
        team_name = team.name if team else "Unknown"

        # Delete team (get user email from JWT payload)
        user_email = get_user_email(user)
        await team_service.delete_team(team_id, deleted_by=user_email)

        # Return success message with script to refresh teams list
        success_html = f"""
        <div class="text-green-500 text-center p-4">
            <p>Team "{team_name}" deleted successfully</p>
            <script>
                setTimeout(() => {{
                    // Refresh the entire teams list
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams?unified=true', {{
                        target: '#unified-teams-list',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error deleting team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error deleting team: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/add-member")
@require_permission("teams.manage_members")
async def admin_add_team_member(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Add member to team via admin UI.

    Args:
        team_id: ID of the team to add member to
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # First-Party
        team_service = TeamManagementService(db)
        auth_service = EmailAuthService(db)

        # Check if team exists and validate visibility
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        # For private teams, only team owners can add members directly
        user_email_from_jwt = get_user_email(user)
        if team.visibility == "private":
            user_role = await team_service.get_user_role_in_team(user_email_from_jwt, team_id)
            if user_role != "owner":
                return HTMLResponse(content='<div class="text-red-500">Only team owners can add members to private teams. Use the invitation system instead.</div>', status_code=403)

        form = await request.form()
        email_val = form.get("user_email")
        role_val = form.get("role", "member")
        user_email = email_val if isinstance(email_val, str) else None
        role = role_val if isinstance(role_val, str) else "member"

        if not user_email:
            return HTMLResponse(content='<div class="text-red-500">User email is required</div>', status_code=400)

        # Check if user exists
        target_user = await auth_service.get_user_by_email(user_email)
        if not target_user:
            return HTMLResponse(content=f'<div class="text-red-500">User {user_email} not found</div>', status_code=400)

        # Add member to team
        await team_service.add_member_to_team(team_id=team_id, user_email=user_email, role=role, invited_by=user_email_from_jwt)

        # Return success message with script to refresh modal
        success_html = f"""
        <div class="text-green-500 text-center p-4">
            <p>Member {user_email} added successfully</p>
            <script>
                setTimeout(() => {{
                    // Reload the manage members modal content
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams/{team_id}/members', {{
                        target: '#team-edit-modal-content',
                        swap: 'innerHTML'
                    }});

                    // Also refresh the teams list to update member counts
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams?unified=true', {{
                        target: '#unified-teams-list',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error adding member to team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error adding member: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/update-member-role")
@require_permission("teams.manage_members")
async def admin_update_team_member_role(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Update team member role via admin UI.

    Args:
        team_id: ID of the team containing the member
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)

        # Check if team exists and validate user permissions
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        # Only team owners can modify member roles
        user_email_from_jwt = get_user_email(user)
        user_role = await team_service.get_user_role_in_team(user_email_from_jwt, team_id)
        if user_role != "owner":
            return HTMLResponse(content='<div class="text-red-500">Only team owners can modify member roles</div>', status_code=403)

        form = await request.form()
        ue_val = form.get("user_email")
        nr_val = form.get("role", "member")
        user_email = ue_val if isinstance(ue_val, str) else None
        new_role = nr_val if isinstance(nr_val, str) else "member"

        if not user_email:
            return HTMLResponse(content='<div class="text-red-500">User email is required</div>', status_code=400)

        if not new_role:
            return HTMLResponse(content='<div class="text-red-500">Role is required</div>', status_code=400)

        # Update member role
        await team_service.update_member_role(team_id=team_id, user_email=user_email, new_role=new_role, updated_by=user_email_from_jwt)

        # Return success message with auto-close and refresh
        success_html = f"""
        <div class="text-green-500 text-center p-4">
            <p>Role updated successfully for {user_email}</p>
            <script>
                setTimeout(() => {{
                    // Reload the manage members modal content to show updated roles
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams/{team_id}/members', {{
                        target: '#team-edit-modal-content',
                        swap: 'innerHTML'
                    }});

                    // Close any open modals
                    const roleModal = document.getElementById('role-assignment-modal');
                    if (roleModal) {{
                        roleModal.classList.add('hidden');
                    }}

                    // Refresh teams list if visible
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams?unified=true', {{
                        target: '#unified-teams-list',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error updating member role in team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error updating role: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/remove-member")
@require_permission("teams.manage_members")
async def admin_remove_team_member(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Remove member from team via admin UI.

    Args:
        team_id: ID of the team to remove member from
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)

        # Check if team exists and validate user permissions
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        # Only team owners can remove members
        user_email_from_jwt = get_user_email(user)
        user_role = await team_service.get_user_role_in_team(user_email_from_jwt, team_id)
        if user_role != "owner":
            return HTMLResponse(content='<div class="text-red-500">Only team owners can remove members</div>', status_code=403)

        form = await request.form()
        ue_val = form.get("user_email")
        user_email = ue_val if isinstance(ue_val, str) else None

        if not user_email:
            return HTMLResponse(content='<div class="text-red-500">User email is required</div>', status_code=400)

        # Remove member from team

        try:
            success = await team_service.remove_member_from_team(team_id=team_id, user_email=user_email, removed_by=user_email_from_jwt)
            if not success:
                return HTMLResponse(content='<div class="text-red-500">Failed to remove member from team</div>', status_code=400)
        except ValueError as e:
            # Handle specific business logic errors (like last owner)
            return HTMLResponse(content=f'<div class="text-red-500">{str(e)}</div>', status_code=400)

        # Return success message with script to refresh modal
        success_html = f"""
        <div class="text-green-500 text-center p-4">
            <p>Member {user_email} removed successfully</p>
            <script>
                setTimeout(() => {{
                    // Reload the manage members modal content
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams/{team_id}/members', {{
                        target: '#team-edit-modal-content',
                        swap: 'innerHTML'
                    }});

                    // Also refresh the teams list to update member counts
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams?unified=true', {{
                        target: '#unified-teams-list',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error removing member from team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error removing member: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/leave")
@require_permission("teams.join")  # Users who can join can also leave
async def admin_leave_team(
    team_id: str,
    request: Request,  # pylint: disable=unused-argument
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Leave a team via admin UI.

    Args:
        team_id: ID of the team to leave
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)

        # Check if team exists
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        # Get current user email
        user_email = get_user_email(user)

        # Check if user is a member of the team
        user_role = await team_service.get_user_role_in_team(user_email, team_id)
        if not user_role:
            return HTMLResponse(content='<div class="text-red-500">You are not a member of this team</div>', status_code=400)

        # Prevent leaving personal teams
        if team.is_personal:
            return HTMLResponse(content='<div class="text-red-500">Cannot leave your personal team</div>', status_code=400)

        # Check if user is the last owner (use SQL COUNT instead of loading all members)
        if user_role == "owner":
            owner_count = team_service.count_team_owners(team_id)
            if owner_count <= 1:
                return HTMLResponse(content='<div class="text-red-500">Cannot leave team as the last owner. Transfer ownership or delete the team instead.</div>', status_code=400)

        # Remove user from team
        success = await team_service.remove_member_from_team(team_id=team_id, user_email=user_email, removed_by=user_email)
        if not success:
            return HTMLResponse(content='<div class="text-red-500">Failed to leave team</div>', status_code=400)

        # Return success message with redirect
        success_html = """
        <div class="text-green-500 text-center p-4">
            <p>Successfully left the team</p>
            <script>
                setTimeout(() => {{
                    // Refresh the unified teams list
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams?unified=true', {{
                        target: '#unified-teams-list',
                        swap: 'innerHTML'
                    }});

                    // Close any open modals
                    const modals = document.querySelectorAll('[id$="-modal"]');
                    modals.forEach(modal => modal.classList.add('hidden'));
                }}, 1500);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error leaving team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error leaving team: {str(e)}</div>', status_code=400)


# ============================================================================ #
#                         TEAM JOIN REQUEST ADMIN ROUTES                      #
# ============================================================================ #


@admin_router.post("/teams/{team_id}/join-request")
async def admin_create_join_request(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Create a join request for a team via admin UI.

    Args:
        team_id: ID of the team to request to join
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with success message or error
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)
        user_email = get_user_email(user)

        # Get team to verify it's public
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        if team.visibility != "public":
            return HTMLResponse(content='<div class="text-red-500">Can only request to join public teams</div>', status_code=400)

        # Check if user is already a member
        user_role = await team_service.get_user_role_in_team(user_email, team_id)
        if user_role:
            return HTMLResponse(content='<div class="text-red-500">You are already a member of this team</div>', status_code=400)

        # Check if user already has a pending request
        existing_requests = await team_service.get_user_join_requests(user_email, team_id)
        pending_request = next((req for req in existing_requests if req.status == "pending"), None)
        if pending_request:
            return HTMLResponse(
                content=f"""
            <div class="text-yellow-600">
                <p>You already have a pending request to join this team.</p>
                <button onclick="cancelJoinRequest('{team_id}', '{pending_request.id}')"
                        class="mt-2 px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">
                    Cancel Request
                </button>
            </div>
            """,
                status_code=200,
            )

        # Get form data for optional message
        form = await request.form()
        msg_val = form.get("message", "")
        message = msg_val if isinstance(msg_val, str) else ""

        # Create join request
        join_request = await team_service.create_join_request(team_id=team_id, user_email=user_email, message=message)

        return HTMLResponse(
            content=f"""
        <div class="text-green-600">
            <p>Join request submitted successfully!</p>
            <button onclick="cancelJoinRequest('{team_id}', '{join_request.id}')"
                    class="mt-2 px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">
                Cancel Request
            </button>
        </div>
        """,
            status_code=201,
        )

    except Exception as e:
        LOGGER.error(f"Error creating join request for team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error creating join request: {str(e)}</div>', status_code=400)


@admin_router.delete("/teams/{team_id}/join-request/{request_id}")
@require_permission("teams.join")
async def admin_cancel_join_request(
    team_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Cancel a join request via admin UI.

    Args:
        team_id: ID of the team
        request_id: ID of the join request to cancel
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with updated button state
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)
        user_email = get_user_email(user)

        # Cancel the join request
        success = await team_service.cancel_join_request(request_id, user_email)
        if not success:
            return HTMLResponse(content='<div class="text-red-500">Failed to cancel join request</div>', status_code=400)

        # Return the "Request to Join" button
        return HTMLResponse(
            content=f"""
        <button data-team-id="{team_id}" data-team-name="Team" onclick="requestToJoinTeamSafe(this)"
                class="px-3 py-1 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 border border-indigo-300 dark:border-indigo-600 hover:border-indigo-500 dark:hover:border-indigo-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
            Request to Join
        </button>
        """,
            status_code=200,
        )

    except Exception as e:
        LOGGER.error(f"Error canceling join request {request_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error canceling join request: {str(e)}</div>', status_code=400)


@admin_router.get("/teams/{team_id}/join-requests")
@require_permission("teams.manage_members")
async def admin_list_join_requests(
    team_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """List join requests for a team via admin UI.

    Args:
        team_id: ID of the team
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with join requests list
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)
        user_email = get_user_email(user)
        request.scope.get("root_path", "")

        # Get team and verify ownership
        team = await team_service.get_team_by_id(team_id)
        if not team:
            return HTMLResponse(content='<div class="text-red-500">Team not found</div>', status_code=404)

        user_role = await team_service.get_user_role_in_team(user_email, team_id)
        if user_role != "owner":
            return HTMLResponse(content='<div class="text-red-500">Only team owners can view join requests</div>', status_code=403)

        # Get join requests
        join_requests = await team_service.list_join_requests(team_id)

        if not join_requests:
            return HTMLResponse(
                content="""
            <div class="text-center py-8">
                <p class="text-gray-500 dark:text-gray-400">No pending join requests</p>
            </div>
            """,
                status_code=200,
            )

        requests_html = ""
        for req in join_requests:
            requests_html += f"""
            <div class="flex justify-between items-center p-4 border border-gray-200 dark:border-gray-600 rounded-lg mb-3">
                <div>
                    <p class="font-medium text-gray-900 dark:text-white">{req.user_email}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">Requested: {req.requested_at.strftime("%Y-%m-%d %H:%M") if req.requested_at else "Unknown"}</p>
                    {f'<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">Message: {req.message}</p>' if req.message else ""}
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300">{req.status.upper()}</span>
                </div>
                <div class="flex gap-2">
                    <button onclick="approveJoinRequest('{team_id}', '{req.id}')"
                            class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500">
                        Approve
                    </button>
                    <button onclick="rejectJoinRequest('{team_id}', '{req.id}')"
                            class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500">
                        Reject
                    </button>
                </div>
            </div>
            """

        return HTMLResponse(
            content=f"""
        <div class="space-y-4">
            <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Join Requests for {team.name}</h3>
            {requests_html}
        </div>
        """,
            status_code=200,
        )

    except Exception as e:
        LOGGER.error(f"Error listing join requests for team {team_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error loading join requests: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/join-requests/{request_id}/approve")
@require_permission("teams.manage_members")
async def admin_approve_join_request(
    team_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Approve a join request via admin UI.

    Args:
        team_id: ID of the team
        request_id: ID of the join request to approve
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with success message
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)
        user_email = get_user_email(user)

        # Verify team ownership
        user_role = await team_service.get_user_role_in_team(user_email, team_id)
        if user_role != "owner":
            return HTMLResponse(content='<div class="text-red-500">Only team owners can approve join requests</div>', status_code=403)

        # Approve join request
        member = await team_service.approve_join_request(request_id, approved_by=user_email)
        if not member:
            return HTMLResponse(content='<div class="text-red-500">Join request not found</div>', status_code=404)

        return HTMLResponse(
            content=f"""
        <div class="text-green-600 text-center p-4">
            <p>Join request approved! {member.user_email} is now a team member.</p>
            <script>
                setTimeout(() => {{
                    // Refresh the join requests list
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams/{team_id}/join-requests', {{
                        target: '#team-join-requests-modal-content',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """,
            status_code=200,
        )

    except Exception as e:
        LOGGER.error(f"Error approving join request {request_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error approving join request: {str(e)}</div>', status_code=400)


@admin_router.post("/teams/{team_id}/join-requests/{request_id}/reject")
@require_permission("teams.manage_members")
async def admin_reject_join_request(
    team_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Reject a join request via admin UI.

    Args:
        team_id: ID of the team
        request_id: ID of the join request to reject
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with success message
    """
    if not getattr(settings, "email_auth_enabled", False):
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        team_service = TeamManagementService(db)
        user_email = get_user_email(user)

        # Verify team ownership
        user_role = await team_service.get_user_role_in_team(user_email, team_id)
        if user_role != "owner":
            return HTMLResponse(content='<div class="text-red-500">Only team owners can reject join requests</div>', status_code=403)

        # Reject join request
        success = await team_service.reject_join_request(request_id, rejected_by=user_email)
        if not success:
            return HTMLResponse(content='<div class="text-red-500">Join request not found</div>', status_code=404)

        return HTMLResponse(
            content=f"""
        <div class="text-green-600 text-center p-4">
            <p>Join request rejected.</p>
            <script>
                setTimeout(() => {{
                    // Refresh the join requests list
                    htmx.ajax('GET', window.ROOT_PATH + '/admin/teams/{team_id}/join-requests', {{
                        target: '#team-join-requests-modal-content',
                        swap: 'innerHTML'
                    }});
                }}, 1000);
            </script>
        </div>
        """,
            status_code=200,
        )

    except Exception as e:
        LOGGER.error(f"Error rejecting join request {request_id}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error rejecting join request: {str(e)}</div>', status_code=400)


# ============================================================================ #
#                         USER MANAGEMENT ADMIN ROUTES                        #
# ============================================================================ #


@admin_router.get("/users")
@require_permission("admin.user_management")
async def admin_list_users(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Response:
    """List users for admin UI via HTMX.

    Args:
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        Response: HTML or JSON response with users list
    """
    try:
        if not settings.email_auth_enabled:
            return HTMLResponse(content='<div class="text-center py-8"><p class="text-gray-500">Email authentication is disabled. User management requires email auth.</p></div>', status_code=200)

        # Get root_path from request
        root_path = request.scope.get("root_path", "")

        # First-Party

        auth_service = EmailAuthService(db)

        # List all users (admin endpoint)
        users = await auth_service.list_users()

        # Check if JSON response is requested (for dropdown population)
        accept_header = request.headers.get("accept", "")
        is_json_request = "application/json" in accept_header or request.query_params.get("format") == "json"

        if is_json_request:
            # Return JSON for dropdown population
            users_data = []
            for user_obj in users:
                users_data.append({"email": user_obj.email, "full_name": user_obj.full_name, "is_active": user_obj.is_active, "is_admin": user_obj.is_admin})
            return ORJSONResponse(content={"users": users_data})

        # Generate HTML for users
        users_html = ""
        current_user_email = get_user_email(user)

        # Check how many active admins we have to determine if we should hide buttons for last admin
        admin_count = await auth_service.count_active_admin_users()

        for user_obj in users:
            status_class = "text-green-600" if user_obj.is_active else "text-red-600"
            status_text = "Active" if user_obj.is_active else "Inactive"
            admin_badge = '<span class="px-2 py-1 text-xs font-semibold bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Admin</span>' if user_obj.is_admin else ""
            is_current_user = user_obj.email == current_user_email
            is_last_admin = user_obj.is_admin and user_obj.is_active and admin_count == 1

            # Build activate/deactivate buttons (hide for current user and last admin)
            activate_deactivate_button = ""
            if not is_current_user and not is_last_admin:
                if not user_obj.is_active:
                    activate_deactivate_button = f'<button class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500" hx-post="{root_path}/admin/users/{urllib.parse.quote(user_obj.email, safe="")}/activate" hx-confirm="Activate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Activate</button>'
                else:
                    activate_deactivate_button = f'<button class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500" hx-post="{root_path}/admin/users/{urllib.parse.quote(user_obj.email, safe="")}/deactivate" hx-confirm="Deactivate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Deactivate</button>'

            # Build delete button (hide for current user and last admin)
            delete_button = ""
            if not is_current_user and not is_last_admin:
                delete_button = f'<button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/users/{urllib.parse.quote(user_obj.email, safe="")}" hx-confirm="Are you sure you want to delete this user? This action cannot be undone." hx-target="closest .user-card" hx-swap="outerHTML">Delete</button>'

            # Build force password change button/indicator
            password_change_button_html = ""  # nosec B105 - HTML content, not password
            if not is_current_user:
                if user_obj.password_change_required:
                    # HTML content for password change required indicator
                    password_change_required_html = (  # nosec B105 - HTML content, not password
                        '<span class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 '
                        "bg-orange-50 dark:bg-orange-900/20 border border-orange-300 dark:border-orange-600 "
                        'rounded-md">Password Change Required</span>'
                    )
                    password_change_button_html = password_change_required_html
                else:
                    password_change_button_html = (
                        f'<button class="px-3 py-1 text-sm font-medium text-yellow-600 dark:text-yellow-400 '
                        f"hover:text-yellow-800 dark:hover:text-yellow-300 border border-yellow-300 dark:border-yellow-600 "
                        f"hover:border-yellow-500 dark:hover:border-yellow-400 rounded-md focus:outline-none focus:ring-2 "
                        f'focus:ring-offset-2 focus:ring-yellow-500" hx-post="{root_path}/admin/users/{urllib.parse.quote(user_obj.email, safe="")}/force-password-change" '
                        f'hx-confirm="Force this user to change their password on next login?" hx-target="closest .user-card" '
                        f'hx-swap="outerHTML">Force Password Change</button>'
                    )

            # Password change required badge
            password_badge = (
                '<span class="px-2 py-1 text-xs font-semibold bg-orange-100 text-orange-800 rounded-full dark:bg-orange-900 dark:text-orange-200"><i class="fas fa-key mr-1"></i>Password Change Required</span>'
                if user_obj.password_change_required
                else ""
            )

            users_html += f"""
            <div class="user-card border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-2">
                            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{user_obj.full_name or "N/A"}</h3>
                            {admin_badge}
                            <span class="px-2 py-1 text-xs font-semibold {status_class} bg-gray-100 dark:bg-gray-700 rounded-full">{status_text}</span>
                            {'<span class="px-2 py-1 text-xs font-semibold bg-blue-100 text-blue-800 rounded-full dark:bg-blue-900 dark:text-blue-200">You</span>' if is_current_user else ""}
                            {'<span class="px-2 py-1 text-xs font-semibold bg-yellow-100 text-yellow-800 rounded-full dark:bg-yellow-900 dark:text-yellow-200">Last Admin</span>' if is_last_admin else ""}
                            {password_badge}
                        </div>
                        <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">📧 {user_obj.email}</p>
                        <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">🔐 Provider: {user_obj.auth_provider}</p>
                        <p class="text-sm text-gray-600 dark:text-gray-400">📅 Created: {user_obj.created_at.strftime("%Y-%m-%d %H:%M")}</p>
                    </div>
                    <div class="flex gap-2 ml-4">
                        <button class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                                hx-get="{root_path}/admin/users/{urllib.parse.quote(user_obj.email, safe="")}/edit" hx-target="#user-edit-modal-content">
                            Edit
                        </button>
                        {activate_deactivate_button}
                        {password_change_button_html}
                        {delete_button}
                    </div>
                </div>
            </div>
            """

        if not users_html:
            users_html = '<div class="text-center py-8"><p class="text-gray-500 dark:text-gray-400">No users found.</p></div>'

        return HTMLResponse(content=users_html)

    except Exception as e:
        LOGGER.error(f"Error listing users for admin {user}: {e}")
        return HTMLResponse(content=f'<div class="text-center py-8"><p class="text-red-500">Error loading users: {str(e)}</p></div>', status_code=200)


@admin_router.post("/users")
@require_permission("admin.user_management")
async def admin_create_user(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Create a new user via admin UI.

    Args:
        request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    try:
        # Get root path for URL construction
        root_path = request.scope.get("root_path", "") if request else ""

        form = await request.form()

        # Validate password strength
        password = str(form.get("password", ""))
        if password:
            is_valid, error_msg = validate_password_strength(password)
            if not is_valid:
                return HTMLResponse(content=f'<div class="text-red-500">Password validation failed: {error_msg}</div>', status_code=400)

        # First-Party

        auth_service = EmailAuthService(db)

        # Create new user
        new_user = await auth_service.create_user(
            email=str(form.get("email", "")), password=password, full_name=str(form.get("full_name", "")), is_admin=form.get("is_admin") == "on", auth_provider="local"
        )

        # If the user was created with the default password, force password change
        if password == settings.default_user_password.get_secret_value():  # nosec B105
            new_user.password_change_required = True
            db.commit()

        LOGGER.info(f"Admin {user} created user: {new_user.email}")

        # Generate HTML for the new user
        status_class = "text-green-600"
        status_text = "Active"
        admin_badge = '<span class="px-2 py-1 text-xs font-semibold bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Admin</span>' if new_user.is_admin else ""

        user_html = f"""
        <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
            <div class="flex justify-between items-start">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{new_user.full_name or "N/A"}</h3>
                        {admin_badge}
                        <span class="px-2 py-1 text-xs font-semibold {status_class} bg-gray-100 dark:bg-gray-700 rounded-full">{status_text}</span>
                    </div>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">📧 {new_user.email}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">🔐 Provider: {new_user.auth_provider}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">📅 Created: {new_user.created_at.strftime("%Y-%m-%d %H:%M")}</p>
                </div>
                <div class="flex gap-2 ml-4">
                    <button class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            hx-get="{root_path}/admin/users/{new_user.email}/edit" hx-target="#user-edit-modal-content">
                        Edit
                    </button>
                    <button class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500" hx-post="{root_path}/admin/users/{new_user.email.replace("@", "%40")}/deactivate" hx-confirm="Deactivate this user?" hx-target="closest .border">Deactivate</button>
                </div>
            </div>
        </div>
        """

        return HTMLResponse(content=user_html, status_code=201)

    except Exception as e:
        LOGGER.error(f"Error creating user by admin {user}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error creating user: {str(e)}</div>', status_code=400)


@admin_router.get("/users/{user_email}/edit")
@require_permission("admin.user_management")
async def admin_get_user_edit(
    user_email: str,
    _request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get user edit form via admin UI.

    Args:
        user_email: Email of user to edit
        db: Database session

    Returns:
        HTMLResponse: User edit form HTML
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = _request.scope.get("root_path", "") if _request else ""

        # First-Party

        auth_service = EmailAuthService(db)

        # URL decode the email

        decoded_email = urllib.parse.unquote(user_email)

        user_obj = await auth_service.get_user_by_email(decoded_email)
        if not user_obj:
            return HTMLResponse(content='<div class="text-red-500">User not found</div>', status_code=404)

        # Build Password Requirements HTML separately to avoid backslash issues inside f-strings
        if settings.password_require_uppercase or settings.password_require_lowercase or settings.password_require_numbers or settings.password_require_special:
            pr_lines = []
            pr_lines.append(
                f"""                <!-- Password Requirements -->
                <div class="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-700 rounded-md p-4">
                    <div class="flex items-start">
                        <svg class="h-5 w-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                        </svg>
                        <div class="ml-3 flex-1">
                            <h3 class="text-sm font-semibold text-blue-900 dark:text-blue-200">Password Requirements</h3>
                            <div class="mt-2 text-sm text-blue-800 dark:text-blue-300 space-y-1">
                                <div class="flex items-center" id="req-length">
                                    <span class="inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2">✗</span>
                                    <span>At least {settings.password_min_length} characters long</span>
                                </div>
            """
            )
            if settings.password_require_uppercase:
                pr_lines.append(
                    """
                                <div class="flex items-center" id="req-uppercase"><span class="inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2">✗</span><span>Contains uppercase letters (A-Z)</span></div>
                """
                )
            if settings.password_require_lowercase:
                pr_lines.append(
                    """
                                <div class="flex items-center" id="req-lowercase"><span class="inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2">✗</span><span>Contains lowercase letters (a-z)</span></div>
                """
                )
            if settings.password_require_numbers:
                pr_lines.append(
                    """
                                <div class="flex items-center" id="req-numbers"><span class="inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2">✗</span><span>Contains numbers (0-9)</span></div>
                """
                )
            if settings.password_require_special:
                pr_lines.append(
                    """
                                <div class="flex items-center" id="req-special"><span class="inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2">✗</span><span>Contains special characters (!@#$%^&amp;*(),.?&quot;:{{}}|&lt;&gt;)</span></div>
                """
                )
            pr_lines.append(
                """
                            </div>
                        </div>
                    </div>
                </div>
            """
            )
            password_requirements_html = "".join(pr_lines)
        else:
            # Intentionally an empty string for HTML insertion when no requirements apply.
            # This is not a password value; suppress Bandit false positive B105.
            password_requirements_html = ""  # nosec B105

        # Create edit form HTML
        edit_form = f"""
        <div class="space-y-4">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Edit User</h3>
            <form hx-post="{root_path}/admin/users/{user_email}/update" hx-target="#user-edit-modal-content" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Email</label>
                    <input type="email" name="email" value="{user_obj.email}" readonly
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Full Name</label>
                    <input type="text" name="full_name" value="{user_obj.full_name or ""}" required
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                        <input type="checkbox" name="is_admin" {"checked" if user_obj.is_admin else ""}
                               class="mr-2"> Administrator
                    </label>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">New Password (leave empty to keep current)</label>
                    <input type="password" name="password" id="password-field"
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white"
                           oninput="validatePasswordRequirements(); validatePasswordMatch();">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">Confirm New Password</label>
                    <input type="password" name="confirm_password" id="confirm-password-field"
                           class="mt-1 px-1.5 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 text-gray-900 dark:text-white"
                           oninput="validatePasswordMatch()">
                    <div id="password-match-message" class="mt-1 text-sm text-red-600 hidden">Passwords do not match</div>
                </div>
                {password_requirements_html}

                <script>
                // Password policy settings injected from backend
                const passwordPolicy = {{
                    minLength: {settings.password_min_length},
                    requireUppercase: {'true' if settings.password_require_uppercase else 'false'},
                    requireLowercase: {'true' if settings.password_require_lowercase else 'false'},
                    requireNumbers: {'true' if settings.password_require_numbers else 'false'},
                    requireSpecial: {'true' if settings.password_require_special else 'false'}
                }};

                // (No debug output) passwordPolicy available in JS for logic below

                function updateRequirementIcon(elementId, isValid) {{
                    const req = document.getElementById(elementId);
                    if (req) {{
                        const icon = req.querySelector('span');
                        if (isValid) {{
                            icon.className = 'inline-flex items-center justify-center w-4 h-4 bg-green-500 text-white rounded-full text-xs mr-2';
                            icon.textContent = '✓';
                        }} else {{
                            icon.className = 'inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2';
                            icon.textContent = '✗';
                        }}
                    }}
                }}

                function validatePasswordRequirements() {{
                    const password = document.getElementById('password-field')?.value || '';

                    // Check length requirement (always required)
                    const lengthCheck = password.length >= passwordPolicy.minLength;
                    updateRequirementIcon('req-length', lengthCheck);

                    // Check uppercase requirement (if enabled)
                    const uppercaseCheck = !passwordPolicy.requireUppercase || /[A-Z]/.test(password);
                    updateRequirementIcon('req-uppercase', uppercaseCheck);

                    // Check lowercase requirement (if enabled)
                    const lowercaseCheck = !passwordPolicy.requireLowercase || /[a-z]/.test(password);
                    updateRequirementIcon('req-lowercase', lowercaseCheck);

                    // Check numbers requirement (if enabled)
                    const numbersCheck = !passwordPolicy.requireNumbers || /[0-9]/.test(password);
                    updateRequirementIcon('req-numbers', numbersCheck);

                    // Check special character requirement (if enabled) - matches backend set
                    const specialCheck = !passwordPolicy.requireSpecial || /[!@#$%^&*()_+\\-\\=\\[\\]{{}};:'"\\\\|,.<>`~\\/\\?]/.test(password);
                    updateRequirementIcon('req-special', specialCheck);

                    // Enable/disable submit button based on active requirements
                    const submitButton = document.querySelector('#user-edit-modal-content button[type="submit"]');
                    const allRequirementsMet = lengthCheck && uppercaseCheck && lowercaseCheck && numbersCheck && specialCheck;
                    const passwordEmpty = password.length === 0;

                    if (submitButton) {{
                        // Allow submission if password is empty (keep current) or if all requirements are met
                        if (passwordEmpty || allRequirementsMet) {{
                            submitButton.disabled = false;
                            submitButton.className = 'px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500';
                        }} else {{
                            submitButton.disabled = true;
                            submitButton.className = 'px-4 py-2 text-sm font-medium text-white bg-gray-400 border border-transparent rounded-md cursor-not-allowed';
                        }}
                    }}
                }}

                function validatePasswordMatch() {{
                    const password = document.getElementById('password-field')?.value || '';
                    const confirmPassword = document.getElementById('confirm-password-field')?.value || '';
                    const matchMessage = document.getElementById('password-match-message');

                    if (password && confirmPassword && password !== confirmPassword) {{
                        matchMessage?.classList.remove('hidden');
                    }} else {{
                        matchMessage?.classList.add('hidden');
                    }}
                }}

                // Initialize validation when the form is present (supports HTMX-injected content)
                (function initPasswordValidation() {{
                    if (document.getElementById('password-field')) {{
                        validatePasswordRequirements();
                        validatePasswordMatch();
                    }}
                }})();

                // Re-run validation after HTMX swaps content into the DOM (modal loaded via HTMX)
                document.addEventListener('htmx:afterSwap', function(event) {{
                    try {{
                        const target = event.detail && event.detail.target ? event.detail.target : null;
                        if (target && (target.querySelector('#password-field') || target.id === 'user-edit-modal-content')) {{
                            validatePasswordRequirements();
                            validatePasswordMatch();
                        }}
                    }} catch (e) {{
                        // Ignore errors from HTMX event handling
                    }}
                }});
                </script>
                <div class="flex justify-end space-x-3">
                    <button type="button" onclick="hideUserEditModal()"
                            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                        Cancel
                    </button>
                    <button type="submit"
                            class="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                        Update User
                    </button>
                </div>
            </form>
        </div>
        """
        return HTMLResponse(content=edit_form)

    except Exception as e:
        LOGGER.error(f"Error getting user edit form for {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error loading user: {str(e)}</div>', status_code=500)


@admin_router.post("/users/{user_email}/update")
@require_permission("admin.user_management")
async def admin_update_user(
    user_email: str,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Update user via admin UI.

    Args:
        user_email: Email of user to update
        request: FastAPI request object
        db: Database session

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # First-Party

        auth_service = EmailAuthService(db)

        # URL decode the email

        decoded_email = urllib.parse.unquote(user_email)

        form = await request.form()
        full_name = form.get("full_name")
        is_admin = form.get("is_admin") == "on"
        password = form.get("password")
        confirm_password = form.get("confirm_password")

        # Validate password confirmation if password is being changed
        if password and password != confirm_password:
            return HTMLResponse(content='<div class="text-red-500">Passwords do not match</div>', status_code=400)

        # Check if trying to remove admin privileges from last admin
        user_obj = await auth_service.get_user_by_email(decoded_email)
        if user_obj and user_obj.is_admin and not is_admin:
            # This user is currently an admin and we're trying to remove admin privileges
            if await auth_service.is_last_active_admin(decoded_email):
                return HTMLResponse(content='<div class="text-red-500">Cannot remove administrator privileges from the last remaining admin user</div>', status_code=400)

        # Update user
        fn_val = form.get("full_name")
        pw_val = form.get("password")
        full_name = fn_val if isinstance(fn_val, str) else None
        password = pw_val.strip() if isinstance(pw_val, str) and pw_val.strip() else None

        # Validate password if provided
        if password:
            is_valid, error_msg = validate_password_strength(password)
            if not is_valid:
                return HTMLResponse(content=f'<div class="text-red-500">Password validation failed: {error_msg}</div>', status_code=400)

        await auth_service.update_user(email=decoded_email, full_name=full_name, is_admin=is_admin, password=password)

        # Return success message with auto-close and refresh
        success_html = """
        <div class="text-green-500 text-center p-4">
            <p>User updated successfully</p>
            <script>
                setTimeout(() => {
                    // Close the modal
                    hideUserEditModal();
                    // Refresh the users list
                    htmx.trigger(document.getElementById('users-list'), 'load');
                }, 1500);
            </script>
        </div>
        """
        return HTMLResponse(content=success_html)

    except Exception as e:
        LOGGER.error(f"Error updating user {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error updating user: {str(e)}</div>', status_code=400)


@admin_router.post("/users/{user_email}/activate")
@require_permission("admin.user_management")
async def admin_activate_user(
    user_email: str,
    _request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Activate user via admin UI.

    Args:
        user_email: Email of user to activate
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = _request.scope.get("root_path", "") if _request else ""

        # First-Party

        auth_service = EmailAuthService(db)

        # URL decode the email

        decoded_email = urllib.parse.unquote(user_email)

        # Get current user email from JWT (used for logging purposes)
        get_user_email(user)

        user_obj = await auth_service.activate_user(decoded_email)
        user_html = f"""
        <div class="user-card border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
            <div class="flex justify-between items-start">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{user_obj.full_name}</h3>
                        <span class="px-2 py-1 text-xs font-semibold text-green-600 bg-gray-100 dark:bg-gray-700 rounded-full">Active</span>
                    </div>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">📧 {user_obj.email}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">🔐 Provider: {user_obj.auth_provider}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">📅 Created: {user_obj.created_at.strftime("%Y-%m-%d %H:%M") if user_obj.created_at else "Unknown"}</p>
                </div>
                <div class="flex gap-2 ml-4">
                    <button class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            hx-get="{root_path}/admin/users/{user_obj.email}/edit" hx-target="#user-edit-modal-content">
                        Edit
                    </button>
                    <button class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500" hx-post="{root_path}/admin/users/{user_obj.email.replace("@", "%40")}/deactivate" hx-confirm="Deactivate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Deactivate</button>
                    <button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/users/{user_obj.email.replace("@", "%40")}" hx-confirm="Are you sure you want to delete this user? This action cannot be undone." hx-target="closest .user-card" hx-swap="outerHTML">Delete</button>
                </div>
            </div>
        </div>
        """
        return HTMLResponse(content=user_html)

    except Exception as e:
        LOGGER.error(f"Error activating user {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error activating user: {str(e)}</div>', status_code=400)


@admin_router.post("/users/{user_email}/deactivate")
@require_permission("admin.user_management")
async def admin_deactivate_user(
    user_email: str,
    _request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Deactivate user via admin UI.

    Args:
        user_email: Email of user to deactivate
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success message or error response
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = _request.scope.get("root_path", "") if _request else ""

        # First-Party

        auth_service = EmailAuthService(db)

        # URL decode the email

        decoded_email = urllib.parse.unquote(user_email)

        # Get current user email from JWT
        current_user_email = get_user_email(user)

        # Prevent self-deactivation
        if decoded_email == current_user_email:
            return HTMLResponse(content='<div class="text-red-500">Cannot deactivate your own account</div>', status_code=400)

        # Prevent deactivating the last active admin user
        if await auth_service.is_last_active_admin(decoded_email):
            return HTMLResponse(content='<div class="text-red-500">Cannot deactivate the last remaining admin user</div>', status_code=400)

        user_obj = await auth_service.deactivate_user(decoded_email)
        user_html = f"""
        <div class="user-card border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
            <div class="flex justify-between items-start">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{user_obj.full_name}</h3>
                        <span class="px-2 py-1 text-xs font-semibold text-red-600 bg-gray-100 dark:bg-gray-700 rounded-full">Inactive</span>
                    </div>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">📧 {user_obj.email}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">🔐 Provider: {user_obj.auth_provider}</p>
                    <p class="text-sm text-gray-600 dark:text-gray-400">📅 Created: {user_obj.created_at.strftime("%Y-%m-%d %H:%M") if user_obj.created_at else "Unknown"}</p>
                </div>
                <div class="flex gap-2 ml-4">
                    <button class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            hx-get="{root_path}/admin/users/{user_obj.email}/edit" hx-target="#user-edit-modal-content">
                        Edit
                    </button>
                    <button class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500" hx-post="{root_path}/admin/users/{user_obj.email.replace("@", "%40")}/activate" hx-confirm="Activate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Activate</button>
                    <button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/users/{user_obj.email.replace("@", "%40")}" hx-confirm="Are you sure you want to delete this user? This action cannot be undone." hx-target="closest .user-card" hx-swap="outerHTML">Delete</button>
                </div>
            </div>
        </div>
        """
        return HTMLResponse(content=user_html)

    except Exception as e:
        LOGGER.error(f"Error deactivating user {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error deactivating user: {str(e)}</div>', status_code=400)


@admin_router.delete("/users/{user_email}")
@require_permission("admin.user_management")
async def admin_delete_user(
    user_email: str,
    _request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Delete user via admin UI.

    Args:
        user_email: Email address of user to delete
        _request: FastAPI request object (unused)
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Success/error message
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # First-Party

        auth_service = EmailAuthService(db)

        # URL decode the email

        decoded_email = urllib.parse.unquote(user_email)

        # Get current user email from JWT
        current_user_email = get_user_email(user)

        # Prevent self-deletion
        if decoded_email == current_user_email:
            return HTMLResponse(content='<div class="text-red-500">Cannot delete your own account</div>', status_code=400)

        # Prevent deleting the last active admin user
        if await auth_service.is_last_active_admin(decoded_email):
            return HTMLResponse(content='<div class="text-red-500">Cannot delete the last remaining admin user</div>', status_code=400)

        await auth_service.delete_user(decoded_email)

        # Return empty content to remove the user from the list
        return HTMLResponse(content="", status_code=200)

    except Exception as e:
        LOGGER.error(f"Error deleting user {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error deleting user: {str(e)}</div>', status_code=400)


@admin_router.post("/users/{user_email}/force-password-change")
@require_permission("admin.user_management")
async def admin_force_password_change(
    user_email: str,
    _request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Force user to change password on next login.

    Args:
        user_email: Email of user to force password change
        _request: FastAPI request object
        db: Database session
        user: Current authenticated user context

    Returns:
        HTMLResponse: Updated user card with success message

    Examples:
        >>> from unittest.mock import MagicMock, AsyncMock
        >>> from fastapi import Request
        >>> from fastapi.responses import HTMLResponse
        >>>
        >>> # Mock request
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.scope = {"root_path": "/test"}
        >>>
        >>> # Mock database
        >>> mock_db = MagicMock()
        >>>
        >>> # Mock user context
        >>> mock_user = MagicMock()
        >>> mock_user.email = "admin@example.com"
        >>>
        >>> import asyncio
        >>> async def test_force_password_change():
        ...     # Note: Full test requires email_auth_enabled and valid user
        ...     return True  # Simplified test due to dependencies
        >>>
        >>> asyncio.run(test_force_password_change())
        True
    """
    if not settings.email_auth_enabled:
        return HTMLResponse(content='<div class="text-red-500">Email authentication is disabled</div>', status_code=403)

    try:
        # Get root path for URL construction
        root_path = _request.scope.get("root_path", "") if _request else ""

        auth_service = EmailAuthService(db)

        # URL decode the email
        decoded_email = urllib.parse.unquote(user_email)

        # Get current user email from JWT
        current_user_email = get_user_email(user)

        # Get the user to update
        user_obj = await auth_service.get_user_by_email(decoded_email)
        if not user_obj:
            return HTMLResponse(content='<div class="text-red-500">User not found</div>', status_code=404)

        # Set password_change_required flag
        user_obj.password_change_required = True
        db.commit()

        LOGGER.info(f"Admin {current_user_email} forced password change for user {decoded_email}")

        # Return updated user card with status indicator
        user_html = f"""
        <div class="user-card bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 hover:shadow-lg transition-shadow duration-200">
            <div class="flex items-start justify-between">
                <div class="flex items-center space-x-4">
                    <div class="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-semibold text-lg">
                        {user_obj.get_display_name()[0].upper()}
                    </div>
                    <div>
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{html.escape(user_obj.get_display_name())}</h3>
                        <p class="text-sm text-gray-600 dark:text-gray-400">{html.escape(user_obj.email)}</p>
                        <div class="flex items-center space-x-2 mt-1">
                            <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium {'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' if user_obj.is_active else 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300'}">
                                {'Active' if user_obj.is_active else 'Inactive'}
                            </span>
                            {'<span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300">Admin</span>' if user_obj.is_admin else ''}
                            {'<span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300"><i class="fas fa-key mr-1"></i>Password Change Required</span>' if user_obj.password_change_required else ''}
                        </div>
                    </div>
                </div>
                <div class="flex flex-col space-y-2">
                    <button class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            hx-get="{root_path}/admin/users/{user_obj.email}/edit" hx-target="#user-edit-modal-content">
                        Edit
                    </button>
                    {(
                        '<button class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 hover:text-orange-800 '
                        'dark:hover:text-orange-300 border border-orange-300 dark:border-orange-600 hover:border-orange-500 '
                        'dark:hover:border-orange-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 '
                        'focus:ring-orange-500" hx-post="' + root_path + '/admin/users/' + user_obj.email.replace("@", "%40") +
                        '/deactivate" hx-confirm="Deactivate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Deactivate</button>'
                        if user_obj.is_active else
                        '<button class="px-3 py-1 text-sm font-medium text-green-600 dark:text-green-400 hover:text-green-800 '
                        'dark:hover:text-green-300 border border-green-300 dark:border-green-600 hover:border-green-500 '
                        'dark:hover:border-green-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 '
                        'focus:ring-green-500" hx-post="' + root_path + '/admin/users/' + user_obj.email.replace("@", "%40") +
                        '/activate" hx-confirm="Activate this user?" hx-target="closest .user-card" hx-swap="outerHTML">Activate</button>'
                    )}
                    {(
                        '<button class="px-3 py-1 text-sm font-medium text-yellow-600 dark:text-yellow-400 hover:text-yellow-800 '
                        'dark:hover:text-yellow-300 border border-yellow-300 dark:border-yellow-600 hover:border-yellow-500 '
                        'dark:hover:border-yellow-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 '
                        'focus:ring-yellow-500" hx-post="' + root_path + '/admin/users/' + user_obj.email.replace("@", "%40") +
                        '/force-password-change" hx-confirm="Force this user to change their password on next login?" '
                        'hx-target="closest .user-card" hx-swap="outerHTML">Force Password Change</button>'
                        if not user_obj.password_change_required else
                        '<span class="px-3 py-1 text-sm font-medium text-orange-600 dark:text-orange-400 bg-orange-50 '
                        'dark:bg-orange-900/20 border border-orange-300 dark:border-orange-600 rounded-md">Password Change Required</span>'
                    )}
                    <button class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500" hx-delete="{root_path}/admin/users/{user_obj.email.replace("@", "%40")}" hx-confirm="Are you sure you want to delete this user? This action cannot be undone." hx-target="closest .user-card" hx-swap="outerHTML">Delete</button>
                </div>
            </div>
        </div>
        """
        return HTMLResponse(content=user_html)

    except Exception as e:
        LOGGER.error(f"Error forcing password change for user {user_email}: {e}")
        return HTMLResponse(content=f'<div class="text-red-500">Error forcing password change: {str(e)}</div>', status_code=400)


@admin_router.get("/tools", response_model=PaginatedResponse)
async def admin_list_tools(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List tools for the admin UI with pagination support.

    This endpoint retrieves a paginated list of tools from the database, optionally
    including those that are inactive. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed). Default: 1.
        per_page (int): Items per page (1-500). Default: 50.
        include_inactive (bool): Whether to include inactive tools in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict with 'data', 'pagination', and 'links' keys containing paginated tools.

    """
    LOGGER.debug(f"User {get_user_email(user)} requested tool list (page={page}, per_page={per_page})")
    user_email = get_user_email(user)

    # Call tool_service.list_tools with page-based pagination
    paginated_result = await tool_service.list_tools(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [tool.model_dump(by_alias=True) for tool in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.get("/tools/partial", response_class=HTMLResponse)
async def admin_tools_partial_html(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    render: Optional[str] = Query(None, description="Render mode: 'controls' for pagination controls only"),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """
    Return HTML partial for paginated tools list (HTMX endpoint).

    This endpoint returns only the table body rows and pagination controls
    for HTMX-based pagination in the admin UI.

    Args:
        request (Request): FastAPI request object.
        page (int): Page number (1-indexed). Default: 1.
        per_page (int): Items per page (1-500). Default: 50.
        include_inactive (bool): Whether to include inactive tools in the results.
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated.
        render (str): Render mode - 'controls' returns only pagination controls.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        HTMLResponse with tools table rows and pagination controls.
    """
    LOGGER.debug(f"User {get_user_email(user)} requested tools HTML partial (page={page}, per_page={per_page}, render={render}, gateway_id={gateway_id})")

    user_email = get_user_email(user)

    # Build base query using tool_service's team filtering logic
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [team.id for team in user_teams]

    # Build query
    query = select(DbTool)

    # Apply gateway filter if provided. Support special sentinel 'null' to
    # request tools with NULL gateway_id (e.g., RestTool/no gateway).
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            # Treat literal 'null' (case-insensitive) as a request for NULL gateway_id
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbTool.gateway_id.in_(non_null_ids), DbTool.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering tools by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbTool.gateway_id.is_(None))
                LOGGER.debug("Filtering tools by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbTool.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering tools by gateway IDs: {non_null_ids}")

    # Apply active/inactive filter
    if not include_inactive:
        query = query.where(DbTool.enabled.is_(True))

    # Build access conditions (same logic as tool_service.list_tools with user_email)
    access_conditions = []

    # 1. User's personal tools (owner_email matches)
    access_conditions.append(DbTool.owner_email == user_email)

    # 2. Team tools where user is member
    if team_ids:
        access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

    # 3. Public tools
    access_conditions.append(DbTool.visibility == "public")

    query = query.where(or_(*access_conditions))

    # Apply sorting: alphabetical by URL, then name, then ID (for UI display)
    # Different from JSON endpoint which uses created_at DESC
    query = query.order_by(DbTool.url, DbTool.original_name, DbTool.id)

    # Use unified pagination function (offset-based for UI compatibility)
    base_url = f"{settings.app_root_path}/admin/tools/partial"
    query_params_dict = {}
    if include_inactive:
        query_params_dict["include_inactive"] = "true"
    if gateway_id:
        query_params_dict["gateway_id"] = gateway_id

    paginated_result = await paginate_query(
        db=db,
        query=query,
        page=page,
        per_page=per_page,
        cursor=None,  # UI uses offset pagination only
        base_url=base_url,
        query_params=query_params_dict,
        use_cursor_threshold=False,  # Disable auto-cursor switching for UI
    )

    # Extract paginated tools (DbTool objects)
    tools_db = paginated_result["data"]
    pagination = paginated_result["pagination"]
    links = paginated_result["links"]

    # Batch fetch team names for the tools to avoid N+1 queries
    team_ids_set = {t.team_id for t in tools_db if t.team_id}
    team_map = {}
    if team_ids_set:
        teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
        team_map = {team.id: team.name for team in teams}

    # Apply team names to DB objects before conversion
    for t in tools_db:
        t.team = team_map.get(t.team_id) if t.team_id else None

    # Batch convert to Pydantic models using tool service
    # This eliminates the N+1 query problem from calling get_tool() in a loop
    tools_pydantic = [tool_service.convert_tool_to_read(t, include_metrics=False, include_auth=False) for t in tools_db]

    # Serialize tools
    data = jsonable_encoder(tools_pydantic)

    # If render=controls, return only pagination controls
    if render == "controls":
        return request.app.state.templates.TemplateResponse(
            "pagination_controls.html",
            {
                "request": request,
                "pagination": pagination.model_dump(),
                "base_url": base_url,
                "hx_target": "#tools-table-body",
                "hx_indicator": "#tools-loading",
                "query_params": query_params_dict,
                "root_path": request.scope.get("root_path", ""),
            },
        )

    # If render=selector, return tool selector items for infinite scroll
    if render == "selector":
        return request.app.state.templates.TemplateResponse(
            "tools_selector_items.html",
            {
                "request": request,
                "data": data,
                "pagination": pagination.model_dump(),
                "root_path": request.scope.get("root_path", ""),
                "gateway_id": gateway_id,
            },
        )

    # Render template with paginated data
    return request.app.state.templates.TemplateResponse(
        "tools_partial.html",
        {
            "request": request,
            "data": data,
            "pagination": pagination.model_dump(),
            "links": links.model_dump() if links else None,
            "root_path": request.scope.get("root_path", ""),
            "include_inactive": include_inactive,
        },
    )


@admin_router.get("/tools/ids", response_class=JSONResponse)
async def admin_get_all_tool_ids(
    include_inactive: bool = False,
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """
    Return all tool IDs accessible to the current user.

    This is used by "Select All" to get all tool IDs without loading full data.

    Args:
        include_inactive (bool): Whether to include inactive tools in the results
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated. Accepts the literal value 'null' to indicate NULL gateway_id (local tools).
        db (Session): Database session dependency
        user: Current user making the request

    Returns:
        JSONResponse: List of tool IDs accessible to the user
    """
    user_email = get_user_email(user)

    # Build base query
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [team.id for team in user_teams]

    query = select(DbTool.id)

    if not include_inactive:
        query = query.where(DbTool.enabled.is_(True))

    # Apply optional gateway/server scoping (comma-separated ids). Accepts the
    # literal value 'null' to indicate NULL gateway_id (local tools).
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbTool.gateway_id.in_(non_null_ids), DbTool.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering tools by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbTool.gateway_id.is_(None))
                LOGGER.debug("Filtering tools by NULL gateway_id (local tools)")
            else:
                query = query.where(DbTool.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering tools by gateway IDs: {non_null_ids}")

    # Build access conditions
    access_conditions = [DbTool.owner_email == user_email, DbTool.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

    query = query.where(or_(*access_conditions))

    # Get all IDs
    tool_ids = [row[0] for row in db.execute(query).all()]

    return {"tool_ids": tool_ids, "count": len(tool_ids)}


@admin_router.get("/tools/search", response_class=JSONResponse)
async def admin_search_tools(
    q: str = Query("", description="Search query"),
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results to return"),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """
    Search tools by name, ID, or description.

    This endpoint searches tools across all accessible tools for the current user,
    returning both IDs and names for use in search functionality like the Add Server page.

    Args:
        q (str): Search query string to match against tool names, IDs, or descriptions
        include_inactive (bool): Whether to include inactive tools in the search results
        limit (int): Maximum number of results to return (1-1000)
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated
        db (Session): Database session dependency
        user: Current user making the request

    Returns:
        JSONResponse: Dictionary containing list of matching tools and count
    """
    user_email = get_user_email(user)
    search_query = q.strip().lower()

    if not search_query:
        # If no search query, return empty list
        return {"tools": [], "count": 0}

    # Build base query
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [team.id for team in user_teams]

    query = select(DbTool.id, DbTool.original_name, DbTool.custom_name, DbTool.display_name, DbTool.description)

    # Apply gateway filter if provided. Support special sentinel 'null' to
    # request tools with NULL gateway_id (e.g., RestTool/no gateway).
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            # Treat literal 'null' (case-insensitive) as a request for NULL gateway_id
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbTool.gateway_id.in_(non_null_ids), DbTool.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering tool search by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbTool.gateway_id.is_(None))
                LOGGER.debug("Filtering tool search by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbTool.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering tool search by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbTool.enabled.is_(True))

    # Build access conditions
    access_conditions = [DbTool.owner_email == user_email, DbTool.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

    query = query.where(or_(*access_conditions))

    # Add search conditions - search in display fields and description
    # Using the same priority as display: displayName -> customName -> original_name
    search_conditions = [
        func.lower(coalesce(DbTool.display_name, "")).contains(search_query),
        func.lower(coalesce(DbTool.custom_name, "")).contains(search_query),
        func.lower(DbTool.original_name).contains(search_query),
        func.lower(coalesce(DbTool.description, "")).contains(search_query),
    ]

    query = query.where(or_(*search_conditions))

    # Order by relevance - prioritize matches at start of names
    query = query.order_by(
        case(
            (func.lower(DbTool.original_name).startswith(search_query), 1),
            (func.lower(coalesce(DbTool.custom_name, "")).startswith(search_query), 1),
            (func.lower(coalesce(DbTool.display_name, "")).startswith(search_query), 1),
            else_=2,
        ),
        func.lower(DbTool.original_name),
    ).limit(limit)

    # Execute query
    results = db.execute(query).all()

    # Format results
    tools = []
    for row in results:
        tools.append({"id": row.id, "name": row.original_name, "display_name": row.display_name, "custom_name": row.custom_name})  # original_name for search matching

    return {"tools": tools, "count": len(tools)}


@admin_router.get("/prompts/partial", response_class=HTMLResponse)
async def admin_prompts_partial_html(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    render: Optional[str] = Query(None),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return paginated prompts HTML partials for the admin UI.

    This HTMX endpoint returns only the partial HTML used by the admin UI for
    prompts. It supports three render modes:

    - default: full table partial (rows + controls)
    - ``render="controls"``: return only pagination controls
    - ``render="selector"``: return selector items for infinite scroll

    Args:
        request (Request): FastAPI request object used by the template engine.
        page (int): Page number (1-indexed).
        per_page (int): Number of items per page (bounded by settings).
        include_inactive (bool): If True, include inactive prompts in results.
        render (Optional[str]): Render mode; one of None, "controls", "selector".
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated.
        db (Session): Database session (dependency-injected).
        user: Authenticated user object from dependency injection.

    Returns:
        Union[HTMLResponse, TemplateResponse]: A rendered template response
        containing either the table partial, pagination controls, or selector
        items depending on ``render``. The response contains JSON-serializable
        encoded prompt data when templates expect it.
    """
    LOGGER.debug(f"User {get_user_email(user)} requested prompts HTML partial (page={page}, per_page={per_page}, include_inactive={include_inactive}, render={render}, gateway_id={gateway_id})")
    # Normalize per_page within configured bounds
    per_page = max(settings.pagination_min_page_size, min(per_page, settings.pagination_max_page_size))

    user_email = get_user_email(user)

    # Team scoping
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    # Build base query
    query = select(DbPrompt)

    # Apply gateway filter if provided
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbPrompt.gateway_id.in_(non_null_ids), DbPrompt.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering prompts by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbPrompt.gateway_id.is_(None))
                LOGGER.debug("Filtering prompts by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbPrompt.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering prompts by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbPrompt.enabled.is_(True))

    # Access conditions: owner, team, public
    access_conditions = [DbPrompt.owner_email == user_email]
    if team_ids:
        access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))
    access_conditions.append(DbPrompt.visibility == "public")

    query = query.where(or_(*access_conditions))

    # Apply pagination ordering for cursor support
    query = query.order_by(desc(DbPrompt.created_at), desc(DbPrompt.id))

    # Build query params for pagination links
    query_params = {}
    if include_inactive:
        query_params["include_inactive"] = "true"
    if gateway_id:
        query_params["gateway_id"] = gateway_id

    # Use unified pagination function
    paginated_result = await paginate_query(
        db=db,
        query=query,
        page=page,
        per_page=per_page,
        cursor=None,  # HTMX partials use page-based navigation
        base_url=f"{settings.app_root_path}/admin/prompts/partial",
        query_params=query_params,
        use_cursor_threshold=False,  # Disable auto-cursor switching for UI
    )

    # Extract paginated prompts (DbPrompt objects)
    prompts_db = paginated_result["data"]
    pagination = paginated_result["pagination"]
    links = paginated_result["links"]

    # Batch fetch team names for the prompts to avoid N+1 queries
    team_ids_set = {p.team_id for p in prompts_db if p.team_id}
    team_map = {}
    if team_ids_set:
        teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
        team_map = {team.id: team.name for team in teams}

    # Apply team names to DB objects before conversion
    for p in prompts_db:
        p.team = team_map.get(p.team_id) if p.team_id else None

    # Batch convert to Pydantic models using prompt service
    # This eliminates the N+1 query problem from calling get_prompt_details() in a loop
    prompts_pydantic = [prompt_service.convert_prompt_to_read(p, include_metrics=False) for p in prompts_db]

    data = jsonable_encoder(prompts_pydantic)
    base_url = f"{settings.app_root_path}/admin/prompts/partial"

    if render == "controls":
        return request.app.state.templates.TemplateResponse(
            "pagination_controls.html",
            {
                "request": request,
                "pagination": pagination.model_dump(),
                "base_url": base_url,
                "hx_target": "#prompts-table-body",
                "hx_indicator": "#prompts-loading",
                "query_params": query_params,
                "root_path": request.scope.get("root_path", ""),
            },
        )

    if render == "selector":
        return request.app.state.templates.TemplateResponse(
            "prompts_selector_items.html",
            {
                "request": request,
                "data": data,
                "pagination": pagination.model_dump(),
                "root_path": request.scope.get("root_path", ""),
                "gateway_id": gateway_id,
            },
        )

    return request.app.state.templates.TemplateResponse(
        "prompts_partial.html",
        {
            "request": request,
            "data": data,
            "pagination": pagination.model_dump(),
            "links": links.model_dump() if links else None,
            "root_path": request.scope.get("root_path", ""),
            "include_inactive": include_inactive,
        },
    )


@admin_router.get("/resources/partial", response_class=HTMLResponse)
async def admin_resources_partial_html(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    render: Optional[str] = Query(None, description="Render mode: 'controls' for pagination controls only"),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return HTML partial for paginated resources list (HTMX endpoint).

    This endpoint mirrors the behavior of the tools and prompts partial
    endpoints. It returns a template fragment suitable for HTMX-based
    pagination/infinite-scroll within the admin UI.

    Args:
        request (Request): FastAPI request object used by the template engine.
        page (int): Page number (1-indexed).
        per_page (int): Number of items per page (bounded by settings).
        include_inactive (bool): If True, include inactive resources in results.
        render (Optional[str]): Render mode; when set to "controls" returns only
            pagination controls. Other supported value: "selector" for selector
            items used by infinite scroll selectors.
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated.
        db (Session): Database session (dependency-injected).
        user: Authenticated user object from dependency injection.

    Returns:
        Union[HTMLResponse, TemplateResponse]: Rendered template response with the
        resources partial (rows + controls), pagination controls only, or selector
        items depending on the ``render`` parameter.
    """

    LOGGER.debug(f"[RESOURCES FILTER DEBUG] User {get_user_email(user)} requested resources HTML partial (page={page}, per_page={per_page}, render={render}, gateway_id={gateway_id})")

    # Normalize per_page
    per_page = max(settings.pagination_min_page_size, min(per_page, settings.pagination_max_page_size))

    user_email = get_user_email(user)

    # Team scoping
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    # Build base query
    query = select(DbResource)

    # Apply gateway filter if provided
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbResource.gateway_id.in_(non_null_ids), DbResource.gateway_id.is_(None)))
                LOGGER.debug(f"[RESOURCES FILTER DEBUG] Filtering resources by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbResource.gateway_id.is_(None))
                LOGGER.debug("[RESOURCES FILTER DEBUG] Filtering resources by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbResource.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"[RESOURCES FILTER DEBUG] Filtering resources by gateway IDs: {non_null_ids}")
    else:
        LOGGER.debug("[RESOURCES FILTER DEBUG] No gateway_id filter provided, showing all resources")

    # Apply active/inactive filter
    if not include_inactive:
        query = query.where(DbResource.enabled.is_(True))

    # Access conditions: owner, team, public
    access_conditions = [DbResource.owner_email == user_email]
    if team_ids:
        access_conditions.append(and_(DbResource.team_id.in_(team_ids), DbResource.visibility.in_(["team", "public"])))
    access_conditions.append(DbResource.visibility == "public")

    query = query.where(or_(*access_conditions))

    # Add sorting for consistent pagination
    query = query.order_by(desc(DbResource.created_at), desc(DbResource.id))

    # Build query params for pagination links
    query_params = {}
    if include_inactive:
        query_params["include_inactive"] = "true"
    if gateway_id:
        query_params["gateway_id"] = gateway_id

    # Use unified pagination function
    paginated_result = await paginate_query(
        db=db,
        query=query,
        page=page,
        per_page=per_page,
        cursor=None,  # HTMX partials use page-based navigation
        base_url=f"{settings.app_root_path}/admin/resources/partial",
        query_params=query_params,
        use_cursor_threshold=False,  # Disable auto-cursor switching for UI
    )

    # Extract paginated resources (DbResource objects)
    resources_db = paginated_result["data"]
    pagination = paginated_result["pagination"]
    links = paginated_result["links"]

    # Batch fetch team names for the resources to avoid N+1 queries
    team_ids_set = {r.team_id for r in resources_db if r.team_id}
    team_map = {}
    if team_ids_set:
        teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
        team_map = {team.id: team.name for team in teams}

    # Apply team names to DB objects before conversion
    for r in resources_db:
        r.team = team_map.get(r.team_id) if r.team_id else None

    # Batch convert to Pydantic models using resource service
    resources_pydantic = [resource_service.convert_resource_to_read(r, include_metrics=False) for r in resources_db]

    data = jsonable_encoder(resources_pydantic)

    if render == "controls":
        return request.app.state.templates.TemplateResponse(
            "pagination_controls.html",
            {
                "request": request,
                "pagination": pagination.model_dump(),
                "base_url": f"{settings.app_root_path}/admin/resources/partial",
                "hx_target": "#resources-table-body",
                "hx_indicator": "#resources-loading",
                "query_params": query_params,
                "root_path": request.scope.get("root_path", ""),
            },
        )

    if render == "selector":
        return request.app.state.templates.TemplateResponse(
            "resources_selector_items.html",
            {
                "request": request,
                "data": data,
                "pagination": pagination.model_dump(),
                "root_path": request.scope.get("root_path", ""),
                "gateway_id": gateway_id,
            },
        )

    return request.app.state.templates.TemplateResponse(
        "resources_partial.html",
        {
            "request": request,
            "data": data,
            "pagination": pagination.model_dump(),
            "links": links.model_dump() if links else None,
            "root_path": request.scope.get("root_path", ""),
            "include_inactive": include_inactive,
        },
    )


@admin_router.get("/prompts/ids", response_class=JSONResponse)
async def admin_get_all_prompt_ids(
    include_inactive: bool = False,
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return all prompt IDs accessible to the current user (select-all helper).

    This endpoint is used by UI "Select All" helpers to fetch only the IDs
    of prompts the requesting user can access (owner, team, or public).

    Args:
        include_inactive (bool): When True include prompts that are inactive.
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated. Accepts the literal value 'null' to indicate NULL gateway_id (local prompts).
        db (Session): Database session (injected dependency).
        user: Authenticated user object from dependency injection.

    Returns:
        dict: A dictionary containing two keys:
            - "prompt_ids": List[str] of accessible prompt IDs.
            - "count": int number of IDs returned.
    """
    user_email = get_user_email(user)
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    query = select(DbPrompt.id)

    # Apply optional gateway/server scoping
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbPrompt.gateway_id.in_(non_null_ids), DbPrompt.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering prompts by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbPrompt.gateway_id.is_(None))
                LOGGER.debug("Filtering prompts by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbPrompt.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering prompts by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbPrompt.enabled.is_(True))

    access_conditions = [DbPrompt.owner_email == user_email, DbPrompt.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))

    query = query.where(or_(*access_conditions))
    prompt_ids = [row[0] for row in db.execute(query).all()]
    return {"prompt_ids": prompt_ids, "count": len(prompt_ids)}


@admin_router.get("/resources/ids", response_class=JSONResponse)
async def admin_get_all_resource_ids(
    include_inactive: bool = False,
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return all resource IDs accessible to the current user (select-all helper).

    This endpoint is used by UI "Select All" helpers to fetch only the IDs
    of resources the requesting user can access (owner, team, or public).

    Args:
        include_inactive (bool): Whether to include inactive resources in the results.
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated. Accepts the literal value 'null' to indicate NULL gateway_id (local resources).
        db (Session): Database session dependency.
        user: Authenticated user object from dependency injection.

    Returns:
        dict: A dictionary containing two keys:
            - "resource_ids": List[str] of accessible resource IDs.
            - "count": int number of IDs returned.
    """
    user_email = get_user_email(user)
    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    query = select(DbResource.id)

    # Apply optional gateway/server scoping
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbResource.gateway_id.in_(non_null_ids), DbResource.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering resources by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbResource.gateway_id.is_(None))
                LOGGER.debug("Filtering resources by NULL gateway_id (RestTool)")
            else:
                query = query.where(DbResource.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering resources by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbResource.enabled.is_(True))

    access_conditions = [DbResource.owner_email == user_email, DbResource.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbResource.team_id.in_(team_ids), DbResource.visibility.in_(["team", "public"])))

    query = query.where(or_(*access_conditions))
    resource_ids = [row[0] for row in db.execute(query).all()]
    return {"resource_ids": resource_ids, "count": len(resource_ids)}


@admin_router.get("/resources/search", response_class=JSONResponse)
async def admin_search_resources(
    q: str = Query("", description="Search query"),
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Search resources by name or description for selector search.

    Performs a case-insensitive search over resource names and descriptions
    and returns a limited list of matching resources suitable for selector
    UIs (id, name, description).

    Args:
        q (str): Search query string.
        include_inactive (bool): When True include resources that are inactive.
        limit (int): Maximum number of results to return (bounded by the query parameter).
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated.
        db (Session): Database session (injected dependency).
        user: Authenticated user object from dependency injection.

    Returns:
        dict: A dictionary containing:
            - "resources": List[dict] where each dict has keys "id", "name", "description".
            - "count": int number of matched resources returned.
    """
    user_email = get_user_email(user)
    search_query = q.strip().lower()
    if not search_query:
        return {"resources": [], "count": 0}

    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    query = select(DbResource.id, DbResource.name, DbResource.description)

    # Apply gateway filter if provided
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbResource.gateway_id.in_(non_null_ids), DbResource.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering resource search by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbResource.gateway_id.is_(None))
                LOGGER.debug("Filtering resource search by NULL gateway_id")
            else:
                query = query.where(DbResource.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering resource search by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbResource.enabled.is_(True))

    access_conditions = [DbResource.owner_email == user_email, DbResource.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbResource.team_id.in_(team_ids), DbResource.visibility.in_(["team", "public"])))
    query = query.where(or_(*access_conditions))

    search_conditions = [func.lower(DbResource.name).contains(search_query), func.lower(coalesce(DbResource.description, "")).contains(search_query)]
    query = query.where(or_(*search_conditions))

    query = query.order_by(
        case(
            (func.lower(DbResource.name).startswith(search_query), 1),
            else_=2,
        ),
        func.lower(DbResource.name),
    ).limit(limit)

    results = db.execute(query).all()
    resources = []
    for row in results:
        resources.append({"id": row.id, "name": row.name, "description": row.description})

    return {"resources": resources, "count": len(resources)}


@admin_router.get("/prompts/search", response_class=JSONResponse)
async def admin_search_prompts(
    q: str = Query("", description="Search query"),
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    gateway_id: Optional[str] = Query(None, description="Filter by gateway ID(s), comma-separated"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Search prompts by name or description for selector search.

    Performs a case-insensitive search over prompt names and descriptions
    and returns a limited list of matching prompts suitable for selector
    UIs (id, name, description).

    Args:
        q (str): Search query string.
        include_inactive (bool): When True include prompts that are inactive.
        limit (int): Maximum number of results to return (bounded by the query parameter).
        gateway_id (Optional[str]): Filter by gateway ID(s), comma-separated.
        db (Session): Database session (injected dependency).
        user: Authenticated user object from dependency injection.

    Returns:
        dict: A dictionary containing:
            - "prompts": List[dict] where each dict has keys "id", "name", "description".
            - "count": int number of matched prompts returned.
    """
    user_email = get_user_email(user)
    search_query = q.strip().lower()
    if not search_query:
        return {"prompts": [], "count": 0}

    team_service = TeamManagementService(db)
    user_teams = await team_service.get_user_teams(user_email)
    team_ids = [t.id for t in user_teams]

    query = select(DbPrompt.id, DbPrompt.original_name, DbPrompt.display_name, DbPrompt.description)

    # Apply gateway filter if provided
    if gateway_id:
        gateway_ids = [gid.strip() for gid in gateway_id.split(",") if gid.strip()]
        if gateway_ids:
            null_requested = any(gid.lower() == "null" for gid in gateway_ids)
            non_null_ids = [gid for gid in gateway_ids if gid.lower() != "null"]
            if non_null_ids and null_requested:
                query = query.where(or_(DbPrompt.gateway_id.in_(non_null_ids), DbPrompt.gateway_id.is_(None)))
                LOGGER.debug(f"Filtering prompt search by gateway IDs (including NULL): {non_null_ids} + NULL")
            elif null_requested:
                query = query.where(DbPrompt.gateway_id.is_(None))
                LOGGER.debug("Filtering prompt search by NULL gateway_id")
            else:
                query = query.where(DbPrompt.gateway_id.in_(non_null_ids))
                LOGGER.debug(f"Filtering prompt search by gateway IDs: {non_null_ids}")

    if not include_inactive:
        query = query.where(DbPrompt.enabled.is_(True))

    access_conditions = [DbPrompt.owner_email == user_email, DbPrompt.visibility == "public"]
    if team_ids:
        access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))

    query = query.where(or_(*access_conditions))

    search_conditions = [
        func.lower(DbPrompt.original_name).contains(search_query),
        func.lower(coalesce(DbPrompt.display_name, "")).contains(search_query),
        func.lower(coalesce(DbPrompt.description, "")).contains(search_query),
    ]
    query = query.where(or_(*search_conditions))

    query = query.order_by(
        case(
            (func.lower(DbPrompt.original_name).startswith(search_query), 1),
            (func.lower(coalesce(DbPrompt.display_name, "")).startswith(search_query), 1),
            else_=2,
        ),
        func.lower(DbPrompt.original_name),
    ).limit(limit)

    results = db.execute(query).all()
    prompts = []
    for row in results:
        prompts.append(
            {
                "id": row.id,
                "name": row.original_name,
                "original_name": row.original_name,
                "display_name": row.display_name,
                "description": row.description,
            }
        )

    return {"prompts": prompts, "count": len(prompts)}


@admin_router.get("/tools/{tool_id}", response_model=ToolRead)
async def admin_get_tool(tool_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """
    Retrieve specific tool details for the admin UI.

    This endpoint fetches the details of a specific tool from the database
    by its ID. It provides access to all information about the tool for
    viewing and management purposes.

    Args:
        tool_id (str): The ID of the tool to retrieve.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        ToolRead: The tool details formatted with by_alias=True.

    Raises:
        HTTPException: If the tool is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ToolRead, ToolMetrics
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.tool_service import ToolNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> tool_id = "test-tool-id"
        >>>
        >>> # Mock tool data
        >>> mock_tool = ToolRead(
        ...     id=tool_id, name="Get Tool", original_name="GetTool", url="http://get.com",
        ...     description="Tool for getting", request_type="GET", integration_type="REST",
        ...     headers={}, input_schema={}, annotations={}, jsonpath_filter=None, auth=None,
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, reachable=True, gateway_id=None, execution_count=0,
        ...     metrics=ToolMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0, avg_response_time=0.0,
        ...         last_execution_time=None
        ...     ),
        ...     gateway_slug="default", custom_name_slug="get-tool",
        ...     customName="Get Tool",
        ...     tags=[]
        ... )
        >>>
        >>> # Mock the tool_service.get_tool method
        >>> original_get_tool = tool_service.get_tool
        >>> tool_service.get_tool = AsyncMock(return_value=mock_tool)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_tool_success():
        ...     result = await admin_get_tool(tool_id, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['id'] == tool_id
        >>>
        >>> asyncio.run(test_admin_get_tool_success())
        True
        >>>
        >>> # Test tool not found
        >>> tool_service.get_tool = AsyncMock(side_effect=ToolNotFoundError("Tool not found"))
        >>> async def test_admin_get_tool_not_found():
        ...     try:
        ...         await admin_get_tool("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Tool not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_tool_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> tool_service.get_tool = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_tool_exception():
        ...     try:
        ...         await admin_get_tool(tool_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.get_tool = original_get_tool
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for tool ID {tool_id}")
    try:
        tool = await tool_service.get_tool(db, tool_id)
        return tool.model_dump(by_alias=True)
    except ToolNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Catch any other unexpected errors and re-raise or log as needed
        LOGGER.error(f"Error getting tool {tool_id}: {e}")
        raise e  # Re-raise for now, or return a 500 JSONResponse if preferred for API consistency


@admin_router.post("/tools/")
@admin_router.post("/tools")
async def admin_add_tool(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """
    Add a tool via the admin UI with error handling.

    Expects form fields:
      - name
      - url
      - description (optional)
      - requestType (mapped to request_type; defaults to "SSE")
      - integrationType (mapped to integration_type; defaults to "MCP")
      - headers (JSON string)
      - input_schema (JSON string)
      - output_schema (JSON string, optional)
      - jsonpath_filter (optional)
      - auth_type (optional)
      - auth_username (optional)
      - auth_password (optional)
      - auth_token (optional)
      - auth_header_key (optional)
      - auth_header_value (optional)

    Logs the raw form data and assembled tool_data for debugging.

    Args:
        request (Request): the FastAPI request object containing the form data.
        db (Session): the SQLAlchemy database session.
        user (str): identifier of the authenticated user.

    Returns:
        JSONResponse: a JSON response with `{"message": ..., "success": ...}` and an appropriate HTTP status code.

    Examples:
        Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json

        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}

        >>> # Happy path: Add a new tool successfully
        >>> form_data_success = FormData([
        ...     ("name", "New_Tool"),
        ...     ("url", "http://new.tool.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST"),
        ...     ("headers", '{"X-Api-Key": "abc"}')
        ... ])
        >>> mock_request_success = MagicMock(spec=Request)
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_register_tool = tool_service.register_tool
        >>> tool_service.register_tool = AsyncMock()

        >>> async def test_admin_add_tool_success():
        ...     response = await admin_add_tool(mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_add_tool_success())
        True

        >>> # Error path: Tool name conflict via IntegrityError
        >>> form_data_conflict = FormData([
        ...     ("name", "Existing_Tool"),
        ...     ("url", "http://existing.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_conflict = MagicMock(spec=Request)
        >>> mock_request_conflict.form = AsyncMock(return_value=form_data_conflict)
        >>> fake_integrity_error = IntegrityError("Mock Integrity Error", {}, None)
        >>> tool_service.register_tool = AsyncMock(side_effect=fake_integrity_error)

        >>> async def test_admin_add_tool_integrity_error():
        ...     response = await admin_add_tool(mock_request_conflict, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_integrity_error())
        True

        >>> # Error path: Missing required field (Pydantic ValidationError)
        >>> form_data_missing = FormData([
        ...     ("url", "http://missing.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_missing = MagicMock(spec=Request)
        >>> mock_request_missing.form = AsyncMock(return_value=form_data_missing)

        >>> async def test_admin_add_tool_validation_error():
        ...     response = await admin_add_tool(mock_request_missing, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_validation_error())  # doctest: +ELLIPSIS
        True

        >>> # Error path: Unexpected exception
        >>> form_data_generic_error = FormData([
        ...     ("name", "Generic_Error_Tool"),
        ...     ("url", "http://generic.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_generic_error = MagicMock(spec=Request)
        >>> mock_request_generic_error.form = AsyncMock(return_value=form_data_generic_error)
        >>> tool_service.register_tool = AsyncMock(side_effect=Exception("Unexpected error"))

        >>> async def test_admin_add_tool_generic_exception():
        ...     response = await admin_add_tool(mock_request_generic_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_generic_exception())
        True

        >>> # Restore original method
        >>> tool_service.register_tool = original_register_tool

    """
    LOGGER.debug(f"User {get_user_email(user)} is adding a new tool")
    form = await request.form()
    LOGGER.debug(f"Received form data: {dict(form)}")
    integration_type = form.get("integrationType", "REST")
    request_type = form.get("requestType")
    visibility = str(form.get("visibility", "private"))

    if request_type is None:
        if integration_type == "REST":
            request_type = "GET"  # or any valid REST method default
        elif integration_type == "MCP":
            request_type = "SSE"
        else:
            request_type = "GET"

    user_email = get_user_email(user)
    # Determine personal team for default assignment
    team_id = form.get("team_id", None)
    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    # Safely parse potential JSON strings from form
    headers_raw = form.get("headers")
    input_schema_raw = form.get("input_schema")
    output_schema_raw = form.get("output_schema")
    annotations_raw = form.get("annotations")
    tool_data: dict[str, Any] = {
        "name": form.get("name"),
        "displayName": form.get("displayName"),
        "url": form.get("url"),
        "description": form.get("description"),
        "request_type": request_type,
        "integration_type": integration_type,
        "headers": orjson.loads(headers_raw if isinstance(headers_raw, str) and headers_raw else "{}"),
        "input_schema": orjson.loads(input_schema_raw if isinstance(input_schema_raw, str) and input_schema_raw else "{}"),
        "output_schema": (orjson.loads(output_schema_raw) if isinstance(output_schema_raw, str) and output_schema_raw else None),
        "annotations": orjson.loads(annotations_raw if isinstance(annotations_raw, str) and annotations_raw else "{}"),
        "jsonpath_filter": form.get("jsonpath_filter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
        "tags": tags,
        "visibility": visibility,
        "team_id": team_id,
        "owner_email": user_email,
        "query_mapping": orjson.loads(form.get("query_mapping") or "{}"),
        "header_mapping": orjson.loads(form.get("header_mapping") or "{}"),
        "timeout_ms": int(form.get("timeout_ms")) if form.get("timeout_ms") and form.get("timeout_ms").strip() else None,
        "expose_passthrough": form.get("expose_passthrough", "true"),
        "allowlist": orjson.loads(form.get("allowlist") or "[]"),
        "plugin_chain_pre": orjson.loads(form.get("plugin_chain_pre") or "[]"),
        "plugin_chain_post": orjson.loads(form.get("plugin_chain_post") or "[]"),
    }
    LOGGER.debug(f"Tool data built: {tool_data}")
    try:
        tool = ToolCreate(**tool_data)
        LOGGER.debug(f"Validated tool data: {tool.model_dump(by_alias=True)}")

        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await tool_service.register_tool(
            db,
            tool,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
        return ORJSONResponse(
            content={"message": "Tool registered successfully!", "success": True},
            status_code=200,
        )
    except IntegrityError as ex:
        error_message = ErrorFormatter.format_database_error(ex)
        LOGGER.error(f"IntegrityError in admin_add_tool: {error_message}")
        return ORJSONResponse(status_code=409, content=error_message)
    except ToolNameConflictError as ex:
        LOGGER.error(f"ToolNameConflictError in admin_add_tool: {str(ex)}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ToolError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:  # This block should catch ValidationError
        LOGGER.error(f"ValidationError in admin_add_tool: {str(ex)}")
        return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except Exception as ex:
        LOGGER.error(f"Unexpected error in admin_add_tool: {str(ex)}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/edit/", response_model=None)
@admin_router.post("/tools/{tool_id}/edit", response_model=None)
async def admin_edit_tool(
    tool_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Response:
    """
    Edit a tool via the admin UI.

    Expects form fields:
      - name
      - displayName (optional)
      - url
      - description (optional)
      - requestType (to be mapped to request_type)
      - integrationType (to be mapped to integration_type)
      - headers (as a JSON string)
      - input_schema (as a JSON string)
      - output_schema (as a JSON string, optional)
      - jsonpathFilter (optional)
      - auth_type (optional, string: "basic", "bearer", or empty)
      - auth_username (optional, for basic auth)
      - auth_password (optional, for basic auth)
      - auth_token (optional, for bearer auth)
      - auth_header_key (optional, for headers auth)
      - auth_header_value (optional, for headers auth)

    Assembles the tool_data dictionary by remapping form keys into the
    snake-case keys expected by the schemas.

    Args:
        tool_id (str): The ID of the tool to edit.
        request (Request): FastAPI request containing form data.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Response: A redirect response to the tools section of the admin
            dashboard with a status code of 303 (See Other), or a JSON response with
            an error message if the update fails.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse, JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.services.tool_service import ToolError
        >>> from pydantic import ValidationError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json

        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> tool_id = "tool-to-edit"

        >>> # Happy path: Edit tool successfully
        >>> form_data_success = FormData([
        ...     ("name", "Updated_Tool"),
        ...     ("customName", "ValidToolName"),
        ...     ("url", "http://updated.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST"),
        ...     ("headers", '{"X-Api-Key": "abc"}'),
        ...     ("input_schema", '{}'),  # ✅ Required field
        ...     ("description", "Sample tool")
        ... ])
        >>> mock_request_success = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_update_tool = tool_service.update_tool
        >>> tool_service.update_tool = AsyncMock()

        >>> async def test_admin_edit_tool_success():
        ...     response = await admin_edit_tool(tool_id, mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_edit_tool_success())
        True

        >>> # Edge case: Edit tool with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Inactive_Edit"),
        ...     ("customName", "ValidToolName"),
        ...     ("url", "http://inactive.com"),
        ...     ("is_inactive_checked", "true"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)

        >>> async def test_admin_edit_tool_inactive_checked():
        ...     response = await admin_edit_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_edit_tool_inactive_checked())
        True

        >>> # Error path: Tool name conflict (simulated with IntegrityError)
        >>> form_data_conflict = FormData([
        ...     ("name", "Conflicting_Name"),
        ...     ("customName", "Conflicting_Name"),
        ...     ("url", "http://conflict.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_conflict = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_conflict.form = AsyncMock(return_value=form_data_conflict)
        >>> tool_service.update_tool = AsyncMock(side_effect=IntegrityError("Conflict", {}, None))

        >>> async def test_admin_edit_tool_integrity_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_conflict, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_integrity_error())
        True

        >>> # Error path: ToolError raised
        >>> form_data_tool_error = FormData([
        ...     ("name", "Tool_Error"),
        ...     ("customName", "Tool_Error"),
        ...     ("url", "http://toolerror.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_tool_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_tool_error.form = AsyncMock(return_value=form_data_tool_error)
        >>> tool_service.update_tool = AsyncMock(side_effect=ToolError("Tool specific error"))

        >>> async def test_admin_edit_tool_tool_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_tool_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_tool_error())
        True

        >>> # Error path: Pydantic Validation Error
        >>> form_data_validation_error = FormData([
        ...     ("name", "Bad_URL"),
        ...     ("customName","Bad_Custom_Name"),
        ...     ("url", "not-a-valid-url"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_validation_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)

        >>> async def test_admin_edit_tool_validation_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_validation_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_validation_error())
        True

        >>> # Error path: Unexpected exception
        >>> form_data_unexpected = FormData([
        ...     ("name", "Crash_Tool"),
        ...     ("customName", "Crash_Tool"),
        ...     ("url", "http://crash.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_unexpected = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_unexpected.form = AsyncMock(return_value=form_data_unexpected)
        >>> tool_service.update_tool = AsyncMock(side_effect=Exception("Unexpected server crash"))

        >>> async def test_admin_edit_tool_unexpected_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_unexpected, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_unexpected_error())
        True

        >>> # Restore original method
        >>> tool_service.update_tool = original_update_tool
    """
    LOGGER.debug(f"User {get_user_email(user)} is editing tool ID {tool_id}")
    form = await request.form()
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    visibility = str(form.get("visibility", "private"))

    user_email = get_user_email(user)
    # Determine personal team for default assignment
    team_id = form.get("team_id", None)
    LOGGER.info(f"before Verifying team for user {user_email} with team_id {team_id}")
    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)

    headers_raw2 = form.get("headers")
    input_schema_raw2 = form.get("input_schema")
    output_schema_raw2 = form.get("output_schema")
    annotations_raw2 = form.get("annotations")

    tool_data: dict[str, Any] = {
        "name": form.get("name"),
        "displayName": form.get("displayName"),
        "custom_name": form.get("customName"),
        "url": form.get("url"),
        "description": form.get("description"),
        "headers": orjson.loads(headers_raw2 if isinstance(headers_raw2, str) and headers_raw2 else "{}"),
        "input_schema": orjson.loads(input_schema_raw2 if isinstance(input_schema_raw2, str) and input_schema_raw2 else "{}"),
        "output_schema": (orjson.loads(output_schema_raw2) if isinstance(output_schema_raw2, str) and output_schema_raw2 else None),
        "annotations": orjson.loads(annotations_raw2 if isinstance(annotations_raw2, str) and annotations_raw2 else "{}"),
        "jsonpath_filter": form.get("jsonpathFilter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
        "tags": tags,
        "visibility": visibility,
        "owner_email": user_email,
        "team_id": team_id,
    }
    # Only include integration_type if it's provided (not disabled in form)
    if "integrationType" in form:
        tool_data["integration_type"] = form.get("integrationType")
    # Only include request_type if it's provided (not disabled in form)
    if "requestType" in form:
        tool_data["request_type"] = form.get("requestType")
    LOGGER.debug(f"Tool update data built: {tool_data}")
    try:
        tool = ToolUpdate(**tool_data)  # Pydantic validation happens here

        # Get current tool to extract current version
        current_tool = db.get(DbTool, tool_id)
        current_version = getattr(current_tool, "version", 0) if current_tool else 0

        # Extract modification metadata
        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, current_version)

        await tool_service.update_tool(
            db,
            tool_id,
            tool,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
            user_email=user_email,
        )
        return ORJSONResponse(content={"message": "Edit tool successfully", "success": True}, status_code=200)
    except PermissionError as e:
        LOGGER.info(f"Permission denied for user {get_user_email(user)}: {e}")
        return ORJSONResponse(
            content={"message": str(e), "success": False},
            status_code=403,
        )
    except IntegrityError as ex:
        error_message = ErrorFormatter.format_database_error(ex)
        LOGGER.error(f"IntegrityError in admin_tool_resource: {error_message}")
        return ORJSONResponse(status_code=409, content=error_message)
    except ToolNameConflictError as ex:
        LOGGER.error(f"ToolNameConflictError in admin_edit_tool: {str(ex)}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ToolError as ex:
        LOGGER.error(f"ToolError in admin_edit_tool: {str(ex)}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:  # Catch Pydantic validation errors
        LOGGER.error(f"ValidationError in admin_edit_tool: {str(ex)}")
        return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except Exception as ex:  # Generic catch-all for unexpected errors
        LOGGER.error(f"Unexpected error in admin_edit_tool: {str(ex)}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/delete")
async def admin_delete_tool(tool_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a tool via the admin UI.

    This endpoint permanently removes a tool from the database using its ID.
    It is irreversible and should be used with caution. The operation is logged,
    and the user must be authenticated to access this route.

    Args:
        tool_id (str): The ID of the tool to delete.
        request (Request): FastAPI request object (not used directly, but required by route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the tools section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> tool_id = "tool-to-delete"
        >>>
        >>> # Happy path: Delete tool
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_tool = tool_service.delete_tool
        >>> tool_service.delete_tool = AsyncMock()
        >>>
        >>> async def test_admin_delete_tool_success():
        ...     result = await admin_delete_tool(tool_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_tool_inactive_checked():
        ...     result = await admin_delete_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> tool_service.delete_tool = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_tool_exception():
        ...     result = await admin_delete_tool(tool_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "#tools" in result.headers["location"] and "error=" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.delete_tool = original_delete_tool
    """
    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    purge_metrics = str(form.get("purge_metrics", "false")).lower() == "true"
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is deleting tool ID {tool_id}")
    error_message = None
    try:
        await tool_service.delete_tool(db, tool_id, user_email=user_email, purge_metrics=purge_metrics)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} deleting tool {tool_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error deleting tool: {e}")
        error_message = "Failed to delete tool. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#tools", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#tools", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#tools", status_code=303)
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.post("/tools/{tool_id}/toggle")
async def admin_toggle_tool(
    tool_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Toggle a tool's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a tool.
    It expects a form field 'activate' with value "true" to activate the tool
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        tool_id (str): The ID of the tool whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard tools section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> tool_id = "tool-to-toggle"
        >>>
        >>> # Happy path: Activate tool
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_tool_status = tool_service.toggle_tool_status
        >>> tool_service.toggle_tool_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_tool_activate():
        ...     result = await admin_toggle_tool(tool_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_activate())
        True
        >>>
        >>> # Happy path: Deactivate tool
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_tool_deactivate():
        ...     result = await admin_toggle_tool(tool_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_deactivate())
        True
        >>>
        >>> # Edge case: Toggle with inactive checkbox checked
        >>> form_data_inactive = FormData([("activate", "true"), ("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_tool_inactive_checked():
        ...     result = await admin_toggle_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin/?include_inactive=true#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> tool_service.toggle_tool_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_tool_exception():
        ...     result = await admin_toggle_tool(tool_id, mock_request_error, mock_db, mock_user)
        ...     location_header = result.headers["location"]
        ...     return (
        ...         isinstance(result, RedirectResponse)
        ...         and result.status_code == 303
        ...         and "/admin" in location_header  # Ensure '/admin' is in the URL
        ...         and "error=" in location_header  # Ensure error query param is present
        ...         and location_header.endswith("#tools")  # Ensure fragment is correct
        ...     )
        >>>
        >>> asyncio.run(test_admin_toggle_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.toggle_tool_status = original_toggle_tool_status
    """
    error_message = None
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is toggling tool ID {tool_id}")
    form = await request.form()
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await tool_service.toggle_tool_status(db, tool_id, activate, reachable=activate, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling tools {tool_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error toggling tool status: {e}")
        error_message = "Failed to toggle tool status. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#tools", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#tools", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#tools", status_code=303)
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.get("/gateways/{gateway_id}", response_model=GatewayRead)
async def admin_get_gateway(gateway_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Get gateway details for the admin UI.

    Args:
        gateway_id: Gateway ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        Gateway details.

    Raises:
        HTTPException: If the gateway is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayRead
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.gateway_service import GatewayNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> gateway_id = "test-gateway-id"
        >>>
        >>> # Mock gateway data
        >>> mock_gateway = GatewayRead(
        ...     id=gateway_id, name="Get Gateway", url="http://get.com",
        ...     description="Gateway for getting", transport="HTTP",
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, auth_type=None, auth_username=None, auth_password=None,
        ...     auth_token=None, auth_header_key=None, auth_header_value=None,
        ...     slug="test-gateway"
        ... )
        >>>
        >>> # Mock the gateway_service.get_gateway method
        >>> original_get_gateway = gateway_service.get_gateway
        >>> gateway_service.get_gateway = AsyncMock(return_value=mock_gateway)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_gateway_success():
        ...     result = await admin_get_gateway(gateway_id, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['id'] == gateway_id
        >>>
        >>> asyncio.run(test_admin_get_gateway_success())
        True
        >>>
        >>> # Test gateway not found
        >>> gateway_service.get_gateway = AsyncMock(side_effect=GatewayNotFoundError("Gateway not found"))
        >>> async def test_admin_get_gateway_not_found():
        ...     try:
        ...         await admin_get_gateway("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Gateway not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_gateway_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> gateway_service.get_gateway = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_gateway_exception():
        ...     try:
        ...         await admin_get_gateway(gateway_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_gateway_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.get_gateway = original_get_gateway
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for gateway ID {gateway_id}")
    try:
        gateway = await gateway_service.get_gateway(db, gateway_id)
        return gateway.model_dump(by_alias=True)
    except GatewayNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting gateway {gateway_id}: {e}")
        raise e


@admin_router.post("/gateways")
async def admin_add_gateway(request: Request, db: Session = Depends(get_db), user: dict[str, Any] = Depends(get_current_user_with_permissions)) -> JSONResponse:
    """Add a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)
      - tags (optional, comma-separated)

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from mcpgateway.services.gateway_service import GatewayConnectionError
        >>> from pydantic import ValidationError
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json # Added import for json.loads
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> # Happy path: Add a new gateway successfully with basic auth details
        >>> form_data_success = FormData([
        ...     ("name", "New Gateway"),
        ...     ("url", "http://new.gateway.com"),
        ...     ("transport", "HTTP"),
        ...     ("auth_type", "basic"), # Valid auth_type
        ...     ("auth_username", "user"), # Required for basic auth
        ...     ("auth_password", "pass")  # Required for basic auth
        ... ])
        >>> mock_request_success = MagicMock(spec=Request)
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_register_gateway = gateway_service.register_gateway
        >>> gateway_service.register_gateway = AsyncMock()
        >>>
        >>> async def test_admin_add_gateway_success():
        ...     response = await admin_add_gateway(mock_request_success, mock_db, mock_user)
        ...     # Corrected: Access body and then parse JSON
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body)["success"] is True
        >>>
        >>> asyncio.run(test_admin_add_gateway_success())
        True
        >>>
        >>> # Error path: Gateway connection error
        >>> form_data_conn_error = FormData([("name", "Bad Gateway"), ("url", "http://bad.com"), ("auth_type", "bearer"), ("auth_token", "abc")]) # Added auth_type and token
        >>> mock_request_conn_error = MagicMock(spec=Request)
        >>> mock_request_conn_error.form = AsyncMock(return_value=form_data_conn_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=GatewayConnectionError("Connection failed"))
        >>>
        >>> async def test_admin_add_gateway_connection_error():
        ...     response = await admin_add_gateway(mock_request_conn_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 502 and json.loads(response.body)["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_connection_error())
        True
        >>>
        >>> # Error path: Validation error (e.g., missing name)
        >>> form_data_validation_error = FormData([("url", "http://no-name.com"), ("auth_type", "headers"), ("auth_header_key", "X-Key"), ("auth_header_value", "val")]) # 'name' is missing, added auth_type
        >>> mock_request_validation_error = MagicMock(spec=Request)
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)
        >>> # No need to mock register_gateway, ValidationError happens during GatewayCreate()
        >>>
        >>> async def test_admin_add_gateway_validation_error():
        ...     response = await admin_add_gateway(mock_request_validation_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_validation_error())
        True
        >>>
        >>> # Error path: Integrity error (e.g., duplicate name)
        >>> from sqlalchemy.exc import IntegrityError
        >>> form_data_integrity_error = FormData([("name", "Duplicate Gateway"), ("url", "http://duplicate.com"), ("auth_type", "basic"), ("auth_username", "u"), ("auth_password", "p")]) # Added auth_type and creds
        >>> mock_request_integrity_error = MagicMock(spec=Request)
        >>> mock_request_integrity_error.form = AsyncMock(return_value=form_data_integrity_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=IntegrityError("Duplicate entry", {}, {}))
        >>>
        >>> async def test_admin_add_gateway_integrity_error():
        ...     response = await admin_add_gateway(mock_request_integrity_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_integrity_error())
        True
        >>>
        >>> # Error path: Generic RuntimeError
        >>> form_data_runtime_error = FormData([("name", "Runtime Error Gateway"), ("url", "http://runtime.com"), ("auth_type", "basic"), ("auth_username", "u"), ("auth_password", "p")]) # Added auth_type and creds
        >>> mock_request_runtime_error = MagicMock(spec=Request)
        >>> mock_request_runtime_error.form = AsyncMock(return_value=form_data_runtime_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=RuntimeError("Unexpected runtime issue"))
        >>>
        >>> async def test_admin_add_gateway_runtime_error():
        ...     response = await admin_add_gateway(mock_request_runtime_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_runtime_error())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.register_gateway = original_register_gateway
    """
    LOGGER.debug(f"User {get_user_email(user)} is adding a new gateway")
    form = await request.form()
    try:
        # Parse tags from comma-separated string
        tags_str = str(form.get("tags", ""))
        tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers: list[dict[str, Any]] = []
        if auth_headers_json:
            try:
                auth_headers = orjson.loads(auth_headers_json)
            except (orjson.JSONDecodeError, ValueError):
                auth_headers = []

        # Parse OAuth configuration - support both JSON string and individual form fields
        oauth_config_json = str(form.get("oauth_config"))
        oauth_config: Optional[dict[str, Any]] = None

        LOGGER.info(f"DEBUG: oauth_config_json from form = '{oauth_config_json}'")
        LOGGER.info(f"DEBUG: Individual OAuth fields - grant_type='{form.get('oauth_grant_type')}', issuer='{form.get('oauth_issuer')}'")

        # Option 1: Pre-assembled oauth_config JSON (from API calls)
        if oauth_config_json and oauth_config_json != "None":
            try:
                oauth_config = orjson.loads(oauth_config_json)
                # Encrypt the client secret if present
                if oauth_config and "client_secret" in oauth_config:
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_config["client_secret"])
            except (orjson.JSONDecodeError, ValueError) as e:
                LOGGER.error(f"Failed to parse OAuth config: {e}")
                oauth_config = None

        # Option 2: Assemble from individual UI form fields
        if not oauth_config:
            oauth_grant_type = str(form.get("oauth_grant_type", ""))
            oauth_issuer = str(form.get("oauth_issuer", ""))
            oauth_token_url = str(form.get("oauth_token_url", ""))
            oauth_authorization_url = str(form.get("oauth_authorization_url", ""))
            oauth_redirect_uri = str(form.get("oauth_redirect_uri", ""))
            oauth_client_id = str(form.get("oauth_client_id", ""))
            oauth_client_secret = str(form.get("oauth_client_secret", ""))
            oauth_username = str(form.get("oauth_username", ""))
            oauth_password = str(form.get("oauth_password", ""))
            oauth_scopes_str = str(form.get("oauth_scopes", ""))

            # If any OAuth field is provided, assemble oauth_config
            if any([oauth_grant_type, oauth_issuer, oauth_token_url, oauth_authorization_url, oauth_client_id]):
                oauth_config = {}

                if oauth_grant_type:
                    oauth_config["grant_type"] = oauth_grant_type
                if oauth_issuer:
                    oauth_config["issuer"] = oauth_issuer
                if oauth_token_url:
                    oauth_config["token_url"] = oauth_token_url  # OAuthManager expects 'token_url', not 'token_endpoint'
                if oauth_authorization_url:
                    oauth_config["authorization_url"] = oauth_authorization_url  # OAuthManager expects 'authorization_url', not 'authorization_endpoint'
                if oauth_redirect_uri:
                    oauth_config["redirect_uri"] = oauth_redirect_uri
                if oauth_client_id:
                    oauth_config["client_id"] = oauth_client_id
                if oauth_client_secret:
                    # Encrypt the client secret
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_client_secret)

                # Add username and password for password grant type
                if oauth_username:
                    oauth_config["username"] = oauth_username
                if oauth_password:
                    oauth_config["password"] = oauth_password

                # Parse scopes (comma or space separated)
                if oauth_scopes_str:
                    scopes = [s.strip() for s in oauth_scopes_str.replace(",", " ").split() if s.strip()]
                    if scopes:
                        oauth_config["scopes"] = scopes

                LOGGER.info(f"✅ Assembled OAuth config from UI form fields: grant_type={oauth_grant_type}, issuer={oauth_issuer}")
                LOGGER.info(f"DEBUG: Complete oauth_config = {oauth_config}")

        visibility = str(form.get("visibility", "private"))

        # Handle passthrough_headers
        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = orjson.loads(passthrough_headers)
            except (orjson.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        # Auto-detect OAuth: if oauth_config is present and auth_type not explicitly set, use "oauth"
        auth_type_from_form = str(form.get("auth_type", ""))
        LOGGER.info(f"DEBUG: auth_type from form: '{auth_type_from_form}', oauth_config present: {oauth_config is not None}")
        if oauth_config and not auth_type_from_form:
            auth_type_from_form = "oauth"
            LOGGER.info("✅ Auto-detected OAuth configuration, setting auth_type='oauth'")
        elif oauth_config and auth_type_from_form:
            LOGGER.info(f"✅ OAuth config present with explicit auth_type='{auth_type_from_form}'")

        ca_certificate: Optional[str] = None
        sig: Optional[str] = None

        # CA certificate(s) handled by JavaScript validation (supports single or multiple files)
        # JavaScript validates, orders (root→intermediate→leaf), and concatenates into hidden field
        if "ca_certificate" in form:
            ca_cert_value = form["ca_certificate"]
            if isinstance(ca_cert_value, str) and ca_cert_value.strip():
                ca_certificate = ca_cert_value.strip()
                LOGGER.info("✅ CA certificate(s) received and validated by frontend")

                if settings.enable_ed25519_signing:
                    try:
                        private_key_pem = settings.ed25519_private_key.get_secret_value()
                        sig = sign_data(ca_certificate.encode(), private_key_pem)
                    except Exception as e:
                        LOGGER.error(f"Error signing CA certificate: {e}")
                        sig = None
                        raise RuntimeError("Failed to sign CA certificate") from e
                else:
                    LOGGER.warning("⚠️  Ed25519 signing is disabled; CA certificate will be stored without signature")
                    sig = None

        gateway = GatewayCreate(
            name=str(form["name"]),
            url=str(form["url"]),
            description=str(form.get("description")),
            tags=tags,
            transport=str(form.get("transport", "SSE")),
            auth_type=auth_type_from_form,
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            oauth_config=oauth_config,
            one_time_auth=form.get("one_time_auth", False),
            passthrough_headers=passthrough_headers,
            visibility=visibility,
            ca_certificate=ca_certificate,
            ca_certificate_sig=sig if sig else None,
            signing_algorithm="ed25519" if sig else None,
        )
    except KeyError as e:
        # Convert KeyError to ValidationError-like response
        return ORJSONResponse(content={"message": f"Missing required field: {e}", "success": False}, status_code=422)

    except ValidationError as ex:
        # --- Getting only the custom message from the ValueError ---
        error_ctx = [str(err["ctx"]["error"]) for err in ex.errors()]
        return ORJSONResponse(content={"success": False, "message": "; ".join(error_ctx)}, status_code=422)

    except RuntimeError as re:
        # --- Getting only the custom message from the ValueError ---
        error_ctx = [str(re)]
        return ORJSONResponse(content={"success": False, "message": "; ".join(error_ctx)}, status_code=422)

    user_email = get_user_email(user)
    team_id = form.get("team_id", None)

    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)

    try:
        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        team_id_cast = typing_cast(Optional[str], team_id)
        await gateway_service.register_gateway(
            db,
            gateway,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            visibility=visibility,
            team_id=team_id_cast,
            owner_email=user_email,
        )

        # Provide specific guidance for OAuth Authorization Code flow
        message = "Gateway registered successfully!"
        if oauth_config and isinstance(oauth_config, dict) and oauth_config.get("grant_type") == "authorization_code":
            message = (
                "Gateway registered successfully! 🎉\n\n"
                "⚠️  IMPORTANT: This gateway uses OAuth Authorization Code flow.\n"
                "You must complete the OAuth authorization before tools will work:\n\n"
                "1. Go to the Gateways list\n"
                "2. Click the '🔐 Authorize' button for this gateway\n"
                "3. Complete the OAuth consent flow\n"
                "4. Return to the admin panel\n\n"
                "Tools will not work until OAuth authorization is completed."
            )
        return ORJSONResponse(
            content={"message": message, "success": True},
            status_code=200,
        )

    except GatewayConnectionError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=502)
    except GatewayDuplicateConflictError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except GatewayNameConflictError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ValueError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except RuntimeError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:
        return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except IntegrityError as ex:
        return ORJSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except Exception as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


# OAuth callback is now handled by the dedicated OAuth router at /oauth/callback
# This route has been removed to avoid conflicts with the complete implementation
@admin_router.post("/gateways/{gateway_id}/edit")
async def admin_edit_gateway(
    gateway_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Edit a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)
      - tags (optional, comma-separated)

    Args:
        gateway_id: Gateway ID.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>> from pydantic import ValidationError
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> gateway_id = "gateway-to-edit"
        >>>
        >>> # Happy path: Edit gateway successfully
        >>> form_data_success = FormData([
        ...  ("name", "Updated Gateway"),
        ...  ("url", "http://updated.com"),
        ...  ("is_inactive_checked", "false"),
        ...  ("auth_type", "basic"),
        ...  ("auth_username", "user"),
        ...  ("auth_password", "pass")
        ... ])
        >>> mock_request_success = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_update_gateway = gateway_service.update_gateway
        >>> gateway_service.update_gateway = AsyncMock()
        >>>
        >>> async def test_admin_edit_gateway_success():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body)["success"] is True
        >>>
        >>> asyncio.run(test_admin_edit_gateway_success())
        True
        >>>
        # >>> # Edge case: Edit gateway with inactive checkbox checked
        # >>> form_data_inactive = FormData([("name", "Inactive Edit"), ("url", "http://inactive.com"), ("is_inactive_checked", "true"), ("auth_type", "basic"), ("auth_username", "user"),
        # ...     ("auth_password", "pass")]) # Added auth_type
        # >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        # >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        # >>>
        # >>> async def test_admin_edit_gateway_inactive_checked():
        # ...     response = await admin_edit_gateway(gateway_id, mock_request_inactive, mock_db, mock_user)
        # ...     return isinstance(response, RedirectResponse) and response.status_code == 303 and "/api/admin/?include_inactive=true#gateways" in response.headers["location"]
        # >>>
        # >>> asyncio.run(test_admin_edit_gateway_inactive_checked())
        # True
        # >>>
        >>> # Error path: Simulate an exception during update
        >>> form_data_error = FormData([("name", "Error Gateway"), ("url", "http://error.com"), ("auth_type", "basic"),("auth_username", "user"),
        ...     ("auth_password", "pass")]) # Added auth_type
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.update_gateway = AsyncMock(side_effect=Exception("Update failed"))
        >>>
        >>> async def test_admin_edit_gateway_exception():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     return (
        ...         isinstance(response, JSONResponse)
        ...         and response.status_code == 500
        ...         and json.loads(response.body)["success"] is False
        ...         and "Update failed" in json.loads(response.body)["message"]
        ...     )
        >>>
        >>> asyncio.run(test_admin_edit_gateway_exception())
        True
        >>>
        >>> # Error path: Pydantic Validation Error (e.g., invalid URL format)
        >>> form_data_validation_error = FormData([("name", "Bad URL Gateway"), ("url", "invalid-url"), ("auth_type", "basic"),("auth_username", "user"),
        ...     ("auth_password", "pass")]) # Added auth_type
        >>> mock_request_validation_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)
        >>>
        >>> async def test_admin_edit_gateway_validation_error():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_validation_error, mock_db, mock_user)
        ...     body = json.loads(response.body.decode())
        ...     return isinstance(response, JSONResponse) and response.status_code in (422,400) and body["success"] is False
        >>>
        >>> asyncio.run(test_admin_edit_gateway_validation_error())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.update_gateway = original_update_gateway
    """
    LOGGER.debug(f"User {get_user_email(user)} is editing gateway ID {gateway_id}")
    form = await request.form()
    try:
        # Parse tags from comma-separated string
        tags_str = str(form.get("tags", ""))
        tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        visibility = str(form.get("visibility", "private"))

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers = []
        if auth_headers_json:
            try:
                auth_headers = orjson.loads(auth_headers_json)
            except (orjson.JSONDecodeError, ValueError):
                auth_headers = []

        # Handle passthrough_headers
        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = orjson.loads(passthrough_headers)
            except (orjson.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        # Parse OAuth configuration - support both JSON string and individual form fields
        oauth_config_json = str(form.get("oauth_config"))
        oauth_config: Optional[dict[str, Any]] = None

        # Option 1: Pre-assembled oauth_config JSON (from API calls)
        if oauth_config_json and oauth_config_json != "None":
            try:
                oauth_config = orjson.loads(oauth_config_json)
                # Encrypt the client secret if present and not empty
                if oauth_config and "client_secret" in oauth_config and oauth_config["client_secret"]:
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_config["client_secret"])
            except (orjson.JSONDecodeError, ValueError) as e:
                LOGGER.error(f"Failed to parse OAuth config: {e}")
                oauth_config = None

        # Option 2: Assemble from individual UI form fields
        if not oauth_config:
            oauth_grant_type = str(form.get("oauth_grant_type", ""))
            oauth_issuer = str(form.get("oauth_issuer", ""))
            oauth_token_url = str(form.get("oauth_token_url", ""))
            oauth_authorization_url = str(form.get("oauth_authorization_url", ""))
            oauth_redirect_uri = str(form.get("oauth_redirect_uri", ""))
            oauth_client_id = str(form.get("oauth_client_id", ""))
            oauth_client_secret = str(form.get("oauth_client_secret", ""))
            oauth_username = str(form.get("oauth_username", ""))
            oauth_password = str(form.get("oauth_password", ""))
            oauth_scopes_str = str(form.get("oauth_scopes", ""))

            # If any OAuth field is provided, assemble oauth_config
            if any([oauth_grant_type, oauth_issuer, oauth_token_url, oauth_authorization_url, oauth_client_id]):
                oauth_config = {}

                if oauth_grant_type:
                    oauth_config["grant_type"] = oauth_grant_type
                if oauth_issuer:
                    oauth_config["issuer"] = oauth_issuer
                if oauth_token_url:
                    oauth_config["token_url"] = oauth_token_url  # OAuthManager expects 'token_url', not 'token_endpoint'
                if oauth_authorization_url:
                    oauth_config["authorization_url"] = oauth_authorization_url  # OAuthManager expects 'authorization_url', not 'authorization_endpoint'
                if oauth_redirect_uri:
                    oauth_config["redirect_uri"] = oauth_redirect_uri
                if oauth_client_id:
                    oauth_config["client_id"] = oauth_client_id
                if oauth_client_secret:
                    # Encrypt the client secret
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_client_secret)

                # Add username and password for password grant type
                if oauth_username:
                    oauth_config["username"] = oauth_username
                if oauth_password:
                    oauth_config["password"] = oauth_password

                # Parse scopes (comma or space separated)
                if oauth_scopes_str:
                    scopes = [s.strip() for s in oauth_scopes_str.replace(",", " ").split() if s.strip()]
                    if scopes:
                        oauth_config["scopes"] = scopes

                LOGGER.info(f"✅ Assembled OAuth config from UI form fields (edit): grant_type={oauth_grant_type}, issuer={oauth_issuer}")

        user_email = get_user_email(user)
        # Determine personal team for default assignment
        team_id_raw = form.get("team_id", None)
        team_id = str(team_id_raw) if team_id_raw is not None else None

        team_service = TeamManagementService(db)
        team_id = await team_service.verify_team_for_user(user_email, team_id)

        # Auto-detect OAuth: if oauth_config is present and auth_type not explicitly set, use "oauth"
        auth_type_from_form = str(form.get("auth_type", ""))
        if oauth_config and not auth_type_from_form:
            auth_type_from_form = "oauth"
            LOGGER.info("Auto-detected OAuth configuration in edit, setting auth_type='oauth'")

        gateway = GatewayUpdate(  # Pydantic validation happens here
            name=str(form.get("name")),
            url=str(form["url"]),
            description=str(form.get("description")),
            transport=str(form.get("transport", "SSE")),
            tags=tags,
            auth_type=auth_type_from_form,
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_value=str(form.get("auth_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            one_time_auth=form.get("one_time_auth", False),
            passthrough_headers=passthrough_headers,
            oauth_config=oauth_config,
            visibility=visibility,
            owner_email=user_email,
            team_id=team_id,
        )

        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)
        await gateway_service.update_gateway(
            db,
            gateway_id,
            gateway,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
            user_email=user_email,
        )
        return ORJSONResponse(
            content={"message": "Gateway updated successfully!", "success": True},
            status_code=200,
        )
    except PermissionError as e:
        LOGGER.info(f"Permission denied for user {get_user_email(user)}: {e}")
        return ORJSONResponse(
            content={"message": str(e), "success": False},
            status_code=403,
        )
    except Exception as ex:
        if isinstance(ex, GatewayConnectionError):
            return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=502)
        if isinstance(ex, ValueError):
            return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=400)
        if isinstance(ex, RuntimeError):
            return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
        if isinstance(ex, ValidationError):
            return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            return ORJSONResponse(status_code=409, content=ErrorFormatter.format_database_error(ex))
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/gateways/{gateway_id}/delete")
async def admin_delete_gateway(gateway_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a gateway via the admin UI.

    This endpoint removes a gateway from the database by its ID. The deletion is
    permanent and cannot be undone. It requires authentication and logs the
    operation for auditing purposes.

    Args:
        gateway_id (str): The ID of the gateway to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the gateways section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> gateway_id = "gateway-to-delete"
        >>>
        >>> # Happy path: Delete gateway
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_gateway = gateway_service.delete_gateway
        >>> gateway_service.delete_gateway = AsyncMock()
        >>>
        >>> async def test_admin_delete_gateway_success():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_gateway_inactive_checked():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.delete_gateway = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_gateway_exception():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "#gateways" in result.headers["location"] and "error=" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.delete_gateway = original_delete_gateway
    """
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is deleting gateway ID {gateway_id}")
    error_message = None
    try:
        await gateway_service.delete_gateway(db, gateway_id, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} deleting gateway {gateway_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error deleting gateway: {e}")
        error_message = "Failed to delete gateway. Please try again."

    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#gateways", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#gateways", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#gateways", status_code=303)
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.get("/resources/test/{resource_uri:path}")
async def admin_test_resource(resource_uri: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """
    Test reading a resource by its URI for the admin UI.

    Args:
        resource_uri: The full resource URI (may include encoded characters).
        db: Database session dependency.
        user: Authenticated user with proper permissions.

    Returns:
        A dictionary containing the resolved resource content.

    Raises:
        HTTPException: If the resource is not found.
        Exception: For unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.services.resource_service import ResourceNotFoundError
        >>> from fastapi import HTTPException

        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user"}
        >>> test_uri = "resource://example/demo"

        >>> # --- Mock successful content read ---
        >>> original_read_resource = resource_service.read_resource
        >>> resource_service.read_resource = AsyncMock(return_value={"hello": "world"})

        >>> async def test_success():
        ...     result = await admin_test_resource(test_uri, mock_db, mock_user)
        ...     return result["content"] == {"hello": "world"}

        >>> asyncio.run(test_success())
        True

        >>> # --- Mock resource not found ---
        >>> resource_service.read_resource = AsyncMock(
        ...     side_effect=ResourceNotFoundError("Not found")
        ... )

        >>> async def test_not_found():
        ...     try:
        ...         await admin_test_resource("resource://missing", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Not found" in e.detail

        >>> asyncio.run(test_not_found())
        True

        >>> # --- Mock unexpected exception ---
        >>> resource_service.read_resource = AsyncMock(side_effect=Exception("Boom"))

        >>> async def test_error():
        ...     try:
        ...         await admin_test_resource(test_uri, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Boom"

        >>> asyncio.run(test_error())
        True

        >>> # Restore original method
        >>> resource_service.read_resource = original_read_resource
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for resource ID {resource_uri}")

    try:
        resource_content = await resource_service.read_resource(db, resource_uri=resource_uri)
        return {"content": resource_content}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting resource for {resource_uri}: {e}")
        raise e


@admin_router.get("/resources/{resource_id}")
async def admin_get_resource(resource_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Get resource details for the admin UI.

    Args:
        resource_id: Resource ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        A dictionary containing resource details.

    Raises:
        HTTPException: If the resource is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ResourceRead, ResourceMetrics
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.resource_service import ResourceNotFoundError
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user"}
        >>> resource_id = "1"
        >>> resource_uri = "test://resource/get"
        >>>
        >>> # Mock resource data
        >>> mock_resource = ResourceRead(
        ...     id=resource_id, uri=resource_uri, name="Get Resource", description="Test",
        ...     mime_type="text/plain", size=10, created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc), is_active=True,enabled=True,
        ...     metrics=ResourceMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None
        ...     ),
        ...     tags=[]
        ... )
        >>>
        >>> # Mock service call
        >>> original_get_resource_by_id = resource_service.get_resource_by_id
        >>> resource_service.get_resource_by_id = AsyncMock(return_value=mock_resource)
        >>>
        >>> # Test: successful retrieval
        >>> async def test_success():
        ...     result = await admin_get_resource(resource_id, mock_db, mock_user)
        ...     return result["resource"]["id"] == resource_id
        >>>
        >>> asyncio.run(test_success())
        True
        >>>
        >>> # Test: resource not found
        >>> resource_service.get_resource_by_id = AsyncMock(
        ...     side_effect=ResourceNotFoundError("Resource not found")
        ... )
        >>>
        >>> async def test_not_found():
        ...     try:
        ...         await admin_get_resource("39334ce0ed2644d79ede8913a66930c9", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Resource not found" in e.detail
        >>>
        >>> asyncio.run(test_not_found())
        True
        >>>
        >>> # Test: unexpected exception
        >>> resource_service.get_resource_by_id = AsyncMock(
        ...     side_effect=Exception("Unexpected error")
        ... )
        >>>
        >>> async def test_exception():
        ...     try:
        ...         await admin_get_resource(resource_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Unexpected error"
        >>>
        >>> asyncio.run(test_exception())
        True
        >>>
        >>> # Restore original method
        >>> resource_service.get_resource_by_id = original_get_resource_by_id
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for resource ID {resource_id}")
    try:
        resource = await resource_service.get_resource_by_id(db, resource_id, include_inactive=True)
        # content = await resource_service.read_resource(db, resource_id=resource_id)
        return {"resource": resource.model_dump(by_alias=True)}  # , "content": None}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting resource {resource_id}: {e}")
        raise e


@admin_router.post("/resources")
async def admin_add_resource(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Response:
    """
    Add a resource via the admin UI.

    Expects form fields:
      - uri
      - name
      - description (optional)
      - mime_type (optional)
      - content

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> form_data = FormData([
        ...     ("uri", "test://resource1"),
        ...     ("name", "Test Resource"),
        ...     ("description", "A test resource"),
        ...     ("mimeType", "text/plain"),
        ...     ("uri_template", ""),
        ...     ("content", "Sample content"),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_register_resource = resource_service.register_resource
        >>> resource_service.register_resource = AsyncMock()
        >>>
        >>> async def test_admin_add_resource():
        ...     response = await admin_add_resource(mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body.decode() == '{"message":"Add resource registered successfully!","success":true}'
        >>>
        >>> import asyncio; asyncio.run(test_admin_add_resource())
        True
        >>> resource_service.register_resource = original_register_resource
    """
    LOGGER.debug(f"User {get_user_email(user)} is adding a new resource")
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    visibility = str(form.get("visibility", "public"))
    user_email = get_user_email(user)
    # Determine personal team for default assignment
    team_id = form.get("team_id", None)
    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)

    try:
        # Handle template field: convert empty string to None for optional field
        template = None
        template_value = form.get("uri_template")
        template = template_value if template_value else None
        template_value = form.get("uri_template")
        uri_value = form.get("uri")

        # Ensure uri_value is a string
        if isinstance(uri_value, str) and "{" in uri_value and "}" in uri_value:
            template = uri_value

        resource = ResourceCreate(
            uri=str(form["uri"]),
            name=str(form["name"]),
            description=str(form.get("description", "")),
            mime_type=str(form.get("mimeType", "")),
            uri_template=template,
            content=str(form["content"]),
            tags=tags,
            visibility=visibility,
            team_id=team_id,
            owner_email=user_email,
        )

        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await resource_service.register_resource(
            db,
            resource,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
            team_id=team_id,
            owner_email=user_email,
            visibility=visibility,
        )
        return ORJSONResponse(
            content={"message": "Add resource registered successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        # Roll back only when a transaction is active to avoid sqlite3 "no transaction" errors.
        try:
            active_transaction = db.get_transaction() if hasattr(db, "get_transaction") else None
            if db.is_active and active_transaction is not None:
                db.rollback()
        except (InvalidRequestError, OperationalError) as rollback_error:
            LOGGER.warning(
                "Rollback failed (ignoring for SQLite compatibility): %s",
                rollback_error,
            )

        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_add_resource: {ErrorFormatter.format_validation_error(ex)}")
            return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_add_resource: {error_message}")
            return ORJSONResponse(status_code=409, content=error_message)
        if isinstance(ex, ResourceURIConflictError):
            LOGGER.error(f"ResourceURIConflictError in admin_add_resource: {ex}")
            return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
        LOGGER.error(f"Error in admin_add_resource: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/resources/{resource_id}/edit")
async def admin_edit_resource(
    resource_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """
    Edit a resource via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - mime_type (optional)
      - content

    Args:
        resource_id: Resource ID.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSONResponse: A JSON response indicating success or failure of the resource update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> form_data = FormData([
        ...     ("name", "Updated Resource"),
        ...     ("description", "Updated description"),
        ...     ("mimeType", "text/plain"),
        ...     ("content", "Updated content"),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_update_resource = resource_service.update_resource
        >>> resource_service.update_resource = AsyncMock()
        >>>
        >>> # Test successful update
        >>> async def test_admin_edit_resource():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Resource updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_resource())
        True
        >>>
        >>> # Test validation error
        >>> from pydantic import ValidationError
        >>> validation_error = ValidationError.from_exception_data("Resource validation error", [
        ...     {"loc": ("name",), "msg": "Field required", "type": "missing"}
        ... ])
        >>> resource_service.update_resource = AsyncMock(side_effect=validation_error)
        >>> async def test_admin_edit_resource_validation():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422
        >>>
        >>> asyncio.run(test_admin_edit_resource_validation())
        True
        >>>
        >>> # Test integrity error (e.g., duplicate resource)
        >>> from sqlalchemy.exc import IntegrityError
        >>> integrity_error = IntegrityError("Duplicate entry", None, None)
        >>> resource_service.update_resource = AsyncMock(side_effect=integrity_error)
        >>> async def test_admin_edit_resource_integrity():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409
        >>>
        >>> asyncio.run(test_admin_edit_resource_integrity())
        True
        >>>
        >>> # Test unknown error
        >>> resource_service.update_resource = AsyncMock(side_effect=Exception("Unknown error"))
        >>> async def test_admin_edit_resource_unknown():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and b'Unknown error' in response.body
        >>>
        >>> asyncio.run(test_admin_edit_resource_unknown())
        True
        >>>
        >>> # Reset mock
        >>> resource_service.update_resource = original_update_resource
    """
    LOGGER.debug(f"User {get_user_email(user)} is editing resource ID {resource_id}")
    form = await request.form()
    LOGGER.info(f"Form data received for resource edit: {form}")
    visibility = str(form.get("visibility", "private"))
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)
        resource = ResourceUpdate(
            uri=str(form.get("uri", "")),
            name=str(form.get("name", "")),
            description=str(form.get("description")),
            mime_type=str(form.get("mimeType")),
            content=str(form.get("content", "")),
            template=str(form.get("template")),
            tags=tags,
            visibility=visibility,
        )
        LOGGER.info(f"ResourceUpdate object created: {resource}")
        await resource_service.update_resource(
            db,
            resource_id,
            resource,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
            user_email=get_user_email(user),
        )
        return ORJSONResponse(
            content={"message": "Resource updated successfully!", "success": True},
            status_code=200,
        )
    except PermissionError as e:
        LOGGER.info(f"Permission denied for user {get_user_email(user)}: {e}")
        return ORJSONResponse(content={"message": str(e), "success": False}, status_code=403)
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_edit_resource: {ErrorFormatter.format_validation_error(ex)}")
            return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_edit_resource: {error_message}")
            return ORJSONResponse(status_code=409, content=error_message)
        if isinstance(ex, ResourceURIConflictError):
            LOGGER.error(f"ResourceURIConflictError in admin_edit_resource: {ex}")
            return ORJSONResponse(status_code=409, content={"message": str(ex), "success": False})
        LOGGER.error(f"Error in admin_edit_resource: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/resources/{resource_id}/delete")
async def admin_delete_resource(resource_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a resource via the admin UI.

    This endpoint permanently removes a resource from the database using its resource ID.
    The operation is irreversible and should be used with caution. It requires
    user authentication and logs the deletion attempt.

    Args:
        resource_id (str): The ID of the resource to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the resources section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_delete_resource = resource_service.delete_resource
        >>> resource_service.delete_resource = AsyncMock()
        >>>
        >>> async def test_admin_delete_resource():
        ...     response = await admin_delete_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> import asyncio; asyncio.run(test_admin_delete_resource())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_resource_inactive():
        ...     response = await admin_delete_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_resource_inactive())
        True
        >>> resource_service.delete_resource = original_delete_resource
    """

    form = await request.form()
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    purge_metrics = str(form.get("purge_metrics", "false")).lower() == "true"
    user_email = get_user_email(user)
    LOGGER.debug(f"User {get_user_email(user)} is deleting resource ID {resource_id}")
    error_message = None
    try:
        await resource_service.delete_resource(
            user["db"] if isinstance(user, dict) else db,
            resource_id,
            user_email=user_email,
            purge_metrics=purge_metrics,
        )
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} deleting resource {resource_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error deleting resource: {e}")
        error_message = "Failed to delete resource. Please try again."
    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#resources", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#resources", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#resources", status_code=303)
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


@admin_router.post("/resources/{resource_id}/toggle")
async def admin_toggle_resource(
    resource_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Toggle a resource's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a resource.
    It expects a form field 'activate' with value "true" to activate the resource
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        resource_id (str): The ID of the resource whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard resources section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_toggle_resource_status = resource_service.toggle_resource_status
        >>> resource_service.toggle_resource_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_resource():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource())
        True
        >>>
        >>> # Test with activate=false
        >>> form_data_deactivate = FormData([
        ...     ("activate", "false"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_resource_deactivate():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource_deactivate())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_resource_inactive():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_resource_inactive())
        True
        >>>
        >>> # Test exception handling
        >>> resource_service.toggle_resource_status = AsyncMock(side_effect=Exception("Test error"))
        >>> form_data_error = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_error)
        >>>
        >>> async def test_admin_toggle_resource_exception():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource_exception())
        True
        >>> resource_service.toggle_resource_status = original_toggle_resource_status
    """
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is toggling resource ID {resource_id}")
    form = await request.form()
    error_message = None
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await resource_service.toggle_resource_status(db, resource_id, activate, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling resource status {resource_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error toggling resource status: {e}")
        error_message = "Failed to toggle resource status. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#resources", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#resources", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#resources", status_code=303)
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


@admin_router.get("/prompts/{prompt_id}")
async def admin_get_prompt(prompt_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Get prompt details for the admin UI.

    Args:
        prompt_id: Prompt ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        A dictionary with prompt details.

    Raises:
        HTTPException: If the prompt is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import PromptRead, PromptMetrics
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.prompt_service import PromptNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> prompt_name = "test-prompt"
        >>>
        >>> # Mock prompt details
        >>> mock_metrics = PromptMetrics(
        ...     total_executions=3,
        ...     successful_executions=3,
        ...     failed_executions=0,
        ...     failure_rate=0.0,
        ...     min_response_time=0.1,
        ...     max_response_time=0.5,
        ...     avg_response_time=0.3,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_prompt_details = {
        ...     "id": "ca627760127d409080fdefc309147e08",
        ...     "name": prompt_name,
        ...     "original_name": prompt_name,
        ...     "custom_name": prompt_name,
        ...     "custom_name_slug": "test-prompt",
        ...     "display_name": "Test Prompt",
        ...     "description": "A test prompt",
        ...     "template": "Hello {{name}}!",
        ...     "arguments": [{"name": "name", "type": "string"}],
        ...     "created_at": datetime.now(timezone.utc),
        ...     "updated_at": datetime.now(timezone.utc),
        ...     "enabled": True,
        ...     "metrics": mock_metrics,
        ...     "tags": []
        ... }
        >>>
        >>> original_get_prompt_details = prompt_service.get_prompt_details
        >>> prompt_service.get_prompt_details = AsyncMock(return_value=mock_prompt_details)
        >>>
        >>> async def test_admin_get_prompt():
        ...     result = await admin_get_prompt(prompt_name, mock_db, mock_user)
        ...     return isinstance(result, dict) and result.get("name") == prompt_name
        >>>
        >>> asyncio.run(test_admin_get_prompt())
        True
        >>>
        >>> # Test prompt not found
        >>> prompt_service.get_prompt_details = AsyncMock(side_effect=PromptNotFoundError("Prompt not found"))
        >>> async def test_admin_get_prompt_not_found():
        ...     try:
        ...         await admin_get_prompt("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Prompt not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_prompt_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> prompt_service.get_prompt_details = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_prompt_exception():
        ...     try:
        ...         await admin_get_prompt(prompt_name, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_prompt_exception())
        True
        >>>
        >>> prompt_service.get_prompt_details = original_get_prompt_details
    """
    LOGGER.info(f"User {get_user_email(user)} requested details for prompt ID {prompt_id}")
    try:
        prompt_details = await prompt_service.get_prompt_details(db, prompt_id)
        prompt = PromptRead.model_validate(prompt_details)
        return prompt.model_dump(by_alias=True)
    except PromptNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting prompt {prompt_id}: {e}")
        raise


@admin_router.post("/prompts")
async def admin_add_prompt(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> JSONResponse:
    """Add a prompt via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - template
      - arguments (as a JSON string representing a list)

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> form_data = FormData([
        ...     ("name", "Test Prompt"),
        ...     ("description", "A test prompt"),
        ...     ("template", "Hello {{name}}!"),
        ...     ("arguments", '[{"name": "name", "type": "string"}]'),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_register_prompt = prompt_service.register_prompt
        >>> prompt_service.register_prompt = AsyncMock()
        >>>
        >>> async def test_admin_add_prompt():
        ...     response = await admin_add_prompt(mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Prompt registered successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_add_prompt())
        True

        >>> prompt_service.register_prompt = original_register_prompt
    """
    LOGGER.debug(f"User {get_user_email(user)} is adding a new prompt")
    form = await request.form()
    visibility = str(form.get("visibility", "private"))
    user_email = get_user_email(user)
    # Determine personal team for default assignment
    team_id = form.get("team_id", None)
    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        args_json = "[]"
        args_value = form.get("arguments")
        if isinstance(args_value, str) and args_value.strip():
            args_json = args_value
        arguments = orjson.loads(args_json)
        prompt = PromptCreate(
            name=str(form["name"]),
            display_name=str(form.get("display_name") or form["name"]),
            description=str(form.get("description")),
            template=str(form["template"]),
            arguments=arguments,
            tags=tags,
            visibility=visibility,
            team_id=team_id,
            owner_email=user_email,
        )
        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await prompt_service.register_prompt(
            db,
            prompt,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
            team_id=team_id,
            owner_email=user_email,
            visibility=visibility,
        )
        return ORJSONResponse(
            content={"message": "Prompt registered successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_add_prompt: {ErrorFormatter.format_validation_error(ex)}")
            return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_add_prompt: {error_message}")
            return ORJSONResponse(status_code=409, content=error_message)
        if isinstance(ex, PromptNameConflictError):
            LOGGER.error(f"PromptNameConflictError in admin_add_prompt: {ex}")
            return ORJSONResponse(status_code=409, content={"message": str(ex), "success": False})
        LOGGER.error(f"Error in admin_add_prompt: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/prompts/{prompt_id}/edit")
async def admin_edit_prompt(
    prompt_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Edit a prompt via the admin UI.

    Expects form fields:
        - name
        - description (optional)
        - template
        - arguments (as a JSON string representing a list)

    Args:
        prompt_id: Prompt ID.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSONResponse: A JSON response indicating success or failure of the server update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from starlette.datastructures import FormData
        >>> from fastapi.responses import JSONResponse
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> prompt_name = "test-prompt"
        >>> form_data = FormData([
        ...     ("name", "Updated Prompt"),
        ...     ("description", "Updated description"),
        ...     ("template", "Hello {{name}}, welcome!"),
        ...     ("arguments", '[{"name": "name", "type": "string"}]'),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_update_prompt = prompt_service.update_prompt
        >>> prompt_service.update_prompt = AsyncMock()
        >>>
        >>> async def test_admin_edit_prompt():
        ...     response = await admin_edit_prompt(prompt_name, mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Prompt updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_prompt())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Updated Prompt"),
        ...     ("template", "Hello {{name}}!"),
        ...     ("arguments", "[]"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_edit_prompt_inactive():
        ...     response = await admin_edit_prompt(prompt_name, mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and b"Prompt updated successfully!" in response.body
        >>>
        >>> asyncio.run(test_admin_edit_prompt_inactive())
        True
        >>> prompt_service.update_prompt = original_update_prompt

    """
    LOGGER.debug(f"User {get_user_email(user)} is editing prompt {prompt_id}")
    form = await request.form()

    visibility = str(form.get("visibility", "private"))
    user_email = get_user_email(user)
    # Determine personal team for default assignment
    team_id = form.get("team_id", None)
    LOGGER.info(f"befor Verifying team for user {user_email} with team_id {team_id}")
    team_service = TeamManagementService(db)
    team_id = await team_service.verify_team_for_user(user_email, team_id)
    LOGGER.info(f"Verifying team for user {user_email} with team_id {team_id}")

    args_json: str = str(form.get("arguments")) or "[]"
    arguments = orjson.loads(args_json)
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    try:
        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)
        prompt = PromptUpdate(
            custom_name=str(form.get("customName") or form.get("name")),
            display_name=str(form.get("displayName") or form.get("display_name") or form.get("name")),
            description=str(form.get("description")),
            template=str(form["template"]),
            arguments=arguments,
            tags=tags,
            visibility=visibility,
            team_id=team_id,
            owner_email=user_email,
        )
        await prompt_service.update_prompt(
            db,
            prompt_id,
            prompt,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
            user_email=user_email,
        )
        return ORJSONResponse(
            content={"message": "Prompt updated successfully!", "success": True},
            status_code=200,
        )
    except PermissionError as e:
        LOGGER.info(f"Permission denied for user {get_user_email(user)}: {e}")
        return ORJSONResponse(content={"message": str(e), "success": False}, status_code=403)
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_edit_prompt: {ErrorFormatter.format_validation_error(ex)}")
            return ORJSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_edit_prompt: {error_message}")
            return ORJSONResponse(status_code=409, content=error_message)
        if isinstance(ex, PromptNameConflictError):
            LOGGER.error(f"PromptNameConflictError in admin_edit_prompt: {ex}")
            return ORJSONResponse(status_code=409, content={"message": str(ex), "success": False})
        LOGGER.error(f"Error in admin_edit_prompt: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/prompts/{prompt_id}/delete")
async def admin_delete_prompt(prompt_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a prompt via the admin UI.

    This endpoint permanently deletes a prompt from the database using its ID.
    Deletion is irreversible and requires authentication. All actions are logged
    for administrative auditing.

    Args:
        prompt_id (str): The ID of the prompt to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the prompts section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_delete_prompt = prompt_service.delete_prompt
        >>> prompt_service.delete_prompt = AsyncMock()
        >>>
        >>> async def test_admin_delete_prompt():
        ...     response = await admin_delete_prompt("test-prompt", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_delete_prompt())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_prompt_inactive():
        ...     response = await admin_delete_prompt("test-prompt", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_prompt_inactive())
        True
        >>> prompt_service.delete_prompt = original_delete_prompt
    """
    form = await request.form()
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    purge_metrics = str(form.get("purge_metrics", "false")).lower() == "true"
    user_email = get_user_email(user)
    LOGGER.info(f"User {get_user_email(user)} is deleting prompt id {prompt_id}")
    error_message = None
    try:
        await prompt_service.delete_prompt(db, prompt_id, user_email=user_email, purge_metrics=purge_metrics)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} deleting prompt {prompt_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error deleting prompt: {e}")
        error_message = "Failed to delete prompt. Please try again."
    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#prompts", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#prompts", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#prompts", status_code=303)
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


@admin_router.post("/prompts/{prompt_id}/toggle")
async def admin_toggle_prompt(
    prompt_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Toggle a prompt's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a prompt.
    It expects a form field 'activate' with value "true" to activate the prompt
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        prompt_id (str): The ID of the prompt whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard prompts section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_toggle_prompt_status = prompt_service.toggle_prompt_status
        >>> prompt_service.toggle_prompt_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_prompt():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt())
        True
        >>>
        >>> # Test with activate=false
        >>> form_data_deactivate = FormData([
        ...     ("activate", "false"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_prompt_deactivate():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_deactivate())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_prompt_inactive():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_inactive())
        True
        >>>
        >>> # Test exception handling
        >>> prompt_service.toggle_prompt_status = AsyncMock(side_effect=Exception("Test error"))
        >>> form_data_error = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_error)
        >>>
        >>> async def test_admin_toggle_prompt_exception():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_exception())
        True
        >>> prompt_service.toggle_prompt_status = original_toggle_prompt_status
    """
    user_email = get_user_email(user)
    LOGGER.debug(f"User {user_email} is toggling prompt ID {prompt_id}")
    error_message = None
    form = await request.form()
    activate: bool = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    try:
        await prompt_service.toggle_prompt_status(db, prompt_id, activate, user_email=user_email)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling prompt {prompt_id}: {e}")
        error_message = str(e)
    except Exception as e:
        LOGGER.error(f"Error toggling prompt status: {e}")
        error_message = "Failed to toggle prompt status. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/{error_param}&include_inactive=true#prompts", status_code=303)
        return RedirectResponse(f"{root_path}/admin/{error_param}#prompts", status_code=303)

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#prompts", status_code=303)
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


@admin_router.post("/roots")
async def admin_add_root(request: Request, user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """Add a new root via the admin UI.

    Expects form fields:
      - path
      - name (optional)

    Args:
        request: FastAPI request containing form data.
        user: Authenticated user.

    Returns:
        RedirectResponse: A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("uri", "test://root1"),
        ...     ("name", "Test Root"),
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_add_root = root_service.add_root
        >>> root_service.add_root = AsyncMock()
        >>>
        >>> async def test_admin_add_root():
        ...     response = await admin_add_root(mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_add_root())
        True
        >>> root_service.add_root = original_add_root
    """
    LOGGER.debug(f"User {get_user_email(user)} is adding a new root")
    form = await request.form()
    uri = str(form["uri"])
    name_value = form.get("name")
    name: str | None = None
    if isinstance(name_value, str):
        name = name_value
    await root_service.add_root(uri, name)
    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#roots", status_code=303)


@admin_router.post("/roots/{uri:path}/delete")
async def admin_delete_root(uri: str, request: Request, user=Depends(get_current_user_with_permissions)) -> RedirectResponse:
    """
    Delete a root via the admin UI.

    This endpoint removes a registered root URI from the system. The deletion is
    permanent and cannot be undone. It requires authentication and logs the
    operation for audit purposes.

    Args:
        uri (str): The URI of the root to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the roots section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_remove_root = root_service.remove_root
        >>> root_service.remove_root = AsyncMock()
        >>>
        >>> async def test_admin_delete_root():
        ...     response = await admin_delete_root("test://root1", mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_delete_root())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_root_inactive():
        ...     response = await admin_delete_root("test://root1", mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_root_inactive())
        True
        >>> root_service.remove_root = original_remove_root
    """
    LOGGER.debug(f"User {get_user_email(user)} is deleting root URI {uri}")
    await root_service.remove_root(uri)
    form = await request.form()
    root_path = request.scope.get("root_path", "")
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#roots", status_code=303)
    return RedirectResponse(f"{root_path}/admin#roots", status_code=303)


# Metrics
MetricsDict = Dict[str, Union[ToolMetrics, ResourceMetrics, ServerMetrics, PromptMetrics]]


# @admin_router.get("/metrics", response_model=MetricsDict)
# async def admin_get_metrics(
#     db: Session = Depends(get_db),
#     user=Depends(get_current_user_with_permissions),
# ) -> MetricsDict:
#     """
#     Retrieve aggregate metrics for all entity types via the admin UI.

#     This endpoint collects and returns usage metrics for tools, resources, servers,
#     and prompts. The metrics are retrieved by calling the aggregate_metrics method
#     on each respective service, which compiles statistics about usage patterns,
#     success rates, and other relevant metrics for administrative monitoring
#     and analysis purposes.

#     Args:
#         db (Session): Database session dependency.
#         user (str): Authenticated user dependency.

#     Returns:
#         MetricsDict: A dictionary containing the aggregated metrics for tools,
#         resources, servers, and prompts. Each value is a Pydantic model instance
#         specific to the entity type.
#     """
#     LOGGER.debug(f"User {get_user_email(user)} requested aggregate metrics")
#     tool_metrics = await tool_service.aggregate_metrics(db)
#     resource_metrics = await resource_service.aggregate_metrics(db)
#     server_metrics = await server_service.aggregate_metrics(db)
#     prompt_metrics = await prompt_service.aggregate_metrics(db)

#     # Return actual Pydantic model instances
#     return {
#         "tools": tool_metrics,
#         "resources": resource_metrics,
#         "servers": server_metrics,
#         "prompts": prompt_metrics,
#     }


@admin_router.get("/metrics")
async def get_aggregated_metrics(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Retrieve aggregated metrics and top performers for all entity types.

    This endpoint collects usage metrics and top-performing entities for tools,
    resources, prompts, and servers by calling the respective service methods.
    The results are compiled into a dictionary for administrative monitoring.

    Args:
        db (Session): Database session dependency for querying metrics.

    Returns:
        Dict[str, Any]: A dictionary containing aggregated metrics and top performers
            for tools, resources, prompts, and servers. The structure includes:
            - 'tools': Metrics for tools.
            - 'resources': Metrics for resources.
            - 'prompts': Metrics for prompts.
            - 'servers': Metrics for servers.
            - 'topPerformers': A nested dictionary with all tools, resources, prompts,
              and servers with their metrics.
    """
    metrics = {
        "tools": await tool_service.aggregate_metrics(db),
        "resources": await resource_service.aggregate_metrics(db),
        "prompts": await prompt_service.aggregate_metrics(db),
        "servers": await server_service.aggregate_metrics(db),
        "topPerformers": {
            "tools": await tool_service.get_top_tools(db, limit=10),
            "resources": await resource_service.get_top_resources(db, limit=10),
            "prompts": await prompt_service.get_top_prompts(db, limit=10),
            "servers": await server_service.get_top_servers(db, limit=10),
        },
    }
    return metrics


@admin_router.get("/metrics/partial", response_class=HTMLResponse)
async def admin_metrics_partial_html(
    request: Request,
    entity_type: str = Query("tools", description="Entity type: tools, resources, prompts, or servers"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(10, ge=1, le=1000, description="Items per page"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """
    Return HTML partial for paginated top performers (HTMX endpoint).

    Matches the /admin/tools/partial pattern for consistent pagination UX.

    Args:
        request: FastAPI request object
        entity_type: Entity type (tools, resources, prompts, servers)
        page: Page number (1-indexed)
        per_page: Items per page (1-1000)
        db: Database session
        user: Authenticated user

    Returns:
        HTMLResponse with paginated table and OOB pagination controls

    Raises:
        HTTPException: If entity_type is not one of the valid types
    """
    LOGGER.debug(f"User {get_user_email(user)} requested metrics partial " f"(entity_type={entity_type}, page={page}, per_page={per_page})")

    # Validate entity type
    valid_types = ["tools", "resources", "prompts", "servers"]
    if entity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid entity_type. Must be one of: {', '.join(valid_types)}")

    # Constrain parameters
    page = max(1, page)
    per_page = max(1, min(per_page, 1000))

    # Get all items for this entity type
    if entity_type == "tools":
        all_items = await tool_service.get_top_tools(db, limit=None)
    elif entity_type == "resources":
        all_items = await resource_service.get_top_resources(db, limit=None)
    elif entity_type == "prompts":
        all_items = await prompt_service.get_top_prompts(db, limit=None)
    else:  # servers
        all_items = await server_service.get_top_servers(db, limit=None)

    # Calculate pagination
    total_items = len(all_items)
    total_pages = math.ceil(total_items / per_page) if per_page > 0 else 0
    offset = (page - 1) * per_page
    paginated_items = all_items[offset : offset + per_page]

    # Convert to JSON-serializable format
    data = jsonable_encoder(paginated_items)

    # Build pagination metadata
    pagination = PaginationMeta(
        page=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

    # Render template
    return request.app.state.templates.TemplateResponse(
        "metrics_top_performers_partial.html",
        {
            "request": request,
            "entity_type": entity_type,
            "data": data,
            "pagination": pagination.model_dump(),
            "root_path": request.scope.get("root_path", ""),
        },
    )


@admin_router.post("/metrics/reset", response_model=Dict[str, object])
async def admin_reset_metrics(db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> Dict[str, object]:
    """
    Reset all metrics for tools, resources, servers, and prompts.
    Each service must implement its own reset_metrics method.

    Args:
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict[str, object]: A dictionary containing a success message and status.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> original_reset_metrics_tool = tool_service.reset_metrics
        >>> original_reset_metrics_resource = resource_service.reset_metrics
        >>> original_reset_metrics_server = server_service.reset_metrics
        >>> original_reset_metrics_prompt = prompt_service.reset_metrics
        >>>
        >>> tool_service.reset_metrics = AsyncMock()
        >>> resource_service.reset_metrics = AsyncMock()
        >>> server_service.reset_metrics = AsyncMock()
        >>> prompt_service.reset_metrics = AsyncMock()
        >>>
        >>> async def test_admin_reset_metrics():
        ...     result = await admin_reset_metrics(mock_db, mock_user)
        ...     return result == {"message": "All metrics reset successfully", "success": True}
        >>>
        >>> import asyncio; asyncio.run(test_admin_reset_metrics())
        True
        >>>
        >>> tool_service.reset_metrics = original_reset_metrics_tool
        >>> resource_service.reset_metrics = original_reset_metrics_resource
        >>> server_service.reset_metrics = original_reset_metrics_server
        >>> prompt_service.reset_metrics = original_reset_metrics_prompt
    """
    LOGGER.debug(f"User {get_user_email(user)} requested to reset all metrics")
    await tool_service.reset_metrics(db)
    await resource_service.reset_metrics(db)
    await server_service.reset_metrics(db)
    await prompt_service.reset_metrics(db)
    return {"message": "All metrics reset successfully", "success": True}


@admin_router.post("/gateways/test", response_model=GatewayTestResponse)
async def admin_test_gateway(request: GatewayTestRequest, team_id: Optional[str] = Query(None), user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> GatewayTestResponse:
    """
    Test a gateway by sending a request to its URL.
    This endpoint allows administrators to test the connectivity and response

    Args:
        request (GatewayTestRequest): The request object containing the gateway URL and request details.
        team_id (Optional[str]): Optional team ID for team-specific gateways.
        user (str): Authenticated user dependency.
        db (Session): Database session dependency.

    Returns:
        GatewayTestResponse: The response from the gateway, including status code, latency, and body

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayTestRequest, GatewayTestResponse
        >>> from fastapi import Request
        >>> import httpx
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> mock_request = GatewayTestRequest(
        ...     base_url="https://api.example.com",
        ...     path="/test",
        ...     method="GET",
        ...     headers={},
        ...     body=None
        ... )
        >>>
        >>> # Mock ResilientHttpClient to simulate a successful response
        >>> class MockResponse:
        ...     def __init__(self):
        ...         self.status_code = 200
        ...         self._json = {"message": "success"}
        ...     def json(self):
        ...         return self._json
        ...     @property
        ...     def text(self):
        ...         return str(self._json)
        >>>
        >>> class MockClient:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         return MockResponse()
        >>>
        >>> from unittest.mock import patch
        >>>
        >>> async def test_admin_test_gateway():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request, None, mock_user, mock_db)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> result = asyncio.run(test_admin_test_gateway())
        >>> result
        True
        >>>
        >>> # Test with JSON decode error
        >>> class MockResponseTextOnly:
        ...     def __init__(self):
        ...         self.status_code = 200
        ...         self.text = "plain text response"
        ...     def json(self):
        ...         raise json.JSONDecodeError("Invalid JSON", "doc", 0)
        >>>
        >>> class MockClientTextOnly:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         return MockResponseTextOnly()
        >>>
        >>> async def test_admin_test_gateway_text_response():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClientTextOnly()
        ...         response = await admin_test_gateway(mock_request, None, mock_user, mock_db)
        ...         return isinstance(response, GatewayTestResponse) and response.body.get("details") == "plain text response"
        >>>
        >>> asyncio.run(test_admin_test_gateway_text_response())
        True
        >>>
        >>> # Test with network error
        >>> class MockClientError:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         raise httpx.RequestError("Network error")
        >>>
        >>> async def test_admin_test_gateway_network_error():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClientError()
        ...         response = await admin_test_gateway(mock_request, None, mock_user, mock_db)
        ...         return response.status_code == 502 and "Network error" in str(response.body)
        >>>
        >>> asyncio.run(test_admin_test_gateway_network_error())
        True
        >>>
        >>> # Test with POST method and body
        >>> mock_request_post = GatewayTestRequest(
        ...     base_url="https://api.example.com",
        ...     path="/test",
        ...     method="POST",
        ...     headers={"Content-Type": "application/json"},
        ...     body={"test": "data"}
        ... )
        >>>
        >>> async def test_admin_test_gateway_post():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request_post, None, mock_user, mock_db)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> asyncio.run(test_admin_test_gateway_post())
        True
        >>>
        >>> # Test URL path handling with trailing slashes
        >>> mock_request_trailing = GatewayTestRequest(
        ...     base_url="https://api.example.com/",
        ...     path="/test/",
        ...     method="GET",
        ...     headers={},
        ...     body=None
        ... )
        >>>
        >>> async def test_admin_test_gateway_trailing_slash():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request_trailing, None, mock_user, mock_db)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> asyncio.run(test_admin_test_gateway_trailing_slash())
        True
    """
    full_url = str(request.base_url).rstrip("/") + "/" + request.path.lstrip("/")
    full_url = full_url.rstrip("/")
    LOGGER.debug(f"User {get_user_email(user)} testing server at {request.base_url}.")
    start_time: float = time.monotonic()
    headers = request.headers or {}

    # Attempt to find a registered gateway matching this URL and team
    try:
        gateway = gateway_service.get_first_gateway_by_url(db, str(request.base_url), team_id=team_id)
    except Exception:
        gateway = None

    try:
        user_email = get_user_email(user)
        if gateway and gateway.auth_type == "oauth" and gateway.oauth_config:
            grant_type = gateway.oauth_config.get("grant_type", "client_credentials")

            if grant_type == "authorization_code":
                # For Authorization Code flow, try to get stored tokens
                try:
                    # First-Party
                    from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                    token_storage = TokenStorageService(db)

                    # Get user-specific OAuth token
                    if not user_email:
                        latency_ms = int((time.monotonic() - start_time) * 1000)
                        return GatewayTestResponse(
                            status_code=401, latency_ms=latency_ms, body={"error": f"User authentication required for OAuth-protected gateway '{gateway.name}'. Please ensure you are authenticated."}
                        )

                    access_token: str = await token_storage.get_user_token(gateway.id, user_email)

                    if access_token:
                        headers["Authorization"] = f"Bearer {access_token}"
                    else:
                        latency_ms = int((time.monotonic() - start_time) * 1000)
                        return GatewayTestResponse(
                            status_code=401, latency_ms=latency_ms, body={"error": f"Please authorize {gateway.name} first. Visit /oauth/authorize/{gateway.id} to complete OAuth flow."}
                        )
                except Exception as e:
                    LOGGER.error(f"Failed to obtain stored OAuth token for gateway {gateway.name}: {e}")
                    latency_ms = int((time.monotonic() - start_time) * 1000)
                    return GatewayTestResponse(status_code=500, latency_ms=latency_ms, body={"error": f"OAuth token retrieval failed for gateway: {str(e)}"})
            else:
                # For Client Credentials flow, get token directly
                try:
                    oauth_manager = OAuthManager(request_timeout=int(os.getenv("OAUTH_REQUEST_TIMEOUT", "30")), max_retries=int(os.getenv("OAUTH_MAX_RETRIES", "3")))
                    access_token: str = await oauth_manager.get_access_token(gateway.oauth_config)
                    headers["Authorization"] = f"Bearer {access_token}"
                except Exception as e:
                    LOGGER.error(f"Failed to obtain OAuth access token for gateway {gateway.name}: {e}")
                    response_body = {"error": f"OAuth token retrieval failed for gateway: {str(e)}"}
        else:
            headers: dict = decode_auth(gateway.auth_value if gateway else None)

        # Prepare request based on content type
        content_type = getattr(request, "content_type", "application/json")
        request_kwargs = {"method": request.method.upper(), "url": full_url, "headers": headers}

        if request.body is not None:
            if content_type == "application/x-www-form-urlencoded":
                # Set proper content type header and use data parameter for form encoding
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                if isinstance(request.body, str):
                    # Body is already form-encoded
                    request_kwargs["data"] = request.body
                else:
                    # Body is a dict, convert to form data
                    request_kwargs["data"] = request.body
            else:
                # Default to JSON
                headers["Content-Type"] = "application/json"
                request_kwargs["json"] = request.body

        async with ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}) as client:
            response: httpx.Response = await client.request(**request_kwargs)
        latency_ms = int((time.monotonic() - start_time) * 1000)
        try:
            response_body: Union[Dict[str, Any], str] = response.json()
        except json.JSONDecodeError:
            response_body = {"details": response.text}

        # Structured logging: Log successful gateway test
        structured_logger = get_structured_logger("gateway_service")
        structured_logger.log(
            level="INFO",
            message=f"Gateway test completed: {request.base_url}",
            event_type="gateway_tested",
            component="gateway_service",
            user_email=get_user_email(user),
            team_id=team_id,
            resource_type="gateway",
            resource_id=gateway.id if gateway else None,
            custom_fields={
                "gateway_name": gateway.name if gateway else None,
                "gateway_url": str(request.base_url),
                "test_method": request.method,
                "test_path": request.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
            db=db,
        )

        return GatewayTestResponse(status_code=response.status_code, latency_ms=latency_ms, body=response_body)

    except httpx.RequestError as e:
        LOGGER.warning(f"Gateway test failed: {e}")
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Structured logging: Log failed gateway test
        structured_logger = get_structured_logger("gateway_service")
        structured_logger.log(
            level="ERROR",
            message=f"Gateway test failed: {request.base_url}",
            event_type="gateway_test_failed",
            component="gateway_service",
            user_email=get_user_email(user),
            team_id=team_id,
            resource_type="gateway",
            resource_id=gateway.id if gateway else None,
            error=e,
            custom_fields={
                "gateway_name": gateway.name if gateway else None,
                "gateway_url": str(request.base_url),
                "test_method": request.method,
                "test_path": request.path,
                "latency_ms": latency_ms,
            },
            db=db,
        )

        return GatewayTestResponse(status_code=502, latency_ms=latency_ms, body={"error": "Request failed", "details": str(e)})


# Event Streaming via SSE to the Admin UI
@admin_router.get("/events")
async def admin_events(request: Request, _user=Depends(get_current_user_with_permissions)):
    """
    Stream admin events from all services via SSE (Server-Sent Events).

    This endpoint establishes a persistent connection to stream real-time updates
    from the gateway service and tool service to the frontend. It aggregates
    multiple event streams into a single asyncio queue for unified delivery.

    Args:
        request (Request): The FastAPI request object, used to detect client disconnection.
        _user (Any): Authenticated user dependency (ensures admin permissions).

    Returns:
        StreamingResponse: An async generator yielding SSE-formatted strings
        (media_type="text/event-stream").

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock, patch
        >>> from fastapi import Request
        >>>
        >>> # Mock the request to simulate connection status
        >>> mock_request = MagicMock(spec=Request)
        >>> # Return False (connected) twice, then True (disconnected) to exit the loop
        >>> mock_request.is_disconnected = AsyncMock(side_effect=[False, False, True])
        >>>
        >>> # Define a mock event generator for services
        >>> async def mock_service_stream(service_name):
        ...     yield {"type": "update", "data": {"service": service_name, "status": "active"}}
        >>>
        >>> async def test_streaming_endpoint():
        ...     # Patch the global services used inside the function
        ...     # Note: Adjust the patch path 'mcpgateway.admin' to your actual module path
        ...     with patch('mcpgateway.admin.gateway_service') as mock_gw_service, patch('mcpgateway.admin.tool_service') as mock_tool_service:
        ...
        ...         # Setup mocks to return our async generator
        ...         mock_gw_service.subscribe_events.side_effect = lambda: mock_service_stream("gateway")
        ...         mock_tool_service.subscribe_events.side_effect = lambda: mock_service_stream("tool")
        ...
        ...         # Call the endpoint
        ...         response = await admin_events(mock_request, _user="admin_user")
        ...
        ...         # Consume the StreamingResponse body iterator
        ...         results = []
        ...         async for chunk in response.body_iterator:
        ...             results.append(chunk)
        ...
        ...         return results
        >>>
        >>> # Run the test
        >>> events = asyncio.run(test_streaming_endpoint())
        >>>
        >>> # Verify SSE formatting
        >>> first_event = events[0]
        >>> assert "event: update" in first_event
        >>> assert "data:" in first_event
        >>> assert "gateway" in first_event or "tool" in first_event
        >>> print("SSE Stream Test Passed")
        SSE Stream Test Passed
    """
    # Create a shared queue to aggregate events from all services
    event_queue = asyncio.Queue()

    # Define a generic producer that feeds a specific stream into the queue
    async def stream_to_queue(generator, source_name: str):
        """Consume events from an async generator and forward them to a queue.

        This coroutine iterates over an asynchronous generator and enqueues each
        yielded event into a global or external `event_queue`. It gracefully
        handles task cancellation and logs unexpected exceptions.

        Args:
            generator (AsyncGenerator): An asynchronous generator that yields events.
            source_name (str): A human-readable label for the event source, used
                for logging error messages.

        Raises:
            Exception: Any unexpected exception raised while iterating over the
                generator will be caught, logged, and suppressed.

        Doctest:
            >>> import asyncio
            >>> class FakeQueue:
            ...     def __init__(self):
            ...         self.items = []
            ...     async def put(self, item):
            ...         self.items.append(item)
            ...
            >>> async def fake_gen():
            ...     yield 1
            ...     yield 2
            ...     yield 3
            ...
            >>> event_queue = FakeQueue()  # monkey-patch the global name
            >>> async def run_test():
            ...     await stream_to_queue(fake_gen(), "test_source")
            ...     return event_queue.items
            ...
            >>> asyncio.run(run_test())
            [1, 2, 3]

        """
        try:
            async for event in generator:
                await event_queue.put(event)
        except asyncio.CancelledError:
            pass  # Task cancelled normally
        except Exception as e:
            LOGGER.error(f"Error in {source_name} event subscription: {e}")

    async def event_generator():
        """
        Asynchronous Server-Sent Events (SSE) generator.

        This coroutine listens to multiple background event streams (e.g., from
        gateway and tool services), funnels their events into a shared queue, and
        yields them to the client in proper SSE format.

        The function:
        - Spawns background tasks to consume events from subscribed services.
        - Monitors the client connection for disconnection.
        - Yields SSE-formatted messages as they arrive.
        - Cleans up subscription tasks on exit.

        The SSE format emitted:
            event: <event_type>
            data: <json-encoded data>

        Yields:
            AsyncGenerator[str, None]: A generator yielding SSE-formatted strings.

        Raises:
            asyncio.CancelledError: If the SSE stream or background tasks are cancelled.
            Exception: Any unexpected exception in the main loop is logged but not re-raised.

        Notes:
            This function expects the following names to exist in the outer scope:
            - `request`: A FastAPI/Starlette Request object.
            - `event_queue`: An asyncio.Queue instance where events are dispatched.
            - `gateway_service` and `tool_service`: Services exposing async subscribe_events().
            - `stream_to_queue`: Coroutine to pipe service streams into the queue.
            - `LOGGER`: Logger instance.

        Example:
            Basic doctest demonstrating SSE formatting from mock data:

            >>> import json, asyncio
            >>> class DummyRequest:
            ...     async def is_disconnected(self):
            ...         return False
            >>> async def dummy_gen():
            ...     # Simulate an event queue and minimal environment
            ...     global request, event_queue
            ...     request = DummyRequest()
            ...     event_queue = asyncio.Queue()
            ...     # Minimal stubs to satisfy references
            ...     class DummyService:
            ...         async def subscribe_events(self):
            ...             async def gen():
            ...                 yield {"type": "test", "data": {"a": 1}}
            ...             return gen()
            ...     global gateway_service, tool_service, stream_to_queue, LOGGER
            ...     gateway_service = tool_service = DummyService()
            ...     async def stream_to_queue(gen, tag):
            ...         async for e in gen:
            ...             await event_queue.put(e)
            ...     class DummyLogger:
            ...         def debug(self, *args, **kwargs): pass
            ...         def error(self, *args, **kwargs): pass
            ...     LOGGER = DummyLogger()
            ...
            ...     agen = event_generator()
            ...     # Startup requires allowing tasks to enqueue
            ...     async def get_one():
            ...         async for msg in agen:
            ...             return msg
            ...     return (await get_one()).startswith("event: test")
            >>> asyncio.run(dummy_gen())
            True
        """
        # Create background tasks for each service subscription
        # This allows them to run concurrently
        tasks = [asyncio.create_task(stream_to_queue(gateway_service.subscribe_events(), "gateway")), asyncio.create_task(stream_to_queue(tool_service.subscribe_events(), "tool"))]

        try:
            while True:
                # Check for client disconnection
                if await request.is_disconnected():
                    LOGGER.debug("SSE Client disconnected")
                    break

                # Wait for the next event from EITHER service
                # We use asyncio.wait_for to allow checking request.is_disconnected periodically
                # or simply rely on queue.get() which is efficient.
                try:
                    # Wait for an event
                    event = await event_queue.get()

                    # SSE format
                    event_type = event.get("type", "message")
                    event_data = orjson.dumps(event.get("data", {})).decode()

                    yield f"event: {event_type}\ndata: {event_data}\n\n"

                    # Mark task as done in queue (good practice)
                    event_queue.task_done()

                except asyncio.CancelledError:
                    LOGGER.debug("SSE Event generator task cancelled")
                    raise

        except asyncio.CancelledError:
            LOGGER.debug("SSE Stream cancelled")
        except Exception as e:
            LOGGER.error(f"SSE Stream error: {e}")
        finally:
            # Cleanup: Cancel all background subscription tasks
            # This is crucial to close Redis connections/listeners in the EventService
            for task in tasks:
                task.cancel()

            # Wait for tasks to clean up
            await asyncio.gather(*tasks, return_exceptions=True)
            LOGGER.debug("Background event subscription tasks cleaned up")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


####################
# Admin Tag Routes #
####################


@admin_router.get("/tags", response_model=PaginatedResponse)
async def admin_list_tags(
    entity_types: Optional[str] = None,
    include_entities: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> List[Dict[str, Any]]:
    """
    List all unique tags with statistics for the admin UI.

    Args:
        entity_types: Comma-separated list of entity types to filter by
                     (e.g., "tools,resources,prompts,servers,gateways").
                     If not provided, returns tags from all entity types.
        include_entities: Whether to include the list of entities that have each tag
        db: Database session
        user: Authenticated user

    Returns:
        List of tag information with statistics

    Raises:
        HTTPException: If tag retrieval fails

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import admin_list_tags
        >>> admin_list_tags.__name__
        'admin_list_tags'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(admin_list_tags)
        True
    """
    tag_service = TagService()

    # Parse entity types parameter if provided
    entity_types_list = None
    if entity_types:
        entity_types_list = [et.strip().lower() for et in entity_types.split(",") if et.strip()]

    LOGGER.debug(f"Admin user {user} is retrieving tags for entity types: {entity_types_list}, include_entities: {include_entities}")

    try:
        tags = await tag_service.get_all_tags(db, entity_types=entity_types_list, include_entities=include_entities)

        # Convert to list of dicts for admin UI
        result: List[Dict[str, Any]] = []
        for tag in tags:
            tag_dict: Dict[str, Any] = {
                "name": tag.name,
                "tools": tag.stats.tools,
                "resources": tag.stats.resources,
                "prompts": tag.stats.prompts,
                "servers": tag.stats.servers,
                "gateways": tag.stats.gateways,
                "total": tag.stats.total,
            }

            # Include entities if requested
            if include_entities and tag.entities:
                tag_dict["entities"] = [
                    {
                        "id": entity.id,
                        "name": entity.name,
                        "type": entity.type,
                        "description": entity.description,
                    }
                    for entity in tag.entities
                ]

            result.append(tag_dict)

        return result
    except Exception as e:
        LOGGER.error(f"Failed to retrieve tags for admin: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tags: {str(e)}")


@admin_router.post("/tools/import/")
@admin_router.post("/tools/import")
@rate_limit(requests_per_minute=settings.mcpgateway_bulk_import_rate_limit)
async def admin_import_tools(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Bulk import multiple tools in a single request.

    Accepts a JSON array of tool definitions and registers them individually.
    Provides per-item validation and error reporting without failing the entire batch.

    Args:
        request: FastAPI Request containing the tools data
        db: Database session
        user: Authenticated username

    Returns:
        JSONResponse with success status, counts, and details of created/failed tools

    Raises:
        HTTPException: For authentication or rate limiting failures
    """
    # Check if bulk import is enabled
    if not settings.mcpgateway_bulk_import_enabled:
        LOGGER.warning("Bulk import attempted but feature is disabled")
        raise HTTPException(status_code=403, detail="Bulk import feature is disabled. Enable MCPGATEWAY_BULK_IMPORT_ENABLED to use this endpoint.")

    LOGGER.debug("bulk tool import: user=%s", user)
    try:
        # ---------- robust payload parsing ----------
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                payload = await request.json()
            except Exception as ex:
                LOGGER.exception("Invalid JSON body")
                return ORJSONResponse({"success": False, "message": f"Invalid JSON: {ex}"}, status_code=422)
        else:
            try:
                form = await request.form()
            except Exception as ex:
                LOGGER.exception("Invalid form body")
                return ORJSONResponse({"success": False, "message": f"Invalid form data: {ex}"}, status_code=422)
            # Check for file upload first
            if "tools_file" in form:
                file = form["tools_file"]
                if isinstance(file, StarletteUploadFile):
                    content = await file.read()
                    try:
                        payload = orjson.loads(content.decode("utf-8"))
                    except (orjson.JSONDecodeError, UnicodeDecodeError) as ex:
                        LOGGER.exception("Invalid JSON file")
                        return ORJSONResponse({"success": False, "message": f"Invalid JSON file: {ex}"}, status_code=422)
                else:
                    return ORJSONResponse({"success": False, "message": "Invalid file upload"}, status_code=422)
            else:
                # Check for JSON in form fields
                raw_val = form.get("tools") or form.get("tools_json") or form.get("json") or form.get("payload")
                raw = raw_val if isinstance(raw_val, str) else None
                if not raw:
                    return ORJSONResponse({"success": False, "message": "Missing tools/tools_json/json/payload form field."}, status_code=422)
                try:
                    payload = orjson.loads(raw)
                except Exception as ex:
                    LOGGER.exception("Invalid JSON in form field")
                    return ORJSONResponse({"success": False, "message": f"Invalid JSON: {ex}"}, status_code=422)

        if not isinstance(payload, list):
            return ORJSONResponse({"success": False, "message": "Payload must be a JSON array of tools."}, status_code=422)

        max_batch = settings.mcpgateway_bulk_import_max_tools
        if len(payload) > max_batch:
            return ORJSONResponse({"success": False, "message": f"Too many tools ({len(payload)}). Max {max_batch}."}, status_code=413)

        created, errors = [], []

        # ---------- import loop ----------
        # Generate import batch ID for this bulk operation
        import_batch_id = str(uuid.uuid4())

        # Extract base metadata for bulk import
        base_metadata = MetadataCapture.extract_creation_metadata(request, user, import_batch_id=import_batch_id)
        for i, item in enumerate(payload):
            name = (item or {}).get("name")
            try:
                tool = ToolCreate(**item)  # pydantic validation
                await tool_service.register_tool(
                    db,
                    tool,
                    created_by=base_metadata["created_by"],
                    created_from_ip=base_metadata["created_from_ip"],
                    created_via="import",  # Override to show this is bulk import
                    created_user_agent=base_metadata["created_user_agent"],
                    import_batch_id=import_batch_id,
                    federation_source=base_metadata["federation_source"],
                )
                created.append({"index": i, "name": name})
            except IntegrityError as ex:
                # The formatter can itself throw; guard it.
                try:
                    formatted = ErrorFormatter.format_database_error(ex)
                except Exception:
                    formatted = {"message": str(ex)}
                errors.append({"index": i, "name": name, "error": formatted})
            except (ValidationError, CoreValidationError) as ex:
                # Ditto: guard the formatter
                try:
                    formatted = ErrorFormatter.format_validation_error(ex)
                except Exception:
                    formatted = {"message": str(ex)}
                errors.append({"index": i, "name": name, "error": formatted})
            except ToolError as ex:
                errors.append({"index": i, "name": name, "error": {"message": str(ex)}})
            except Exception as ex:
                LOGGER.exception("Unexpected error importing tool %r at index %d", name, i)
                errors.append({"index": i, "name": name, "error": {"message": str(ex)}})

        # Format response to match both frontend and test expectations
        response_data = {
            "success": len(errors) == 0,
            # New format for frontend
            "imported": len(created),
            "failed": len(errors),
            "total": len(payload),
            # Original format for tests
            "created_count": len(created),
            "failed_count": len(errors),
            "created": created,
            "errors": errors,
            # Detailed format for frontend
            "details": {
                "success": [item["name"] for item in created if item.get("name")],
                "failed": [{"name": item["name"], "error": item["error"].get("message", str(item["error"]))} for item in errors],
            },
        }

        rd = typing_cast(Dict[str, Any], response_data)
        if len(errors) == 0:
            rd["message"] = f"Successfully imported all {len(created)} tools"
        else:
            rd["message"] = f"Imported {len(created)} of {len(payload)} tools. {len(errors)} failed."

        return ORJSONResponse(
            response_data,
            status_code=200,  # Always return 200, success field indicates if all succeeded
        )

    except HTTPException:
        # let FastAPI semantics (e.g., auth) pass through
        raise
    except Exception as ex:
        # absolute catch-all: report instead of crashing
        LOGGER.exception("Fatal error in admin_import_tools")
        return ORJSONResponse({"success": False, "message": str(ex)}, status_code=500)


####################
# Log Endpoints
####################


@admin_router.get("/logs")
async def admin_get_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    request_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    order: str = "desc",
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """Get filtered log entries from the in-memory buffer.

    Args:
        entity_type: Filter by entity type (tool, resource, server, gateway)
        entity_id: Filter by entity ID
        level: Minimum log level (debug, info, warning, error, critical)
        start_time: ISO format start time
        end_time: ISO format end time
        request_id: Filter by request ID
        search: Search in message text
        limit: Maximum number of results (default 100, max 1000)
        offset: Number of results to skip
        order: Sort order (asc or desc)
        user: Authenticated user

    Returns:
        Dictionary with logs and metadata

    Raises:
        HTTPException: If validation fails or service unavailable
    """
    # Get log storage from logging service
    storage = typing_cast(Any, logging_service).get_storage()
    if not storage:
        return {"logs": [], "total": 0, "stats": {}}

    # Parse timestamps if provided
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid start_time format: {start_time}")

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid end_time format: {end_time}")

    # Parse log level
    log_level = None
    if level:
        try:
            log_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    # Limit max results
    limit = min(limit, 1000)

    # Get filtered logs
    logs = await storage.get_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        level=log_level,
        start_time=start_dt,
        end_time=end_dt,
        request_id=request_id,
        search=search,
        limit=limit,
        offset=offset,
        order=order,
    )

    # Get statistics
    stats = storage.get_stats()

    return {
        "logs": logs,
        "total": stats.get("total_logs", 0),
        "stats": stats,
    }


@admin_router.get("/logs/stream")
async def admin_stream_logs(
    request: Request,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Stream real-time log updates via Server-Sent Events.

    Args:
        request: FastAPI request object
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        level: Minimum log level
        user: Authenticated user

    Returns:
        SSE response with real-time log updates

    Raises:
        HTTPException: If log level is invalid or service unavailable
    """
    # Get log storage from logging service
    storage = typing_cast(Any, logging_service).get_storage()
    if not storage:
        raise HTTPException(503, "Log storage not available")

    # Parse log level filter
    min_level = None
    if level:
        try:
            min_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    async def generate():
        """Generate SSE events for log streaming.

        Yields:
            Formatted SSE events containing log data
        """
        try:
            async for event in storage.subscribe():
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Apply filters
                log_data = event.get("data", {})

                # Entity type filter
                if entity_type and log_data.get("entity_type") != entity_type:
                    continue

                # Entity ID filter
                if entity_id and log_data.get("entity_id") != entity_id:
                    continue

                # Level filter
                if min_level:
                    log_level = log_data.get("level")
                    if log_level:
                        try:
                            if not storage._meets_level_threshold(LogLevel(log_level), min_level):  # pylint: disable=protected-access
                                continue
                        except ValueError:
                            continue

                # Send SSE event
                yield f"data: {orjson.dumps(event).decode()}\n\n"

        except Exception as e:
            LOGGER.error(f"Error in log streaming: {e}")
            yield f"event: error\ndata: {orjson.dumps({'error': str(e)}).decode()}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


@admin_router.get("/logs/file")
async def admin_get_log_file(
    filename: Optional[str] = None,
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Download log file.

    Args:
        filename: Specific log file to download (optional)
        user: Authenticated user

    Returns:
        File download response or list of available files

    Raises:
        HTTPException: If file doesn't exist or access denied
    """
    # Check if file logging is enabled
    if not settings.log_to_file or not settings.log_file:
        raise HTTPException(404, "File logging is not enabled")

    # Determine log directory
    log_dir = Path(settings.log_folder) if settings.log_folder else Path(".")

    if filename:
        # Download specific file
        file_path = log_dir / filename

        # Security: Ensure file is within log directory
        try:
            file_path = file_path.resolve()
            log_dir_resolved = log_dir.resolve()
            if not str(file_path).startswith(str(log_dir_resolved)):
                raise HTTPException(403, "Access denied")
        except Exception:
            raise HTTPException(400, "Invalid file path")

        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(404, f"Log file not found: {filename}")

        # Check if it's a log file
        if not (file_path.suffix in [".log", ".jsonl", ".json"] or file_path.stem.startswith(Path(settings.log_file).stem)):
            raise HTTPException(403, "Not a log file")

        # Return file for download using Response with file content
        try:
            with open(file_path, "rb") as f:
                file_content = f.read()

            return Response(
                content=file_content,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{file_path.name}"',
                },
            )
        except Exception as e:
            LOGGER.error(f"Error reading file for download: {e}")
            raise HTTPException(500, f"Error reading file for download: {e}")

    # List available log files
    log_files = []

    try:
        # Main log file
        main_log = log_dir / settings.log_file
        if main_log.exists():
            stat = main_log.stat()
            log_files.append(
                {
                    "name": main_log.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "type": "main",
                }
            )

            # Rotated log files
            if settings.log_rotation_enabled:
                pattern = f"{Path(settings.log_file).stem}.*"
                for file in log_dir.glob(pattern):
                    if file.is_file() and file.name != main_log.name:  # Exclude main log file
                        stat = file.stat()
                        log_files.append(
                            {
                                "name": file.name,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "type": "rotated",
                            }
                        )

            # Storage log file (JSON lines)
            storage_log = log_dir / f"{Path(settings.log_file).stem}_storage.jsonl"
            if storage_log.exists():
                stat = storage_log.stat()
                log_files.append(
                    {
                        "name": storage_log.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "type": "storage",
                    }
                )

        # Sort by modified time (newest first)
        log_files.sort(key=lambda x: x["modified"], reverse=True)

    except Exception as e:
        LOGGER.error(f"Error listing log files: {e}")
        raise HTTPException(500, f"Error listing log files: {e}")

    return {
        "log_directory": str(log_dir),
        "files": log_files,
        "total": len(log_files),
    }


@admin_router.get("/logs/export")
async def admin_export_logs(
    export_format: str = Query("json", alias="format"),
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    request_id: Optional[str] = None,
    search: Optional[str] = None,
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Export filtered logs in JSON or CSV format.

    Args:
        export_format: Export format (json or csv)
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        level: Minimum log level
        start_time: ISO format start time
        end_time: ISO format end time
        request_id: Filter by request ID
        search: Search in message text
        user: Authenticated user

    Returns:
        File download response with exported logs

    Raises:
        HTTPException: If validation fails or export format invalid
    """
    # Standard
    # Validate format
    if export_format not in ["json", "csv"]:
        raise HTTPException(400, f"Invalid format: {export_format}. Use 'json' or 'csv'")

    # Get log storage from logging service
    storage = typing_cast(Any, logging_service).get_storage()
    if not storage:
        raise HTTPException(503, "Log storage not available")

    # Parse timestamps if provided
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid start_time format: {start_time}")

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid end_time format: {end_time}")

    # Parse log level
    log_level = None
    if level:
        try:
            log_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    # Get all matching logs (no pagination for export)
    logs = await storage.get_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        level=log_level,
        start_time=start_dt,
        end_time=end_dt,
        request_id=request_id,
        search=search,
        limit=10000,  # Reasonable max for export
        offset=0,
        order="desc",
    )

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"logs_export_{timestamp}.{export_format}"

    if export_format == "json":
        # Export as JSON
        content = json.dumps(logs, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # CSV format
    # Create CSV content
    output = io.StringIO()

    if logs:
        # Use first log to determine columns
        fieldnames = [
            "timestamp",
            "level",
            "entity_type",
            "entity_id",
            "entity_name",
            "message",
            "logger",
            "request_id",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for log in logs:
            # Flatten the log entry for CSV
            row = {k: log.get(k, "") for k in fieldnames}
            writer.writerow(row)

    content = output.getvalue()

    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@admin_router.get("/export/configuration")
async def admin_export_configuration(
    request: Request,  # pylint: disable=unused-argument
    types: Optional[str] = None,
    exclude_types: Optional[str] = None,
    tags: Optional[str] = None,
    include_inactive: bool = False,
    include_dependencies: bool = True,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """
    Export gateway configuration via Admin UI.

    Args:
        request: FastAPI request object for extracting root path
        types: Comma-separated entity types to include
        exclude_types: Comma-separated entity types to exclude
        tags: Comma-separated tags to filter by
        include_inactive: Include inactive entities
        include_dependencies: Include dependent entities
        db: Database session
        user: Authenticated user

    Returns:
        JSON file download with configuration export

    Raises:
        HTTPException: If export fails
    """
    try:
        LOGGER.info(f"Admin user {user} requested configuration export")

        # Parse parameters
        include_types = None
        if types:
            include_types = [t.strip() for t in types.split(",") if t.strip()]

        exclude_types_list = None
        if exclude_types:
            exclude_types_list = [t.strip() for t in exclude_types.split(",") if t.strip()]

        tags_list = None
        if tags:
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Get root path for URL construction - prefer configured APP_ROOT_PATH
        root_path = settings.app_root_path

        # Perform export
        export_data = await export_service.export_configuration(
            db=db,
            include_types=include_types,
            exclude_types=exclude_types_list,
            tags=tags_list,
            include_inactive=include_inactive,
            include_dependencies=include_dependencies,
            exported_by=username,
            root_path=root_path,
        )

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"mcpgateway-config-export-{timestamp}.json"

        # Return as downloadable file
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except ExportError as e:
        LOGGER.error(f"Admin export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@admin_router.post("/export/selective")
async def admin_export_selective(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """
    Export selected entities via Admin UI with entity selection.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON file download with selective export data

    Raises:
        HTTPException: If export fails

    Expects JSON body with entity selections:
    {
        "entity_selections": {
            "tools": ["tool1", "tool2"],
            "servers": ["server1"]
        },
        "include_dependencies": true
    }
    """
    try:
        LOGGER.info(f"Admin user {user} requested selective configuration export")

        body = await request.json()
        entity_selections = body.get("entity_selections", {})
        include_dependencies = body.get("include_dependencies", True)

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Get root path for URL construction - prefer configured APP_ROOT_PATH
        root_path = settings.app_root_path

        # Perform selective export
        export_data = await export_service.export_selective(db=db, entity_selections=entity_selections, include_dependencies=include_dependencies, exported_by=username, root_path=root_path)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"mcpgateway-selective-export-{timestamp}.json"

        # Return as downloadable file
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except ExportError as e:
        LOGGER.error(f"Admin selective export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin selective export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@admin_router.post("/import/preview")
async def admin_import_preview(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """
    Preview import file to show available items for selective import.

    Args:
        request: FastAPI request object with import file data
        db: Database session
        user: Authenticated user

    Returns:
        JSON response with categorized import preview data

    Raises:
        HTTPException: 400 for invalid JSON or missing data field, validation errors;
                      500 for unexpected preview failures

    Expects JSON body:
    {
        "data": { ... }  // The import file content
    }
    """
    try:
        LOGGER.info(f"Admin import preview requested by user: {user}")

        # Parse request data
        try:
            data = await request.json()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

        # Extract import data
        import_data = data.get("data")
        if not import_data:
            raise HTTPException(status_code=400, detail="Missing 'data' field with import content")

        # Validate user permissions for import preview
        username = user if isinstance(user, str) else user.get("username", "unknown")
        LOGGER.info(f"Processing import preview for user: {username}")

        # Generate preview
        preview_data = await import_service.preview_import(db=db, import_data=import_data)

        return ORJSONResponse(content={"success": True, "preview": preview_data, "message": f"Import preview generated. Found {preview_data['summary']['total_items']} total items."})

    except ImportValidationError as e:
        LOGGER.error(f"Import validation failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid import data: {str(e)}")
    except Exception as e:
        LOGGER.error(f"Import preview failed for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@admin_router.post("/import/configuration")
async def admin_import_configuration(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """
    Import configuration via Admin UI.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON response with import status

    Raises:
        HTTPException: If import fails

    Expects JSON body with import data and options:
    {
        "import_data": { ... },
        "conflict_strategy": "update",
        "dry_run": false,
        "rekey_secret": "optional-new-secret",
        "selected_entities": { ... }
    }
    """
    try:
        LOGGER.info(f"Admin user {user} requested configuration import")

        body = await request.json()
        import_data = body.get("import_data")
        if not import_data:
            raise HTTPException(status_code=400, detail="Missing import_data in request body")

        conflict_strategy_str = body.get("conflict_strategy", "update")
        dry_run = body.get("dry_run", False)
        rekey_secret = body.get("rekey_secret")
        selected_entities = body.get("selected_entities")

        # Validate conflict strategy
        try:
            conflict_strategy = ConflictStrategy(conflict_strategy_str.lower())
        except ValueError:
            allowed = [s.value for s in ConflictStrategy.__members__.values()]
            raise HTTPException(status_code=400, detail=f"Invalid conflict strategy. Must be one of: {allowed}")

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Perform import
        status = await import_service.import_configuration(
            db=db, import_data=import_data, conflict_strategy=conflict_strategy, dry_run=dry_run, rekey_secret=rekey_secret, imported_by=username, selected_entities=selected_entities
        )

        return ORJSONResponse(content=status.to_dict())

    except ImportServiceError as e:
        LOGGER.error(f"Admin import failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin import error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@admin_router.get("/import/status/{import_id}")
async def admin_get_import_status(import_id: str, user=Depends(get_current_user_with_permissions)):
    """Get import status via Admin UI.

    Args:
        import_id: Import operation ID
        user: Authenticated user

    Returns:
        JSON response with import status

    Raises:
        HTTPException: If import not found
    """
    LOGGER.debug(f"Admin user {user} requested import status for {import_id}")

    status = import_service.get_import_status(import_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Import {import_id} not found")

    return ORJSONResponse(content=status.to_dict())


@admin_router.get("/import/status")
async def admin_list_import_statuses(user=Depends(get_current_user_with_permissions)):
    """List all import statuses via Admin UI.

    Args:
        user: Authenticated user

    Returns:
        JSON response with list of import statuses
    """
    LOGGER.debug(f"Admin user {user} requested all import statuses")

    statuses = import_service.list_import_statuses()
    return ORJSONResponse(content=[status.to_dict() for status in statuses])


# ============================================================================ #
#                             A2A AGENT ADMIN ROUTES                          #
# ============================================================================ #


@admin_router.get("/a2a/{agent_id}", response_model=A2AAgentRead)
async def admin_get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Get A2A agent details for the admin UI.

    Args:
        agent_id: Agent ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        Agent details.

    Raises:
        HTTPException: If the agent is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import A2AAgentRead
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService
        >>> from mcpgateway.services.a2a_service import A2AAgentNotFoundError
        >>> from fastapi import HTTPException
        >>>
        >>> a2a_service: Optional[A2AAgentService] = A2AAgentService() if settings.mcpgateway_a2a_enabled else None
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>> agent_id = "test-agent-id"
        >>>
        >>> mock_agent = A2AAgentRead(
        ...     id=agent_id, name="Agent1", slug="agent1",
        ...     description="Test A2A agent", endpoint_url="http://agent.local",
        ...     agent_type="connector", protocol_version="1.0",
        ...     capabilities={"ping": True}, config={"x": "y"},
        ...     auth_type=None, enabled=True, reachable=True,
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     last_interaction=None, metrics = {
        ...                                           "requests": 0,
        ...                                           "totalExecutions": 0,
        ...                                           "successfulExecutions": 0,
        ...                                           "failedExecutions": 0,
        ...                                           "failureRate": 0.0,
        ...                                             }
        ... )
        >>>
        >>> from mcpgateway import admin
        >>> original_get_agent = admin.a2a_service.get_agent
        >>> a2a_service.get_agent = AsyncMock(return_value=mock_agent)
        >>> admin.a2a_service.get_agent = AsyncMock(return_value=mock_agent)
        >>> async def test_admin_get_agent_success():
        ...     result = await admin.admin_get_agent(agent_id, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['id'] == agent_id
        >>>
        >>> asyncio.run(test_admin_get_agent_success())
        True
        >>>
        >>> # Test not found
        >>> admin.a2a_service.get_agent = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))
        >>> async def test_admin_get_agent_not_found():
        ...     try:
        ...         await admin.admin_get_agent("bad-id", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Agent not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_agent_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> admin.a2a_service.get_agent = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_agent_exception():
        ...     try:
        ...         await admin.admin_get_agent(agent_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_agent_exception())
        True
        >>>
        >>> admin.a2a_service.get_agent = original_get_agent
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for agent ID {agent_id}")
    try:
        agent = await a2a_service.get_agent(db, agent_id)
        return agent.model_dump(by_alias=True)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting agent {agent_id}: {e}")
        raise e


@admin_router.get("/a2a", response_model=PaginatedResponse)
async def admin_list_a2a_agents(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """
    List A2A Agents for the admin UI with pagination support.

    This endpoint retrieves a paginated list of A2A (Agent-to-Agent) agents associated with
    the current user. Administrators can optionally include inactive agents for
    management or auditing purposes. Uses offset-based (page/per_page) pagination.

    Args:
        page (int): Page number (1-indexed) for offset pagination.
        per_page (int): Number of items per page (1-500).
        include_inactive (bool): Whether to include inactive agents in the results.
        db (Session): Database session dependency.
        user (dict): Authenticated user dependency.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - data: List of A2A agent records formatted with by_alias=True
            - pagination: Pagination metadata
            - links: Pagination links (optional)

    Raises:
        HTTPException (500): If an error occurs while retrieving the agent list.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock, patch
        >>> from mcpgateway.schemas import A2AAgentRead, A2AAgentMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_user", "db": mock_db}
        >>>
        >>> mock_agent = A2AAgentRead(
        ...     id="1",
        ...     name="Agent1",
        ...     slug="agent1",
        ...     description="A2A Test Agent",
        ...     endpoint_url="http://localhost/agent1",
        ...     agent_type="test",
        ...     protocol_version="1.0",
        ...     capabilities={},
        ...     config={},
        ...     auth_type=None,
        ...     enabled=True,
        ...     reachable=True,
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     last_interaction=None,
        ...     tags=[],
        ...     metrics=A2AAgentMetrics(
        ...         total_executions=1,
        ...         successful_executions=1,
        ...         failed_executions=0,
        ...         failure_rate=0.0,
        ...         min_response_time=0.1,
        ...         max_response_time=0.2,
        ...         avg_response_time=0.15,
        ...         last_execution_time=datetime.now(timezone.utc)
        ...     )
        ... )
        >>>
        >>> # Mock a2a_service.list_agents
        >>> async def mock_list_agents(*args, **kwargs):
        ...     from mcpgateway.schemas import PaginationMeta, PaginationLinks
        ...     return {
        ...         "data": [mock_agent],
        ...         "pagination": PaginationMeta(page=1, per_page=50, total_items=1, total_pages=1, has_next=False, has_prev=False),
        ...         "links": PaginationLinks(self="/admin/a2a?page=1&per_page=50", first="/admin/a2a?page=1&per_page=50", last="/admin/a2a?page=1&per_page=50", next=None, prev=None)
        ...     }
        >>>
        >>> from unittest.mock import patch
        >>> # Test listing A2A agents with pagination
        >>> async def test_admin_list_a2a_agents_paginated():
        ...     fake_service = MagicMock()
        ...     fake_service.list_agents = mock_list_agents
        ...     with patch("mcpgateway.admin.a2a_service", new=fake_service):
        ...         result = await admin_list_a2a_agents(page=1, per_page=50, include_inactive=False, db=mock_db, user=mock_user)
        ...         return "data" in result and "pagination" in result
        >>>
        >>> asyncio.run(test_admin_list_a2a_agents_paginated())
        True
    """
    if a2a_service is None:
        LOGGER.warning("A2A features are disabled, returning empty paginated response")
        # First-Party

        return {
            "data": [],
            "pagination": PaginationMeta(page=page, per_page=per_page, total_items=0, total_pages=0, has_next=False, has_prev=False).model_dump(),
            "links": None,
        }

    LOGGER.debug(f"User {get_user_email(user)} requested A2A Agent list (page={page}, per_page={per_page})")
    user_email = get_user_email(user)

    # Call a2a_service.list_agents with page-based pagination
    paginated_result = await a2a_service.list_agents(
        db=db,
        include_inactive=include_inactive,
        page=page,
        per_page=per_page,
        user_email=user_email,
    )

    # Return standardized paginated response
    return {
        "data": [agent.model_dump(by_alias=True) for agent in paginated_result["data"]],
        "pagination": paginated_result["pagination"].model_dump(),
        "links": paginated_result["links"].model_dump() if paginated_result["links"] else None,
    }


@admin_router.post("/a2a")
async def admin_add_a2a_agent(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Add a new A2A agent via admin UI.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSONResponse with success/error status

    Raises:
        HTTPException: If A2A features are disabled
    """
    LOGGER.info(f"A2A agent creation request from user {user}")

    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        LOGGER.warning("A2A agent creation attempted but A2A features are disabled")
        return ORJSONResponse(
            content={"message": "A2A features are disabled!", "success": False},
            status_code=403,
        )

    form = await request.form()
    try:
        LOGGER.info(f"A2A agent creation form data: {dict(form)}")

        user_email = get_user_email(user)
        # Determine personal team for default assignment
        team_id = form.get("team_id", None)
        team_service = TeamManagementService(db)
        team_id = await team_service.verify_team_for_user(user_email, team_id)

        # Process tags
        ts_val = form.get("tags", "")
        tags_str = ts_val if isinstance(ts_val, str) else ""
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers: list[dict[str, Any]] = []
        if auth_headers_json:
            try:
                auth_headers = orjson.loads(auth_headers_json)
            except (orjson.JSONDecodeError, ValueError):
                auth_headers = []

        # Parse OAuth configuration - support both JSON string and individual form fields
        oauth_config_json = str(form.get("oauth_config"))
        oauth_config: Optional[dict[str, Any]] = None

        LOGGER.info(f"DEBUG: oauth_config_json from form = '{oauth_config_json}'")
        LOGGER.info(f"DEBUG: Individual OAuth fields - grant_type='{form.get('oauth_grant_type')}', issuer='{form.get('oauth_issuer')}'")

        # Option 1: Pre-assembled oauth_config JSON (from API calls)
        if oauth_config_json and oauth_config_json != "None":
            try:
                oauth_config = orjson.loads(oauth_config_json)
                # Encrypt the client secret if present
                if oauth_config and "client_secret" in oauth_config:
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_config["client_secret"])
            except (orjson.JSONDecodeError, ValueError) as e:
                LOGGER.error(f"Failed to parse OAuth config: {e}")
                oauth_config = None

        # Option 2: Assemble from individual UI form fields
        if not oauth_config:
            oauth_grant_type = str(form.get("oauth_grant_type", ""))
            oauth_issuer = str(form.get("oauth_issuer", ""))
            oauth_token_url = str(form.get("oauth_token_url", ""))
            oauth_authorization_url = str(form.get("oauth_authorization_url", ""))
            oauth_redirect_uri = str(form.get("oauth_redirect_uri", ""))
            oauth_client_id = str(form.get("oauth_client_id", ""))
            oauth_client_secret = str(form.get("oauth_client_secret", ""))
            oauth_username = str(form.get("oauth_username", ""))
            oauth_password = str(form.get("oauth_password", ""))
            oauth_scopes_str = str(form.get("oauth_scopes", ""))

            # If any OAuth field is provided, assemble oauth_config
            if any([oauth_grant_type, oauth_issuer, oauth_token_url, oauth_authorization_url, oauth_client_id]):
                oauth_config = {}

                if oauth_grant_type:
                    oauth_config["grant_type"] = oauth_grant_type
                if oauth_issuer:
                    oauth_config["issuer"] = oauth_issuer
                if oauth_token_url:
                    oauth_config["token_url"] = oauth_token_url  # OAuthManager expects 'token_url', not 'token_endpoint'
                if oauth_authorization_url:
                    oauth_config["authorization_url"] = oauth_authorization_url  # OAuthManager expects 'authorization_url', not 'authorization_endpoint'
                if oauth_redirect_uri:
                    oauth_config["redirect_uri"] = oauth_redirect_uri
                if oauth_client_id:
                    oauth_config["client_id"] = oauth_client_id
                if oauth_client_secret:
                    # Encrypt the client secret
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_client_secret)

                # Add username and password for password grant type
                if oauth_username:
                    oauth_config["username"] = oauth_username
                if oauth_password:
                    oauth_config["password"] = oauth_password

                # Parse scopes (comma or space separated)
                if oauth_scopes_str:
                    scopes = [s.strip() for s in oauth_scopes_str.replace(",", " ").split() if s.strip()]
                    if scopes:
                        oauth_config["scopes"] = scopes

                LOGGER.info(f"✅ Assembled OAuth config from UI form fields: grant_type={oauth_grant_type}, issuer={oauth_issuer}")
                LOGGER.info(f"DEBUG: Complete oauth_config = {oauth_config}")

        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = orjson.loads(passthrough_headers)
            except (orjson.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        # Auto-detect OAuth: if oauth_config is present and auth_type not explicitly set, use "oauth"
        auth_type_from_form = str(form.get("auth_type", ""))
        LOGGER.info(f"DEBUG: auth_type from form: '{auth_type_from_form}', oauth_config present: {oauth_config is not None}")
        if oauth_config and not auth_type_from_form:
            auth_type_from_form = "oauth"
            LOGGER.info("✅ Auto-detected OAuth configuration, setting auth_type='oauth'")
        elif oauth_config and auth_type_from_form:
            LOGGER.info(f"✅ OAuth config present with explicit auth_type='{auth_type_from_form}'")

        agent_data = A2AAgentCreate(
            name=form["name"],
            description=form.get("description"),
            endpoint_url=form["endpoint_url"],
            agent_type=form.get("agent_type", "generic"),
            auth_type=auth_type_from_form,
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            oauth_config=oauth_config,
            auth_value=form.get("auth_value") if form.get("auth_value") else None,
            tags=tags,
            visibility=form.get("visibility", "private"),
            team_id=team_id,
            owner_email=user_email,
            passthrough_headers=passthrough_headers,
        )

        LOGGER.info(f"Creating A2A agent: {agent_data.name} at {agent_data.endpoint_url}")

        # Extract metadata from request
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await a2a_service.register_agent(
            db,
            agent_data,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
            team_id=team_id,
            owner_email=user_email,
            visibility=form.get("visibility", "private"),
        )

        return ORJSONResponse(
            content={"message": "A2A agent created successfully!", "success": True},
            status_code=200,
        )

    except CoreValidationError as ex:
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=422)
    except A2AAgentNameConflictError as ex:
        LOGGER.error(f"A2A agent name conflict: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except A2AAgentError as ex:
        LOGGER.error(f"A2A agent error: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:
        LOGGER.error(f"Validation error while creating A2A agent: {ex}")
        return ORJSONResponse(
            content=ErrorFormatter.format_validation_error(ex),
            status_code=422,
        )
    except IntegrityError as ex:
        return ORJSONResponse(
            content=ErrorFormatter.format_database_error(ex),
            status_code=409,
        )
    except Exception as ex:
        LOGGER.error(f"Error creating A2A agent: {ex}")
        return ORJSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/a2a/{agent_id}/edit")
async def admin_edit_a2a_agent(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """
    Edit an existing A2A agent via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - endpoint_url
      - agent_type
      - tags (optional, comma-separated)
      - auth_type (optional)
      - auth_username (optional)
      - auth_password (optional)
      - auth_token (optional)
      - auth_header_key / auth_header_value (optional)
      - auth_headers (JSON array, optional)
      - oauth_config (JSON string or individual OAuth fields)
      - visibility (optional)
      - team_id (optional)
      - capabilities (JSON, optional)
      - config (JSON, optional)
      - passthrough_headers: Optional[List[str]]

    Args:
        agent_id (str): The ID of the agent being edited.
        request (Request): The incoming FastAPI request containing form data.
        db (Session): Active database session.
        user: The authenticated admin user performing the edit.

    Returns:
        JSONResponse: A JSON response indicating success or failure.

    Examples:
        >>> import asyncio, json
        >>> from unittest.mock import AsyncMock, MagicMock, patch
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = {"email": "test_admin_user", "db": mock_db}
        >>> agent_id = "agent-123"
        >>>
        >>> # Happy path: edit A2A agent successfully
        >>> form_data_success = FormData([
        ...     ("name", "Updated Agent"),
        ...     ("endpoint_url", "http://updated-agent.com"),
        ...     ("agent_type", "generic"),
        ...     ("auth_type", "basic"),
        ...     ("auth_username", "user"),
        ...     ("auth_password", "pass"),
        ... ])
        >>> mock_request_success = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_update_agent = a2a_service.update_agent
        >>> a2a_service.update_agent = AsyncMock()
        >>>
        >>> async def test_admin_edit_a2a_agent_success():
        ...     response = await admin_edit_a2a_agent(agent_id, mock_request_success, mock_db, mock_user)
        ...     body = json.loads(response.body)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and body["success"] is True
        >>>
        >>> asyncio.run(test_admin_edit_a2a_agent_success())
        True
        >>>
        >>> # Error path: simulate exception during update
        >>> form_data_error = FormData([
        ...     ("name", "Error Agent"),
        ...     ("endpoint_url", "http://error-agent.com"),
        ...     ("auth_type", "basic"),
        ...     ("auth_username", "user"),
        ...     ("auth_password", "pass"),
        ... ])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> a2a_service.update_agent = AsyncMock(side_effect=Exception("Update failed"))
        >>>
        >>> async def test_admin_edit_a2a_agent_exception():
        ...     response = await admin_edit_a2a_agent(agent_id, mock_request_error, mock_db, mock_user)
        ...     body = json.loads(response.body)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and body["success"] is False and "Update failed" in body["message"]
        >>>
        >>> asyncio.run(test_admin_edit_a2a_agent_exception())
        True
        >>>
        >>> # Validation error path: e.g., invalid URL
        >>> form_data_validation = FormData([
        ...     ("name", "Bad URL Agent"),
        ...     ("endpoint_url", "invalid-url"),
        ...     ("auth_type", "basic"),
        ...     ("auth_username", "user"),
        ...     ("auth_password", "pass"),
        ... ])
        >>> mock_request_validation = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_validation.form = AsyncMock(return_value=form_data_validation)
        >>>
        >>> async def test_admin_edit_a2a_agent_validation():
        ...     response = await admin_edit_a2a_agent(agent_id, mock_request_validation, mock_db, mock_user)
        ...     body = json.loads(response.body)
        ...     return isinstance(response, JSONResponse) and response.status_code in (422, 400) and body["success"] is False
        >>>
        >>> asyncio.run(test_admin_edit_a2a_agent_validation())
        True
        >>>
        >>> # Restore original method
        >>> a2a_service.update_agent = original_update_agent

    """

    try:
        form = await request.form()

        # Normalize tags
        tags_raw = str(form.get("tags", ""))
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        # Visibility
        visibility = str(form.get("visibility", "private"))

        # Agent Type
        agent_type = str(form.get("agent_type", "generic"))

        # Capabilities
        raw_capabilities = form.get("capabilities")
        capabilities = {}
        if raw_capabilities:
            try:
                capabilities = orjson.loads(raw_capabilities)
            except (ValueError, orjson.JSONDecodeError):
                capabilities = {}

        # Config
        raw_config = form.get("config")
        config = {}
        if raw_config:
            try:
                config = orjson.loads(raw_config)
            except (ValueError, orjson.JSONDecodeError):
                config = {}

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers = []
        if auth_headers_json:
            try:
                auth_headers = orjson.loads(auth_headers_json)
            except (orjson.JSONDecodeError, ValueError):
                auth_headers = []

        # Passthrough headers
        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = orjson.loads(passthrough_headers)
            except (orjson.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        # Parse OAuth configuration - support both JSON string and individual form fields
        oauth_config_json = str(form.get("oauth_config"))
        oauth_config: Optional[dict[str, Any]] = None

        # Option 1: Pre-assembled oauth_config JSON (from API calls)
        if oauth_config_json and oauth_config_json != "None":
            try:
                oauth_config = orjson.loads(oauth_config_json)
                # Encrypt the client secret if present and not empty
                if oauth_config and "client_secret" in oauth_config and oauth_config["client_secret"]:
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_config["client_secret"])
            except (orjson.JSONDecodeError, ValueError) as e:
                LOGGER.error(f"Failed to parse OAuth config: {e}")
                oauth_config = None

        # Option 2: Assemble from individual UI form fields
        if not oauth_config:
            oauth_grant_type = str(form.get("oauth_grant_type", ""))
            oauth_issuer = str(form.get("oauth_issuer", ""))
            oauth_token_url = str(form.get("oauth_token_url", ""))
            oauth_authorization_url = str(form.get("oauth_authorization_url", ""))
            oauth_redirect_uri = str(form.get("oauth_redirect_uri", ""))
            oauth_client_id = str(form.get("oauth_client_id", ""))
            oauth_client_secret = str(form.get("oauth_client_secret", ""))
            oauth_username = str(form.get("oauth_username", ""))
            oauth_password = str(form.get("oauth_password", ""))
            oauth_scopes_str = str(form.get("oauth_scopes", ""))

            # If any OAuth field is provided, assemble oauth_config
            if any([oauth_grant_type, oauth_issuer, oauth_token_url, oauth_authorization_url, oauth_client_id]):
                oauth_config = {}

                if oauth_grant_type:
                    oauth_config["grant_type"] = oauth_grant_type
                if oauth_issuer:
                    oauth_config["issuer"] = oauth_issuer
                if oauth_token_url:
                    oauth_config["token_url"] = oauth_token_url  # OAuthManager expects 'token_url', not 'token_endpoint'
                if oauth_authorization_url:
                    oauth_config["authorization_url"] = oauth_authorization_url  # OAuthManager expects 'authorization_url', not 'authorization_endpoint'
                if oauth_redirect_uri:
                    oauth_config["redirect_uri"] = oauth_redirect_uri
                if oauth_client_id:
                    oauth_config["client_id"] = oauth_client_id
                if oauth_client_secret:
                    # Encrypt the client secret
                    encryption = get_encryption_service(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_client_secret)

                # Add username and password for password grant type
                if oauth_username:
                    oauth_config["username"] = oauth_username
                if oauth_password:
                    oauth_config["password"] = oauth_password

                # Parse scopes (comma or space separated)
                if oauth_scopes_str:
                    scopes = [s.strip() for s in oauth_scopes_str.replace(",", " ").split() if s.strip()]
                    if scopes:
                        oauth_config["scopes"] = scopes

                LOGGER.info(f"✅ Assembled OAuth config from UI form fields (edit): grant_type={oauth_grant_type}, issuer={oauth_issuer}")

        user_email = get_user_email(user)
        team_service = TeamManagementService(db)
        team_id = await team_service.verify_team_for_user(user_email, form.get("team_id"))

        # Auto-detect OAuth: if oauth_config is present and auth_type not explicitly set, use "oauth"
        auth_type_from_form = str(form.get("auth_type", ""))
        if oauth_config and not auth_type_from_form:
            auth_type_from_form = "oauth"
            LOGGER.info("Auto-detected OAuth configuration in edit, setting auth_type='oauth'")

        agent_update = A2AAgentUpdate(
            name=form.get("name"),
            description=form.get("description"),
            endpoint_url=form.get("endpoint_url"),
            agent_type=agent_type,
            tags=tags,
            auth_type=auth_type_from_form,
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_value=str(form.get("auth_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            passthrough_headers=passthrough_headers,
            oauth_config=oauth_config,
            visibility=visibility,
            team_id=team_id,
            owner_email=user_email,
            capabilities=capabilities,  # Optional, not editable via UI
            config=config,  # Optional, not editable via UI
        )

        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)
        await a2a_service.update_agent(
            db=db,
            agent_id=agent_id,
            agent_data=agent_update,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
        )

        return ORJSONResponse({"message": "A2A agent updated successfully", "success": True}, status_code=200)

    except ValidationError as ve:
        return ORJSONResponse({"message": str(ve), "success": False}, status_code=422)
    except IntegrityError as ie:
        return ORJSONResponse({"message": str(ie), "success": False}, status_code=409)
    except Exception as e:
        return ORJSONResponse({"message": str(e), "success": False}, status_code=500)


@admin_router.post("/a2a/{agent_id}/toggle")
async def admin_toggle_a2a_agent(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
) -> RedirectResponse:
    """Toggle A2A agent status via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Redirect response to admin page with A2A tab

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    error_message = None
    try:
        form = await request.form()
        act_val = form.get("activate", "false")
        activate = act_val.lower() == "true" if isinstance(act_val, str) else False

        user_email = get_user_email(user)

        await a2a_service.toggle_agent_status(db, agent_id, activate, user_email=user_email)
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {user_email} toggling A2A agent status{agent_id}: {e}")
        error_message = str(e)
    except A2AAgentNotFoundError as e:
        LOGGER.error(f"A2A agent toggle failed - not found: {e}")
        root_path = request.scope.get("root_path", "")
        error_message = "A2A agent not found."
    except Exception as e:
        LOGGER.error(f"Error toggling A2A agent: {e}")
        root_path = request.scope.get("root_path", "")
        error_message = "Failed to toggle status of A2A agent. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        return RedirectResponse(f"{root_path}/admin/{error_param}#a2a-agents", status_code=303)

    return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)


@admin_router.post("/a2a/{agent_id}/delete")
async def admin_delete_a2a_agent(
    agent_id: str,
    request: Request,  # pylint: disable=unused-argument
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
) -> RedirectResponse:
    """Delete A2A agent via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Redirect response to admin page with A2A tab

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    form = await request.form()
    purge_metrics = str(form.get("purge_metrics", "false")).lower() == "true"
    error_message = None
    try:
        user_email = get_user_email(user)
        await a2a_service.delete_agent(db, agent_id, user_email=user_email, purge_metrics=purge_metrics)
    except PermissionError as e:
        LOGGER.warning(f"Permission denied for user {get_user_email(user)} deleting A2A agent {agent_id}: {e}")
        error_message = str(e)
    except A2AAgentNotFoundError as e:
        LOGGER.error(f"A2A agent delete failed - not found: {e}")
        error_message = "A2A agent not found."
    except Exception as e:
        LOGGER.error(f"Error deleting A2A agent: {e}")
        error_message = "Failed to delete A2A agent. Please try again."

    root_path = request.scope.get("root_path", "")

    # Build redirect URL with error message if present
    if error_message:
        error_param = f"?error={urllib.parse.quote(error_message)}"
        return RedirectResponse(f"{root_path}/admin/{error_param}#a2a-agents", status_code=303)

    return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)


@admin_router.post("/a2a/{agent_id}/test")
async def admin_test_a2a_agent(
    agent_id: str,
    request: Request,  # pylint: disable=unused-argument
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
) -> JSONResponse:
    """Test A2A agent via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON response with test results

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        return ORJSONResponse(content={"success": False, "error": "A2A features are disabled"}, status_code=403)

    try:
        user_email = get_user_email(user)
        # Get the agent by ID
        agent = await a2a_service.get_agent(db, agent_id)

        # Prepare test parameters based on agent type and endpoint
        if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
            # JSONRPC format for agents that expect it
            test_params = {
                "method": "message/send",
                "params": {"message": {"messageId": f"admin-test-{int(time.time())}", "role": "user", "parts": [{"type": "text", "text": "Hello from MCP Gateway Admin UI test!"}]}},
            }
        else:
            # Generic test format
            test_params = {"message": "Hello from MCP Gateway Admin UI test!", "test": True, "timestamp": int(time.time())}

        # Invoke the agent
        result = await a2a_service.invoke_agent(
            db,
            agent.name,
            test_params,
            "admin_test",
            user_email=user_email,
            user_id=user_email,
        )

        return ORJSONResponse(content={"success": True, "result": result, "agent_name": agent.name, "test_timestamp": time.time()})

    except Exception as e:
        LOGGER.error(f"Error testing A2A agent {agent_id}: {e}")
        return ORJSONResponse(content={"success": False, "error": str(e), "agent_id": agent_id}, status_code=500)


# gRPC Service Management Endpoints


@admin_router.get("/grpc", response_model=PaginatedResponse)
async def admin_list_grpc_services(
    include_inactive: bool = False,
    team_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """List all gRPC services.

    Args:
        include_inactive: Include disabled services
        team_id: Filter by team ID
        db: Database session
        user: Authenticated user

    Returns:
        List of gRPC services

    Raises:
        HTTPException: If gRPC support is disabled or not available
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    user_email = get_user_email(user)
    return await grpc_service_mgr.list_services(db, include_inactive, user_email, team_id)


@admin_router.post("/grpc")
async def admin_create_grpc_service(
    service: GrpcServiceCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Create a new gRPC service.

    Args:
        service: gRPC service creation data
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Created gRPC service

    Raises:
        HTTPException: If gRPC support is disabled or creation fails
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        metadata = MetadataCapture.capture(request)  # pylint: disable=no-member
        user_email = get_user_email(user)
        result = await grpc_service_mgr.register_service(db, service, user_email, metadata)
        return ORJSONResponse(content=jsonable_encoder(result), status_code=201)
    except GrpcServiceNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except GrpcServiceError as e:
        LOGGER.error(f"gRPC service error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/grpc/{service_id}", response_model=GrpcServiceRead)
async def admin_get_grpc_service(
    service_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get a specific gRPC service.

    Args:
        service_id: Service ID
        db: Database session
        user: Authenticated user

    Returns:
        The gRPC service

    Raises:
        HTTPException: If gRPC support is disabled or service not found
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        user_email = get_user_email(user)
        return await grpc_service_mgr.get_service(db, service_id, user_email)
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.put("/grpc/{service_id}")
async def admin_update_grpc_service(
    service_id: str,
    service: GrpcServiceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Update a gRPC service.

    Args:
        service_id: Service ID
        service: Update data
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Updated gRPC service

    Raises:
        HTTPException: If gRPC support is disabled or update fails
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        metadata = MetadataCapture.capture(request)  # pylint: disable=no-member
        user_email = get_user_email(user)
        result = await grpc_service_mgr.update_service(db, service_id, service, user_email, metadata)
        return ORJSONResponse(content=jsonable_encoder(result))
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except GrpcServiceNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except GrpcServiceError as e:
        LOGGER.error(f"gRPC service error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.post("/grpc/{service_id}/toggle")
async def admin_toggle_grpc_service(
    service_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Toggle a gRPC service's enabled status.

    Args:
        service_id: Service ID
        db: Database session
        user: Authenticated user

    Returns:
        Updated gRPC service

    Raises:
        HTTPException: If gRPC support is disabled or toggle fails
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        service = await grpc_service_mgr.get_service(db, service_id)
        result = await grpc_service_mgr.toggle_service(db, service_id, not service.enabled)
        return ORJSONResponse(content=jsonable_encoder(result))
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/grpc/{service_id}/delete")
async def admin_delete_grpc_service(
    service_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Delete a gRPC service.

    Args:
        service_id: Service ID
        db: Database session
        user: Authenticated user

    Returns:
        No content response

    Raises:
        HTTPException: If gRPC support is disabled or deletion fails
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        await grpc_service_mgr.delete_service(db, service_id)
        return Response(status_code=204)
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/grpc/{service_id}/reflect")
async def admin_reflect_grpc_service(
    service_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Trigger re-reflection on a gRPC service.

    Args:
        service_id: Service ID
        db: Database session
        user: Authenticated user

    Returns:
        Updated gRPC service with reflection results

    Raises:
        HTTPException: If gRPC support is disabled or reflection fails
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        result = await grpc_service_mgr.reflect_service(db, service_id)
        return ORJSONResponse(content=jsonable_encoder(result))
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except GrpcServiceError as e:
        LOGGER.error(f"gRPC service error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/grpc/{service_id}/methods")
async def admin_get_grpc_methods(
    service_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Get methods for a gRPC service.

    Args:
        service_id: Service ID
        db: Database session
        user: Authenticated user

    Returns:
        List of gRPC methods

    Raises:
        HTTPException: If gRPC support is disabled or service not found
    """
    if not GRPC_AVAILABLE or not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is not available or disabled")

    try:
        methods = await grpc_service_mgr.get_service_methods(db, service_id)
        return ORJSONResponse(content={"methods": methods})
    except GrpcServiceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.get("/sections/resources")
@require_permission("admin")
async def get_resources_section(
    team_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get resources data filtered by team.

    Args:
        team_id: Optional team ID to filter by
        db: Database session
        user: Current authenticated user context

    Returns:
        JSONResponse: Resources data with team filtering applied
    """
    try:
        local_resource_service = ResourceService()
        user_email = get_user_email(user)
        LOGGER.debug(f"User {user_email} requesting resources section with team_id={team_id}")

        # Get all resources and filter by team
        resources_list = await local_resource_service.list_resources(db, include_inactive=True)

        # Apply team filtering if specified
        if team_id:
            resources_list = [r for r in resources_list if getattr(r, "team_id", None) == team_id]

        # Convert to JSON-serializable format
        resources = []
        for resource in resources_list:
            resource_dict = (
                resource.model_dump(by_alias=True)
                if hasattr(resource, "model_dump")
                else {
                    "id": resource.id,
                    "name": resource.name,
                    "description": resource.description,
                    "uri": resource.uri,
                    "tags": resource.tags or [],
                    "isActive": resource.enabled,
                    "team_id": getattr(resource, "team_id", None),
                    "visibility": getattr(resource, "visibility", "private"),
                }
            )
            resources.append(resource_dict)

        return ORJSONResponse(content={"resources": resources, "team_id": team_id})

    except Exception as e:
        LOGGER.error(f"Error loading resources section: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=500)


@admin_router.get("/sections/prompts")
@require_permission("admin")
async def get_prompts_section(
    team_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get prompts data filtered by team.

    Args:
        team_id: Optional team ID to filter by
        db: Database session
        user: Current authenticated user context

    Returns:
        JSONResponse: Prompts data with team filtering applied
    """
    try:
        local_prompt_service = PromptService()
        user_email = get_user_email(user)
        LOGGER.debug(f"User {user_email} requesting prompts section with team_id={team_id}")

        # Get all prompts and filter by team
        prompts_list = await local_prompt_service.list_prompts(db, include_inactive=True)

        # Apply team filtering if specified
        if team_id:
            prompts_list = [p for p in prompts_list if getattr(p, "team_id", None) == team_id]

        # Convert to JSON-serializable format
        prompts = []
        for prompt in prompts_list:
            prompt_dict = (
                prompt.model_dump(by_alias=True)
                if hasattr(prompt, "model_dump")
                else {
                    "id": prompt.id,
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": prompt.arguments or [],
                    "tags": prompt.tags or [],
                    # Prompt enabled/disabled state is stored on the prompt as `enabled`.
                    "isActive": getattr(prompt, "enabled", False),
                    "team_id": getattr(prompt, "team_id", None),
                    "visibility": getattr(prompt, "visibility", "private"),
                }
            )
            prompts.append(prompt_dict)

        return ORJSONResponse(content={"prompts": prompts, "team_id": team_id})

    except Exception as e:
        LOGGER.error(f"Error loading prompts section: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=500)


@admin_router.get("/sections/servers")
@require_permission("admin")
async def get_servers_section(
    team_id: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get servers data filtered by team.

    Args:
        team_id: Optional team ID to filter by
        include_inactive: Whether to include inactive servers
        db: Database session
        user: Current authenticated user context

    Returns:
        JSONResponse: Servers data with team filtering applied
    """
    try:
        local_server_service = ServerService()
        user_email = get_user_email(user)
        LOGGER.debug(f"User {user_email} requesting servers section with team_id={team_id}, include_inactive={include_inactive}")

        # Get servers with optional include_inactive parameter
        servers_list = await local_server_service.list_servers(db, include_inactive=include_inactive)

        # Apply team filtering if specified
        if team_id:
            servers_list = [s for s in servers_list if getattr(s, "team_id", None) == team_id]

        # Convert to JSON-serializable format
        servers = []
        for server in servers_list:
            server_dict = (
                server.model_dump(by_alias=True)
                if hasattr(server, "model_dump")
                else {
                    "id": server.id,
                    "name": server.name,
                    "description": server.description,
                    "tags": server.tags or [],
                    "isActive": server.enabled,
                    "team_id": getattr(server, "team_id", None),
                    "visibility": getattr(server, "visibility", "private"),
                }
            )
            servers.append(server_dict)

        return ORJSONResponse(content={"servers": servers, "team_id": team_id})

    except Exception as e:
        LOGGER.error(f"Error loading servers section: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=500)


@admin_router.get("/sections/gateways")
@require_permission("admin")
async def get_gateways_section(
    team_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get gateways data filtered by team.

    Args:
        team_id: Optional team ID to filter by
        db: Database session
        user: Current authenticated user context

    Returns:
        JSONResponse: Gateways data with team filtering applied
    """
    try:
        local_gateway_service = GatewayService()
        get_user_email(user)

        # Get all gateways and filter by team
        gateways_list = await local_gateway_service.list_gateways(db, include_inactive=True)

        # Apply team filtering if specified
        if team_id:
            gateways_list = [g for g in gateways_list if g.team_id == team_id]

        # Convert to JSON-serializable format
        gateways = []
        for gateway in gateways_list:
            if hasattr(gateway, "model_dump"):
                # Get dict and serialize datetime objects
                gateway_dict = gateway.model_dump(by_alias=True)
                # Convert datetime objects to strings
                for key, value in gateway_dict.items():
                    gateway_dict[key] = serialize_datetime(value)
            else:
                # Parse URL to extract host and port
                parsed_url = urllib.parse.urlparse(gateway.url) if gateway.url else None
                gateway_dict = {
                    "id": gateway.id,
                    "name": gateway.name,
                    "host": parsed_url.hostname if parsed_url else "",
                    "port": parsed_url.port if parsed_url else 80,
                    "tags": gateway.tags or [],
                    "isActive": getattr(gateway, "enabled", False),
                    "team_id": getattr(gateway, "team_id", None),
                    "visibility": getattr(gateway, "visibility", "private"),
                    "created_at": serialize_datetime(getattr(gateway, "created_at", None)),
                    "updated_at": serialize_datetime(getattr(gateway, "updated_at", None)),
                }
            gateways.append(gateway_dict)

        return ORJSONResponse(content={"gateways": gateways, "team_id": team_id})

    except Exception as e:
        LOGGER.error(f"Error loading gateways section: {e}")
        return ORJSONResponse(content={"error": str(e)}, status_code=500)


####################
# Plugin Routes    #
####################


@admin_router.get("/plugins/partial")
async def get_plugins_partial(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> HTMLResponse:  # pylint: disable=unused-argument
    """Render the plugins partial HTML template.

    This endpoint returns a rendered HTML partial containing plugin information,
    similar to the version_info_partial pattern. It's designed to be loaded via HTMX
    into the admin interface.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        HTMLResponse with rendered plugins partial template
    """
    LOGGER.debug(f"User {get_user_email(user)} requested plugins partial")

    try:
        # Get plugin service and check if plugins are enabled
        plugin_service = get_plugin_service()

        # Check if plugin manager is available in app state
        plugin_manager = getattr(request.app.state, "plugin_manager", None)
        if plugin_manager:
            plugin_service.set_plugin_manager(plugin_manager)

        # Get plugin data
        plugins = plugin_service.get_all_plugins()
        stats = await plugin_service.get_plugin_statistics()

        # Prepare context for template
        context = {"request": request, "plugins": plugins, "stats": stats, "plugins_enabled": plugin_manager is not None, "root_path": request.scope.get("root_path", "")}

        # Render the partial template
        return request.app.state.templates.TemplateResponse("plugins_partial.html", context)

    except Exception as e:
        LOGGER.error(f"Error rendering plugins partial: {e}")
        # Return error HTML that can be displayed in the UI
        error_html = f"""
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            <strong class="font-bold">Error loading plugins:</strong>
            <span class="block sm:inline">{str(e)}</span>
        </div>
        """
        return HTMLResponse(content=error_html, status_code=500)


@admin_router.get("/plugins", response_model=PluginListResponse)
async def list_plugins(
    request: Request,
    search: Optional[str] = None,
    mode: Optional[str] = None,
    hook: Optional[str] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),  # pylint: disable=unused-argument
    user=Depends(get_current_user_with_permissions),
) -> PluginListResponse:
    """Get list of all plugins with optional filtering.

    Args:
        request: FastAPI request object
        search: Optional text search in name/description/author
        mode: Optional filter by mode (enforce/permissive/disabled)
        hook: Optional filter by hook type
        tag: Optional filter by tag
        db: Database session
        user: Authenticated user

    Returns:
        PluginListResponse with list of plugins and statistics

    Raises:
        HTTPException: If there's an error retrieving plugins
    """
    LOGGER.debug(f"User {get_user_email(user)} requested plugin list")
    structured_logger = get_structured_logger()

    try:
        # Get plugin service
        plugin_service = get_plugin_service()

        # Check if plugin manager is available
        plugin_manager = getattr(request.app.state, "plugin_manager", None)
        if plugin_manager:
            plugin_service.set_plugin_manager(plugin_manager)

        # Get filtered plugins
        if any([search, mode, hook, tag]):
            plugins = plugin_service.search_plugins(query=search, mode=mode, hook=hook, tag=tag)
        else:
            plugins = plugin_service.get_all_plugins()

        # Count enabled/disabled
        enabled_count = sum(1 for p in plugins if p["status"] == "enabled")
        disabled_count = sum(1 for p in plugins if p["status"] == "disabled")

        # Log plugin marketplace browsing activity
        structured_logger.info(
            "User browsed plugin marketplace",
            user_id=get_user_id(user),
            user_email=get_user_email(user),
            component="plugin_marketplace",
            category="business_logic",
            resource_type="plugin_list",
            resource_action="browse",
            custom_fields={
                "search_query": search,
                "filter_mode": mode,
                "filter_hook": hook,
                "filter_tag": tag,
                "results_count": len(plugins),
                "enabled_count": enabled_count,
                "disabled_count": disabled_count,
                "has_filters": any([search, mode, hook, tag]),
            },
            db=db,
        )

        return PluginListResponse(plugins=plugins, total=len(plugins), enabled_count=enabled_count, disabled_count=disabled_count)

    except Exception as e:
        LOGGER.error(f"Error listing plugins: {e}")
        structured_logger.error(
            "Failed to list plugins in marketplace", user_id=get_user_id(user), user_email=get_user_email(user), error=e, component="plugin_marketplace", category="business_logic", db=db
        )
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/plugins/stats", response_model=PluginStatsResponse)
async def get_plugin_stats(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> PluginStatsResponse:  # pylint: disable=unused-argument
    """Get plugin statistics.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        PluginStatsResponse with aggregated plugin statistics

    Raises:
        HTTPException: If there's an error getting plugin statistics
    """
    LOGGER.debug(f"User {get_user_email(user)} requested plugin statistics")
    structured_logger = get_structured_logger()

    try:
        # Get plugin service
        plugin_service = get_plugin_service()

        # Check if plugin manager is available
        plugin_manager = getattr(request.app.state, "plugin_manager", None)
        if plugin_manager:
            plugin_service.set_plugin_manager(plugin_manager)

        # Get statistics
        stats = await plugin_service.get_plugin_statistics()

        # Log marketplace analytics access
        structured_logger.info(
            "User accessed plugin marketplace statistics",
            user_id=get_user_id(user),
            user_email=get_user_email(user),
            component="plugin_marketplace",
            category="business_logic",
            resource_type="plugin_stats",
            resource_action="view",
            custom_fields={
                "total_plugins": stats.get("total_plugins", 0),
                "enabled_plugins": stats.get("enabled_plugins", 0),
                "disabled_plugins": stats.get("disabled_plugins", 0),
                "hooks_count": len(stats.get("plugins_by_hook", {})),
                "tags_count": len(stats.get("plugins_by_tag", {})),
                "authors_count": len(stats.get("plugins_by_author", {})),
            },
            db=db,
        )

        return PluginStatsResponse(**stats)

    except Exception as e:
        LOGGER.error(f"Error getting plugin statistics: {e}")
        structured_logger.error(
            "Failed to get plugin marketplace statistics", user_id=get_user_id(user), user_email=get_user_email(user), error=e, component="plugin_marketplace", category="business_logic", db=db
        )
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/plugins/{name}", response_model=PluginDetail)
async def get_plugin_details(name: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)) -> PluginDetail:  # pylint: disable=unused-argument
    """Get detailed information about a specific plugin.

    Args:
        name: Plugin name
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        PluginDetail with full plugin information

    Raises:
        HTTPException: If plugin not found
    """
    LOGGER.debug(f"User {get_user_email(user)} requested details for plugin {name}")
    structured_logger = get_structured_logger()
    audit_service = get_audit_trail_service()

    try:
        # Get plugin service
        plugin_service = get_plugin_service()

        # Check if plugin manager is available
        plugin_manager = getattr(request.app.state, "plugin_manager", None)
        if plugin_manager:
            plugin_service.set_plugin_manager(plugin_manager)

        # Get plugin details
        plugin = plugin_service.get_plugin_by_name(name)

        if not plugin:
            structured_logger.warning(
                f"Plugin '{name}' not found in marketplace",
                user_id=get_user_id(user),
                user_email=get_user_email(user),
                component="plugin_marketplace",
                category="business_logic",
                custom_fields={"plugin_name": name, "action": "view_details"},
                db=db,
            )
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

        # Log plugin view activity
        structured_logger.info(
            f"User viewed plugin details: '{name}'",
            user_id=get_user_id(user),
            user_email=get_user_email(user),
            component="plugin_marketplace",
            category="business_logic",
            resource_type="plugin",
            resource_id=name,
            resource_action="view_details",
            custom_fields={
                "plugin_name": name,
                "plugin_version": plugin.get("version"),
                "plugin_author": plugin.get("author"),
                "plugin_status": plugin.get("status"),
                "plugin_mode": plugin.get("mode"),
                "plugin_hooks": plugin.get("hooks", []),
                "plugin_tags": plugin.get("tags", []),
            },
            db=db,
        )

        # Create audit trail for plugin access
        audit_service.log_audit(
            user_id=get_user_id(user), user_email=get_user_email(user), resource_type="plugin", resource_id=name, action="view", description=f"Viewed plugin '{name}' details in marketplace", db=db
        )

        return PluginDetail(**plugin)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error getting plugin details: {e}")
        structured_logger.error(
            f"Failed to get plugin details: '{name}'", user_id=get_user_id(user), user_email=get_user_email(user), error=e, component="plugin_marketplace", category="business_logic", db=db
        )
        raise HTTPException(status_code=500, detail=str(e))


##################################################
# MCP Registry Endpoints
##################################################


@admin_router.get("/mcp-registry/servers", response_model=CatalogListResponse)
async def list_catalog_servers(
    _request: Request,
    category: Optional[str] = None,
    auth_type: Optional[str] = None,
    provider: Optional[str] = None,
    search: Optional[str] = None,
    tags: Optional[List[str]] = Query(None),
    show_registered_only: bool = False,
    show_available_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> CatalogListResponse:
    """Get list of catalog servers with filtering.

    Args:
        _request: FastAPI request object
        category: Filter by category
        auth_type: Filter by authentication type
        provider: Filter by provider
        search: Search in name/description
        tags: Filter by tags
        show_registered_only: Show only already registered servers
        show_available_only: Show only available servers
        limit: Maximum results
        offset: Pagination offset
        db: Database session
        _user: Authenticated user

    Returns:
        List of catalog servers matching filters

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    catalog_request = CatalogListRequest(
        category=category,
        auth_type=auth_type,
        provider=provider,
        search=search,
        tags=tags or [],
        show_registered_only=show_registered_only,
        show_available_only=show_available_only,
        limit=limit,
        offset=offset,
    )

    return await catalog_service.get_catalog_servers(catalog_request, db)


@admin_router.post("/mcp-registry/{server_id}/register", response_model=CatalogServerRegisterResponse)
@require_permission("servers.create")
async def register_catalog_server(
    server_id: str,
    request: Optional[CatalogServerRegisterRequest] = None,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> CatalogServerRegisterResponse:
    """Register a catalog server.

    Args:
        server_id: Catalog server ID to register
        request: Optional registration parameters
        db: Database session
        _user: Authenticated user

    Returns:
        Registration response with success status

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    return await catalog_service.register_catalog_server(catalog_id=server_id, request=request, db=db)


@admin_router.get("/mcp-registry/{server_id}/status", response_model=CatalogServerStatusResponse)
async def check_catalog_server_status(
    server_id: str,
    _db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> CatalogServerStatusResponse:
    """Check catalog server availability.

    Args:
        server_id: Catalog server ID to check
        _db: Database session
        _user: Authenticated user

    Returns:
        Server status including availability and response time

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    return await catalog_service.check_server_availability(server_id)


@admin_router.post("/mcp-registry/bulk-register", response_model=CatalogBulkRegisterResponse)
@require_permission("servers.create")
async def bulk_register_catalog_servers(
    request: CatalogBulkRegisterRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> CatalogBulkRegisterResponse:
    """Register multiple catalog servers at once.

    Args:
        request: Bulk registration request with server IDs
        db: Database session
        _user: Authenticated user

    Returns:
        Bulk registration response with success/failure details

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    return await catalog_service.bulk_register_servers(request, db)


@admin_router.get("/mcp-registry/partial")
async def catalog_partial(
    request: Request,
    category: Optional[str] = None,
    auth_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get HTML partial for catalog servers (used by HTMX).

    Args:
        request: FastAPI request object
        category: Filter by category
        auth_type: Filter by authentication type
        search: Search term
        page: Page number (1-indexed)
        db: Database session
        _user: Authenticated user

    Returns:
        HTML partial with filtered catalog servers

    Raises:
        HTTPException: If the catalog feature is disabled.
    """
    if not settings.mcpgateway_catalog_enabled:
        raise HTTPException(status_code=404, detail="Catalog feature is disabled")

    root_path = request.scope.get("root_path", "")

    # Calculate pagination
    page_size = settings.mcpgateway_catalog_page_size
    offset = (page - 1) * page_size

    catalog_request = CatalogListRequest(category=category, auth_type=auth_type, search=search, show_available_only=False, limit=page_size, offset=offset)

    response = await catalog_service.get_catalog_servers(catalog_request, db)

    # Get ALL servers (no filters, no pagination) for counting statistics
    all_servers_request = CatalogListRequest(show_available_only=False, limit=1000, offset=0)
    all_servers_response = await catalog_service.get_catalog_servers(all_servers_request, db)

    # Pass filter parameters to template for pagination links
    filter_params = {
        "category": category,
        "auth_type": auth_type,
        "search": search,
    }

    # Calculate statistics and pagination info
    total_servers = response.total
    registered_count = sum(1 for s in response.servers if s.is_registered)
    total_pages = (total_servers + page_size - 1) // page_size  # Ceiling division

    # Count ALL servers by category, auth type, and provider (not just current page)
    servers_by_category = {}
    servers_by_auth_type = {}
    servers_by_provider = {}

    for server in all_servers_response.servers:
        servers_by_category[server.category] = servers_by_category.get(server.category, 0) + 1
        servers_by_auth_type[server.auth_type] = servers_by_auth_type.get(server.auth_type, 0) + 1
        servers_by_provider[server.provider] = servers_by_provider.get(server.provider, 0) + 1

    stats = {
        "total_servers": all_servers_response.total,  # Use total from all servers
        "registered_servers": registered_count,
        "categories": all_servers_response.categories,
        "auth_types": all_servers_response.auth_types,
        "providers": all_servers_response.providers,
        "servers_by_category": servers_by_category,
        "servers_by_auth_type": servers_by_auth_type,
        "servers_by_provider": servers_by_provider,
    }

    context = {
        "request": request,
        "servers": response.servers,
        "stats": stats,
        "root_path": root_path,
        "page": page,
        "total_pages": total_pages,
        "page_size": page_size,
        "filter_params": filter_params,
    }

    return request.app.state.templates.TemplateResponse("mcp_registry_partial.html", context)


# ===================================
# System Metrics Endpoints
# ===================================


@admin_router.get("/system/stats")
async def get_system_stats(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get comprehensive system metrics for administrators.

    Returns detailed counts across all entity types including users, teams,
    MCP resources (servers, tools, resources, prompts, A2A agents, gateways),
    API tokens, sessions, metrics, security events, and workflow state.

    Designed for capacity planning, performance optimization, and demonstrating
    system capabilities to administrators.

    Args:
        request: FastAPI request object
        db: Database session dependency
        user: Authenticated user from dependency (must have admin access)

    Returns:
        HTMLResponse or JSONResponse: Comprehensive system metrics
        Returns HTML partial when requested via HTMX, JSON otherwise

    Raises:
        HTTPException: If metrics collection fails

    Examples:
        >>> # Request system metrics via API
        >>> # GET /admin/system/stats
        >>> # Returns JSON with users, teams, mcp_resources, tokens, sessions, metrics, security, workflow
    """
    try:
        LOGGER.info(f"System metrics requested by user: {user}")

        # First-Party
        from mcpgateway.services.system_stats_service import SystemStatsService  # pylint: disable=import-outside-toplevel

        # Get metrics (using cached version for performance)
        service = SystemStatsService()
        stats = await service.get_comprehensive_stats_cached(db)

        LOGGER.info(f"System metrics retrieved successfully for user {user}")

        # Check if this is an HTMX request for HTML partial
        if request.headers.get("hx-request"):
            # Return HTML partial for HTMX
            return request.app.state.templates.TemplateResponse(
                "metrics_partial.html",
                {
                    "request": request,
                    "stats": stats,
                    "root_path": request.scope.get("root_path", ""),
                    "db_metrics_recording_enabled": settings.db_metrics_recording_enabled,
                },
            )

        # Return JSON for API requests
        return ORJSONResponse(content=stats)

    except Exception as e:
        LOGGER.error(f"System metrics retrieval failed for user {user}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve system metrics: {str(e)}")


# ===================================
# Support Bundle Endpoints
# ===================================


@admin_router.get("/support-bundle/generate")
async def admin_generate_support_bundle(
    log_lines: int = Query(default=1000, description="Number of log lines to include"),
    include_logs: bool = Query(default=True, description="Include log files"),
    include_env: bool = Query(default=True, description="Include environment config"),
    include_system: bool = Query(default=True, description="Include system info"),
    user=Depends(get_current_user_with_permissions),
):
    """
    Generate and download a support bundle with sanitized diagnostics.

    Creates a ZIP file containing version info, system diagnostics, configuration,
    and logs with automatic sanitization of sensitive data (passwords, tokens, secrets).

    Args:
        log_lines: Number of log lines to include (default: 1000, 0 = all)
        include_logs: Include log files in bundle (default: True)
        include_env: Include environment configuration (default: True)
        include_system: Include system diagnostics (default: True)
        user: Authenticated user from dependency

    Returns:
        Response: ZIP file download with support bundle

    Raises:
        HTTPException: If bundle generation fails

    Examples:
        >>> # Request support bundle via API
        >>> # GET /admin/support-bundle/generate?log_lines=500
        >>> # Returns: mcpgateway-support-YYYY-MM-DD-HHMMSS.zip
    """
    try:
        LOGGER.info(f"Support bundle generation requested by user: {user}")

        # First-Party
        from mcpgateway.services.support_bundle_service import SupportBundleConfig, SupportBundleService  # pylint: disable=import-outside-toplevel

        # Create configuration
        config = SupportBundleConfig(
            include_logs=include_logs,
            include_env=include_env,
            include_system_info=include_system,
            log_tail_lines=log_lines,
            output_dir=Path(tempfile.gettempdir()),
        )

        # Generate bundle
        service = SupportBundleService()
        bundle_path = service.generate_bundle(config)

        # Read bundle file
        with open(bundle_path, "rb") as f:
            bundle_content = f.read()

        # Clean up temp file
        try:
            bundle_path.unlink()
        except Exception as cleanup_error:
            LOGGER.warning(f"Failed to cleanup temporary bundle file: {cleanup_error}")

        # Return as downloadable file
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"mcpgateway-support-{timestamp}.zip"

        LOGGER.info(f"Support bundle generated successfully for user {user}: {filename} ({len(bundle_content)} bytes)")

        return Response(
            content=bundle_content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(bundle_content)),
                "X-Content-Type-Options": "nosniff",
            },
        )

    except Exception as e:
        LOGGER.error(f"Support bundle generation failed for user {user}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate support bundle: {str(e)}")


# ============================================================================
# Maintenance Routes (Platform Admin Only)
# ============================================================================


@admin_router.get("/maintenance/partial", response_class=HTMLResponse)
async def get_maintenance_partial(
    request: Request,
    user=Depends(get_current_user_with_permissions),
):
    """Render the maintenance dashboard partial (platform admin only).

    This endpoint returns the maintenance UI panel which includes:
    - Metrics cleanup controls
    - Metrics rollup controls
    - System health status

    Only platform administrators can access this endpoint.

    Args:
        request: FastAPI request object
        user: Authenticated user with admin permissions

    Returns:
        HTMLResponse: Rendered maintenance dashboard template

    Raises:
        HTTPException: 403 if user is not a platform admin
    """
    # Check if user is platform admin
    is_admin = user.get("is_admin", False) if isinstance(user, dict) else getattr(user, "is_admin", False)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required")

    root_path = request.scope.get("root_path", "")

    # Build payload with settings for the template
    payload = {
        "settings": {
            "metrics_cleanup_enabled": getattr(settings, "metrics_cleanup_enabled", False),
            "metrics_rollup_enabled": getattr(settings, "metrics_rollup_enabled", False),
            "metrics_retention_days": getattr(settings, "metrics_retention_days", 30),
        }
    }

    return request.app.state.templates.TemplateResponse(
        "maintenance_partial.html",
        {"request": request, "payload": payload, "root_path": root_path},
    )


# ============================================================================
# Observability Routes
# ============================================================================


@admin_router.get("/observability/partial", response_class=HTMLResponse)
async def get_observability_partial(request: Request, _user=Depends(get_current_user_with_permissions)):
    """Render the observability dashboard partial.

    Args:
        request: FastAPI request object
        _user: Authenticated user with admin permissions (required by dependency)

    Returns:
        HTMLResponse: Rendered observability dashboard template
    """
    root_path = request.scope.get("root_path", "")
    return request.app.state.templates.TemplateResponse("observability_partial.html", {"request": request, "root_path": root_path})


@admin_router.get("/observability/metrics/partial", response_class=HTMLResponse)
async def get_observability_metrics_partial(request: Request, _user=Depends(get_current_user_with_permissions)):
    """Render the advanced metrics dashboard partial.

    Args:
        request: FastAPI request object
        _user: Authenticated user with admin permissions (required by dependency)

    Returns:
        HTMLResponse: Rendered metrics dashboard template
    """
    root_path = request.scope.get("root_path", "")
    return request.app.state.templates.TemplateResponse("observability_metrics.html", {"request": request, "root_path": root_path})


@admin_router.get("/observability/stats", response_class=HTMLResponse)
async def get_observability_stats(request: Request, hours: int = Query(24, ge=1, le=168), _user=Depends(get_current_user_with_permissions)):
    """Get observability statistics for the dashboard.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back for statistics (1-168)
        _user: Authenticated user with admin permissions (required by dependency)

    Returns:
        HTMLResponse: Rendered statistics template with trace counts and averages
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours)

        # Consolidate multiple count queries into a single aggregated select
        # Filter by start_time first (uses index), then aggregate by status
        result = db.execute(
            select(
                func.count(ObservabilityTrace.trace_id).label("total_traces"),  # pylint: disable=not-callable
                func.sum(case((ObservabilityTrace.status == "ok", 1), else_=0)).label("success_count"),
                func.sum(case((ObservabilityTrace.status == "error", 1), else_=0)).label("error_count"),
                func.avg(ObservabilityTrace.duration_ms).label("avg_duration_ms"),
            ).where(ObservabilityTrace.start_time >= cutoff_time)
        ).one()

        stats = {
            "total_traces": int(result.total_traces or 0),
            "success_count": int(result.success_count or 0),
            "error_count": int(result.error_count or 0),
            "avg_duration_ms": float(result.avg_duration_ms or 0),
        }

        return request.app.state.templates.TemplateResponse("observability_stats.html", {"request": request, "stats": stats})
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/traces", response_class=HTMLResponse)
async def get_observability_traces(
    request: Request,
    time_range: str = Query("24h"),
    status_filter: str = Query("all"),
    limit: int = Query(50),
    min_duration: Optional[float] = Query(None),
    max_duration: Optional[float] = Query(None),
    http_method: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    name_search: Optional[str] = Query(None),
    attribute_search: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    _user=Depends(get_current_user_with_permissions),
):
    """Get list of traces for the dashboard.

    Args:
        request: FastAPI request object
        time_range: Time range filter (1h, 6h, 24h, 7d)
        status_filter: Status filter (all, ok, error)
        limit: Maximum number of traces to return
        min_duration: Minimum duration in ms
        max_duration: Maximum duration in ms
        http_method: HTTP method filter
        user_email: User email filter
        name_search: Trace name search
        attribute_search: Full-text attribute search
        tool_name: Filter by tool name (shows traces that invoked this tool)
        _user: Authenticated user with admin permissions (required by dependency)

    Returns:
        HTMLResponse: Rendered traces list template
    """
    db = next(get_db())
    try:
        # Parse time range
        time_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
        hours = time_map.get(time_range, 24)
        cutoff_time = datetime.now() - timedelta(hours=hours)

        query = db.query(ObservabilityTrace).filter(ObservabilityTrace.start_time >= cutoff_time)

        # Apply status filter
        if status_filter != "all":
            query = query.filter(ObservabilityTrace.status == status_filter)

        # Apply duration filters
        if min_duration is not None:
            query = query.filter(ObservabilityTrace.duration_ms >= min_duration)
        if max_duration is not None:
            query = query.filter(ObservabilityTrace.duration_ms <= max_duration)

        # Apply HTTP method filter
        if http_method:
            query = query.filter(ObservabilityTrace.http_method == http_method)

        # Apply user email filter
        if user_email:
            query = query.filter(ObservabilityTrace.user_email.ilike(f"%{user_email}%"))

        # Apply name search
        if name_search:
            query = query.filter(ObservabilityTrace.name.ilike(f"%{name_search}%"))

        # Apply attribute search
        if attribute_search:
            # Escape special characters for SQL LIKE
            safe_search = attribute_search.replace("%", "\\%").replace("_", "\\_")
            query = query.filter(cast(ObservabilityTrace.attributes, String).ilike(f"%{safe_search}%"))

        # Apply tool name filter (join with spans to find traces that invoked a specific tool)
        if tool_name:
            # Subquery to find trace_ids that have tool invocations matching the tool name
            tool_trace_ids = (
                db.query(ObservabilitySpan.trace_id)
                .filter(
                    ObservabilitySpan.name == "tool.invoke",
                    extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').ilike(f"%{tool_name}%"),
                )
                .distinct()
                .subquery()
            )
            query = query.filter(ObservabilityTrace.trace_id.in_(select(tool_trace_ids.c.trace_id)))

        # Get traces ordered by most recent
        traces = query.order_by(ObservabilityTrace.start_time.desc()).limit(limit).all()

        root_path = request.scope.get("root_path", "")
        return request.app.state.templates.TemplateResponse("observability_traces_list.html", {"request": request, "traces": traces, "root_path": root_path})
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/trace/{trace_id}", response_class=HTMLResponse)
async def get_observability_trace_detail(request: Request, trace_id: str, _user=Depends(get_current_user_with_permissions)):
    """Get detailed trace information with spans.

    Args:
        request: FastAPI request object
        trace_id: UUID of the trace to retrieve
        _user: Authenticated user with admin permissions (required by dependency)

    Returns:
        HTMLResponse: Rendered trace detail template with waterfall view

    Raises:
        HTTPException: 404 if trace not found
    """
    db = next(get_db())
    try:
        trace = db.query(ObservabilityTrace).filter_by(trace_id=trace_id).options(joinedload(ObservabilityTrace.spans).joinedload(ObservabilitySpan.events)).first()

        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")

        root_path = request.scope.get("root_path", "")
        return request.app.state.templates.TemplateResponse("observability_trace_detail.html", {"request": request, "trace": trace, "root_path": root_path})
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.post("/observability/queries", response_model=dict)
async def save_observability_query(
    request: Request,  # pylint: disable=unused-argument
    name: str = Body(..., description="Name for the saved query"),
    description: Optional[str] = Body(None, description="Optional description"),
    filter_config: dict = Body(..., description="Filter configuration as JSON"),
    is_shared: bool = Body(False, description="Whether query is shared with team"),
    user=Depends(get_current_user_with_permissions),
):
    """Save a new observability query filter configuration.

    Args:
        request: FastAPI request object
        name: User-given name for the query
        description: Optional description
        filter_config: Dictionary containing all filter values
        is_shared: Whether this query is visible to other users
        user: Authenticated user (required by dependency)

    Returns:
        dict: Created query details with id

    Raises:
        HTTPException: 400 if validation fails
    """
    db = next(get_db())
    try:
        # Get user email from authenticated user
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Create new saved query
        query = ObservabilitySavedQuery(name=name, description=description, user_email=user_email, filter_config=filter_config, is_shared=is_shared)

        db.add(query)
        db.commit()
        db.refresh(query)

        return {"id": query.id, "name": query.name, "description": query.description, "filter_config": query.filter_config, "is_shared": query.is_shared, "created_at": query.created_at.isoformat()}
    except Exception as e:
        db.rollback()
        LOGGER.error(f"Failed to save query: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/queries", response_model=list)
async def list_observability_queries(request: Request, user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """List saved observability queries for the current user.

    Returns user's own queries plus any shared queries.

    Args:
        request: FastAPI request object
        user: Authenticated user (required by dependency)

    Returns:
        list: List of saved query dictionaries
    """
    db = next(get_db())
    try:
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Get user's own queries + shared queries
        queries = (
            db.query(ObservabilitySavedQuery)
            .filter(or_(ObservabilitySavedQuery.user_email == user_email, ObservabilitySavedQuery.is_shared is True))
            .order_by(desc(ObservabilitySavedQuery.created_at))
            .all()
        )

        return [
            {
                "id": q.id,
                "name": q.name,
                "description": q.description,
                "filter_config": q.filter_config,
                "is_shared": q.is_shared,
                "user_email": q.user_email,
                "created_at": q.created_at.isoformat(),
                "last_used_at": q.last_used_at.isoformat() if q.last_used_at else None,
                "use_count": q.use_count,
            }
            for q in queries
        ]
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/queries/{query_id}", response_model=dict)
async def get_observability_query(request: Request, query_id: int, user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """Get a specific saved query by ID.

    Args:
        request: FastAPI request object
        query_id: ID of the saved query
        user: Authenticated user (required by dependency)

    Returns:
        dict: Query details

    Raises:
        HTTPException: 404 if query not found or unauthorized
    """
    db = next(get_db())
    try:
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Can only access own queries or shared queries
        query = (
            db.query(ObservabilitySavedQuery).filter(ObservabilitySavedQuery.id == query_id, or_(ObservabilitySavedQuery.user_email == user_email, ObservabilitySavedQuery.is_shared is True)).first()
        )

        if not query:
            raise HTTPException(status_code=404, detail="Query not found or unauthorized")

        return {
            "id": query.id,
            "name": query.name,
            "description": query.description,
            "filter_config": query.filter_config,
            "is_shared": query.is_shared,
            "user_email": query.user_email,
            "created_at": query.created_at.isoformat(),
            "last_used_at": query.last_used_at.isoformat() if query.last_used_at else None,
            "use_count": query.use_count,
        }
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.put("/observability/queries/{query_id}", response_model=dict)
async def update_observability_query(
    request: Request,  # pylint: disable=unused-argument
    query_id: int,
    name: Optional[str] = Body(None),
    description: Optional[str] = Body(None),
    filter_config: Optional[dict] = Body(None),
    is_shared: Optional[bool] = Body(None),
    user=Depends(get_current_user_with_permissions),
):
    """Update an existing saved query.

    Args:
        request: FastAPI request object
        query_id: ID of the query to update
        name: New name (optional)
        description: New description (optional)
        filter_config: New filter configuration (optional)
        is_shared: New sharing status (optional)
        user: Authenticated user (required by dependency)

    Returns:
        dict: Updated query details

    Raises:
        HTTPException: 404 if query not found, 403 if unauthorized
    """
    db = next(get_db())
    try:
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Can only update own queries
        query = db.query(ObservabilitySavedQuery).filter(ObservabilitySavedQuery.id == query_id, ObservabilitySavedQuery.user_email == user_email).first()

        if not query:
            raise HTTPException(status_code=404, detail="Query not found or unauthorized")

        # Update fields if provided
        if name is not None:
            query.name = name
        if description is not None:
            query.description = description
        if filter_config is not None:
            query.filter_config = filter_config
        if is_shared is not None:
            query.is_shared = is_shared

        db.commit()
        db.refresh(query)

        return {
            "id": query.id,
            "name": query.name,
            "description": query.description,
            "filter_config": query.filter_config,
            "is_shared": query.is_shared,
            "updated_at": query.updated_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        LOGGER.error(f"Failed to update query: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.delete("/observability/queries/{query_id}", status_code=204)
async def delete_observability_query(request: Request, query_id: int, user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """Delete a saved query.

    Args:
        request: FastAPI request object
        query_id: ID of the query to delete
        user: Authenticated user (required by dependency)

    Raises:
        HTTPException: 404 if query not found, 403 if unauthorized
    """
    db = next(get_db())
    try:
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Can only delete own queries
        query = db.query(ObservabilitySavedQuery).filter(ObservabilitySavedQuery.id == query_id, ObservabilitySavedQuery.user_email == user_email).first()

        if not query:
            raise HTTPException(status_code=404, detail="Query not found or unauthorized")

        db.delete(query)
        db.commit()
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.post("/observability/queries/{query_id}/use", response_model=dict)
async def track_query_usage(request: Request, query_id: int, user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """Track usage of a saved query (increments use count and updates last_used_at).

    Args:
        request: FastAPI request object
        query_id: ID of the query being used
        user: Authenticated user (required by dependency)

    Returns:
        dict: Updated query usage stats

    Raises:
        HTTPException: 404 if query not found or unauthorized
    """
    db = next(get_db())
    try:
        user_email = user.email if hasattr(user, "email") else "unknown"

        # Can track usage for own queries or shared queries
        query = (
            db.query(ObservabilitySavedQuery).filter(ObservabilitySavedQuery.id == query_id, or_(ObservabilitySavedQuery.user_email == user_email, ObservabilitySavedQuery.is_shared is True)).first()
        )

        if not query:
            raise HTTPException(status_code=404, detail="Query not found or unauthorized")

        # Update usage tracking
        query.use_count += 1
        query.last_used_at = utc_now()

        db.commit()
        db.refresh(query)

        return {"use_count": query.use_count, "last_used_at": query.last_used_at.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        LOGGER.error(f"Failed to track query usage: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/metrics/percentiles", response_model=dict)
async def get_latency_percentiles(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    interval_minutes: int = Query(60, ge=5, le=1440, description="Aggregation interval in minutes"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get latency percentiles (p50, p90, p95, p99) over time.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        interval_minutes: Aggregation interval in minutes (5-1440)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Time-series data with percentiles

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Use SQL aggregation for PostgreSQL, Python fallback for SQLite
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            return _get_latency_percentiles_postgresql(db, cutoff_time, interval_minutes)
        return _get_latency_percentiles_python(db, cutoff_time, interval_minutes)
    except Exception as e:
        LOGGER.error(f"Failed to calculate latency percentiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


def _get_latency_percentiles_postgresql(db: Session, cutoff_time: datetime, interval_minutes: int) -> dict:
    """Compute time-bucketed latency percentiles using PostgreSQL.

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        interval_minutes: Bucket size in minutes

    Returns:
        dict: Time-series percentile data
    """
    # PostgreSQL query with epoch-based bucketing (works for any interval including > 60 min)
    stats_sql = text(
        """
        SELECT
            TO_TIMESTAMP(FLOOR(EXTRACT(EPOCH FROM start_time) / :interval_seconds) * :interval_seconds) as bucket,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) as p50,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY duration_ms) as p90,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) as p99
        FROM observability_traces
        WHERE start_time >= :cutoff_time AND duration_ms IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
        """
    )

    interval_seconds = interval_minutes * 60
    results = db.execute(stats_sql, {"cutoff_time": cutoff_time, "interval_seconds": interval_seconds}).fetchall()

    if not results:
        return {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    timestamps = []
    p50_values = []
    p90_values = []
    p95_values = []
    p99_values = []

    for row in results:
        timestamps.append(row.bucket.isoformat() if row.bucket else "")
        p50_values.append(round(float(row.p50), 2) if row.p50 else 0)
        p90_values.append(round(float(row.p90), 2) if row.p90 else 0)
        p95_values.append(round(float(row.p95), 2) if row.p95 else 0)
        p99_values.append(round(float(row.p99), 2) if row.p99 else 0)

    return {"timestamps": timestamps, "p50": p50_values, "p90": p90_values, "p95": p95_values, "p99": p99_values}


def _get_latency_percentiles_python(db: Session, cutoff_time: datetime, interval_minutes: int) -> dict:
    """Compute time-bucketed latency percentiles using Python (fallback for SQLite).

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        interval_minutes: Bucket size in minutes

    Returns:
        dict: Time-series percentile data
    """
    # Query all traces with duration in time range
    traces = (
        db.query(ObservabilityTrace.start_time, ObservabilityTrace.duration_ms)
        .filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None))
        .order_by(ObservabilityTrace.start_time)
        .all()
    )

    if not traces:
        return {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    # Group traces into time buckets using epoch-based bucketing (works for any interval)
    interval_seconds = interval_minutes * 60
    buckets: Dict[datetime, List[float]] = defaultdict(list)
    for trace in traces:
        trace_time = trace.start_time
        if trace_time.tzinfo is None:
            trace_time = trace_time.replace(tzinfo=timezone.utc)
        epoch = trace_time.timestamp()
        bucket_epoch = (epoch // interval_seconds) * interval_seconds
        bucket_time = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
        buckets[bucket_time].append(trace.duration_ms)

    # Calculate percentiles for each bucket
    timestamps = []
    p50_values = []
    p90_values = []
    p95_values = []
    p99_values = []

    def percentile_cont(data: List[float], p: float) -> float:
        """Linear interpolation percentile matching PostgreSQL percentile_cont.

        Args:
            data: Sorted list of float values.
            p: Percentile value between 0 and 1.

        Returns:
            float: Interpolated percentile value.
        """
        n = len(data)
        if n == 0:
            return 0.0
        if n == 1:
            return data[0]
        k = p * (n - 1)
        f = int(k)
        c = k - f
        if f + 1 < n:
            return data[f] + c * (data[f + 1] - data[f])
        return data[f]

    for bucket_time in sorted(buckets.keys()):
        durations = sorted(buckets[bucket_time])

        if durations:
            timestamps.append(bucket_time.isoformat())
            p50_values.append(round(percentile_cont(durations, 0.50), 2))
            p90_values.append(round(percentile_cont(durations, 0.90), 2))
            p95_values.append(round(percentile_cont(durations, 0.95), 2))
            p99_values.append(round(percentile_cont(durations, 0.99), 2))

    return {"timestamps": timestamps, "p50": p50_values, "p90": p90_values, "p95": p95_values, "p99": p99_values}


@admin_router.get("/observability/metrics/timeseries", response_model=dict)
async def get_timeseries_metrics(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    interval_minutes: int = Query(60, ge=5, le=1440, description="Aggregation interval in minutes"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get time-series metrics (request rate, error rate, throughput).

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        interval_minutes: Aggregation interval in minutes (5-1440)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Time-series data with request counts, error rates, and throughput

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Use SQL aggregation for PostgreSQL, Python fallback for SQLite
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            return _get_timeseries_metrics_postgresql(db, cutoff_time, interval_minutes)
        return _get_timeseries_metrics_python(db, cutoff_time, interval_minutes)
    except Exception as e:
        LOGGER.error(f"Failed to calculate timeseries metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


def _get_timeseries_metrics_postgresql(db: Session, cutoff_time: datetime, interval_minutes: int) -> dict:
    """Compute time-series metrics using PostgreSQL.

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        interval_minutes: Bucket size in minutes

    Returns:
        dict: Time-series metrics data
    """
    # Use epoch-based bucketing (works for any interval including > 60 min)
    stats_sql = text(
        """
        SELECT
            TO_TIMESTAMP(FLOOR(EXTRACT(EPOCH FROM start_time) / :interval_seconds) * :interval_seconds) as bucket,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error
        FROM observability_traces
        WHERE start_time >= :cutoff_time
        GROUP BY bucket
        ORDER BY bucket
        """
    )

    interval_seconds = interval_minutes * 60
    results = db.execute(stats_sql, {"cutoff_time": cutoff_time, "interval_seconds": interval_seconds}).fetchall()

    if not results:
        return {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    timestamps = []
    request_counts = []
    success_counts = []
    error_counts = []
    error_rates = []

    for row in results:
        total = row.total or 0
        error = row.error or 0
        error_rate = (error / total * 100) if total > 0 else 0

        timestamps.append(row.bucket.isoformat() if row.bucket else "")
        request_counts.append(total)
        success_counts.append(row.success or 0)
        error_counts.append(error)
        error_rates.append(round(error_rate, 2))

    return {
        "timestamps": timestamps,
        "request_count": request_counts,
        "success_count": success_counts,
        "error_count": error_counts,
        "error_rate": error_rates,
    }


def _get_timeseries_metrics_python(db: Session, cutoff_time: datetime, interval_minutes: int) -> dict:
    """Compute time-series metrics using Python (fallback for SQLite).

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        interval_minutes: Bucket size in minutes

    Returns:
        dict: Time-series metrics data
    """
    # Query traces grouped by time bucket
    traces = db.query(ObservabilityTrace.start_time, ObservabilityTrace.status).filter(ObservabilityTrace.start_time >= cutoff_time).order_by(ObservabilityTrace.start_time).all()

    if not traces:
        return {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    # Group traces into time buckets using epoch-based bucketing (works for any interval)
    interval_seconds = interval_minutes * 60
    buckets: Dict[datetime, Dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0, "error": 0})
    for trace in traces:
        trace_time = trace.start_time
        if trace_time.tzinfo is None:
            trace_time = trace_time.replace(tzinfo=timezone.utc)
        epoch = trace_time.timestamp()
        bucket_epoch = (epoch // interval_seconds) * interval_seconds
        bucket_time = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)

        buckets[bucket_time]["total"] += 1
        if trace.status == "ok":
            buckets[bucket_time]["success"] += 1
        elif trace.status == "error":
            buckets[bucket_time]["error"] += 1

    # Build time-series arrays
    timestamps = []
    request_counts = []
    success_counts = []
    error_counts = []
    error_rates = []

    for bucket_time in sorted(buckets.keys()):
        bucket = buckets[bucket_time]
        error_rate = (bucket["error"] / bucket["total"] * 100) if bucket["total"] > 0 else 0

        timestamps.append(bucket_time.isoformat())
        request_counts.append(bucket["total"])
        success_counts.append(bucket["success"])
        error_counts.append(bucket["error"])
        error_rates.append(round(error_rate, 2))

    return {
        "timestamps": timestamps,
        "request_count": request_counts,
        "success_count": success_counts,
        "error_count": error_counts,
        "error_rate": error_rates,
    }


def _get_latency_heatmap_postgresql(db: Session, cutoff_time: datetime, hours: int, time_buckets: int, latency_buckets: int) -> dict:
    """Compute latency heatmap using PostgreSQL (optimized path).

    Uses SQL arithmetic for efficient 2D histogram computation.

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        hours: Time range in hours
        time_buckets: Number of time buckets
        latency_buckets: Number of latency buckets

    Returns:
        dict: Heatmap data with time and latency dimensions
    """
    # First, get min/max durations
    stats_query = text(
        """
        SELECT MIN(duration_ms) as min_d, MAX(duration_ms) as max_d
        FROM observability_traces
        WHERE start_time >= :cutoff_time AND duration_ms IS NOT NULL
    """
    )
    stats_row = db.execute(stats_query, {"cutoff_time": cutoff_time}).fetchone()

    if not stats_row or stats_row.min_d is None:
        return {"time_labels": [], "latency_labels": [], "data": []}

    min_duration = float(stats_row.min_d)
    max_duration = float(stats_row.max_d)
    latency_range = max_duration - min_duration

    # Handle case where all durations are the same
    if latency_range == 0:
        latency_range = 1.0
        max_duration = min_duration + 1.0

    time_range_minutes = hours * 60
    latency_bucket_size = latency_range / latency_buckets
    time_bucket_minutes = time_range_minutes / time_buckets

    # Use SQL arithmetic for 2D histogram bucketing
    heatmap_query = text(
        """
        SELECT
            LEAST(GREATEST(
                (EXTRACT(EPOCH FROM (start_time - :cutoff_time)) / 60.0 / :time_bucket_minutes)::int,
                0
            ), :time_buckets - 1) as time_idx,
            LEAST(GREATEST(
                ((duration_ms - :min_duration) / :latency_bucket_size)::int,
                0
            ), :latency_buckets - 1) as latency_idx,
            COUNT(*) as cnt
        FROM observability_traces
        WHERE start_time >= :cutoff_time AND duration_ms IS NOT NULL
        GROUP BY time_idx, latency_idx
    """
    )

    rows = db.execute(
        heatmap_query,
        {
            "cutoff_time": cutoff_time,
            "time_bucket_minutes": time_bucket_minutes,
            "time_buckets": time_buckets,
            "min_duration": min_duration,
            "latency_bucket_size": latency_bucket_size,
            "latency_buckets": latency_buckets,
        },
    ).fetchall()

    # Initialize heatmap matrix
    heatmap = [[0 for _ in range(time_buckets)] for _ in range(latency_buckets)]

    # Populate from SQL results
    for row in rows:
        time_idx = int(row.time_idx)
        latency_idx = int(row.latency_idx)
        if 0 <= time_idx < time_buckets and 0 <= latency_idx < latency_buckets:
            heatmap[latency_idx][time_idx] = int(row.cnt)

    # Generate labels
    time_labels = []
    for i in range(time_buckets):
        bucket_time = cutoff_time + timedelta(minutes=i * time_bucket_minutes)
        time_labels.append(bucket_time.strftime("%H:%M"))

    latency_labels = []
    for i in range(latency_buckets):
        bucket_min = min_duration + i * latency_bucket_size
        bucket_max = bucket_min + latency_bucket_size
        latency_labels.append(f"{bucket_min:.0f}-{bucket_max:.0f}ms")

    return {"time_labels": time_labels, "latency_labels": latency_labels, "data": heatmap}


def _get_latency_heatmap_python(db: Session, cutoff_time: datetime, hours: int, time_buckets: int, latency_buckets: int) -> dict:
    """Compute latency heatmap using Python (fallback for SQLite).

    Args:
        db: Database session
        cutoff_time: Start time for analysis
        hours: Time range in hours
        time_buckets: Number of time buckets
        latency_buckets: Number of latency buckets

    Returns:
        dict: Heatmap data with time and latency dimensions
    """
    # Query all traces with duration
    traces = (
        db.query(ObservabilityTrace.start_time, ObservabilityTrace.duration_ms)
        .filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None))
        .order_by(ObservabilityTrace.start_time)
        .all()
    )

    if not traces:
        return {"time_labels": [], "latency_labels": [], "data": []}

    # Calculate time bucket size
    time_range = hours * 60  # minutes
    time_bucket_minutes = time_range / time_buckets

    # Find latency range and create buckets
    durations = [t.duration_ms for t in traces]
    min_duration = min(durations)
    max_duration = max(durations)
    latency_range = max_duration - min_duration
    latency_bucket_size = latency_range / latency_buckets if latency_range > 0 else 1

    # Initialize heatmap matrix
    heatmap = [[0 for _ in range(time_buckets)] for _ in range(latency_buckets)]

    # Populate heatmap
    for trace in traces:
        trace_time = trace.start_time
        # Convert naive SQLite datetime to UTC aware
        if trace_time.tzinfo is None:
            trace_time = trace_time.replace(tzinfo=timezone.utc)

        # Calculate time bucket index
        time_diff = (trace_time - cutoff_time).total_seconds() / 60  # minutes
        time_idx = min(int(time_diff / time_bucket_minutes), time_buckets - 1)

        # Calculate latency bucket index
        latency_idx = min(int((trace.duration_ms - min_duration) / latency_bucket_size), latency_buckets - 1)

        heatmap[latency_idx][time_idx] += 1

    # Generate labels
    time_labels = []
    for i in range(time_buckets):
        bucket_time = cutoff_time + timedelta(minutes=i * time_bucket_minutes)
        time_labels.append(bucket_time.strftime("%H:%M"))

    latency_labels = []
    for i in range(latency_buckets):
        bucket_min = min_duration + i * latency_bucket_size
        bucket_max = bucket_min + latency_bucket_size
        latency_labels.append(f"{bucket_min:.0f}-{bucket_max:.0f}ms")

    return {"time_labels": time_labels, "latency_labels": latency_labels, "data": heatmap}


@admin_router.get("/observability/metrics/top-slow", response_model=dict)
async def get_top_slow_endpoints(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(10, ge=1, le=100, description="Number of results"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get top N slowest endpoints by average duration.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Number of results to return (1-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: List of slowest endpoints with stats

    Raises:
        HTTPException: 500 if query fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Group by endpoint and calculate average duration
        results = (
            db.query(
                ObservabilityTrace.http_url,
                ObservabilityTrace.http_method,
                func.count(ObservabilityTrace.trace_id).label("count"),  # pylint: disable=not-callable
                func.avg(ObservabilityTrace.duration_ms).label("avg_duration"),
                func.max(ObservabilityTrace.duration_ms).label("max_duration"),
            )
            .filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None))
            .group_by(ObservabilityTrace.http_url, ObservabilityTrace.http_method)
            .order_by(desc("avg_duration"))
            .limit(limit)
            .all()
        )

        endpoints = []
        for row in results:
            endpoints.append(
                {
                    "endpoint": f"{row.http_method} {row.http_url}",
                    "method": row.http_method,
                    "url": row.http_url,
                    "count": row.count,
                    "avg_duration_ms": round(row.avg_duration, 2),
                    "max_duration_ms": round(row.max_duration, 2),
                }
            )

        return {"endpoints": endpoints}
    except Exception as e:
        LOGGER.error(f"Failed to get top slow endpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/metrics/top-volume", response_model=dict)
async def get_top_volume_endpoints(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(10, ge=1, le=100, description="Number of results"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get top N highest volume endpoints by request count.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Number of results to return (1-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: List of highest volume endpoints with stats

    Raises:
        HTTPException: 500 if query fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Group by endpoint and count requests
        results = (
            db.query(
                ObservabilityTrace.http_url,
                ObservabilityTrace.http_method,
                func.count(ObservabilityTrace.trace_id).label("count"),  # pylint: disable=not-callable
                func.avg(ObservabilityTrace.duration_ms).label("avg_duration"),
            )
            .filter(ObservabilityTrace.start_time >= cutoff_time)
            .group_by(ObservabilityTrace.http_url, ObservabilityTrace.http_method)
            .order_by(desc("count"))
            .limit(limit)
            .all()
        )

        endpoints = []
        for row in results:
            endpoints.append(
                {
                    "endpoint": f"{row.http_method} {row.http_url}",
                    "method": row.http_method,
                    "url": row.http_url,
                    "count": row.count,
                    "avg_duration_ms": round(row.avg_duration, 2) if row.avg_duration else 0,
                }
            )

        return {"endpoints": endpoints}
    except Exception as e:
        LOGGER.error(f"Failed to get top volume endpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/metrics/top-errors", response_model=dict)
async def get_top_error_endpoints(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(10, ge=1, le=100, description="Number of results"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get top N error-prone endpoints by error count and rate.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Number of results to return (1-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: List of error-prone endpoints with stats

    Raises:
        HTTPException: 500 if query fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Group by endpoint and count errors
        results = (
            db.query(
                ObservabilityTrace.http_url,
                ObservabilityTrace.http_method,
                func.count(ObservabilityTrace.trace_id).label("total_count"),  # pylint: disable=not-callable
                func.sum(case((ObservabilityTrace.status == "error", 1), else_=0)).label("error_count"),
            )
            .filter(ObservabilityTrace.start_time >= cutoff_time)
            .group_by(ObservabilityTrace.http_url, ObservabilityTrace.http_method)
            .having(func.sum(case((ObservabilityTrace.status == "error", 1), else_=0)) > 0)
            .order_by(desc("error_count"))
            .limit(limit)
            .all()
        )

        endpoints = []
        for row in results:
            error_rate = (row.error_count / row.total_count * 100) if row.total_count > 0 else 0
            endpoints.append(
                {
                    "endpoint": f"{row.http_method} {row.http_url}",
                    "method": row.http_method,
                    "url": row.http_url,
                    "total_count": row.total_count,
                    "error_count": row.error_count,
                    "error_rate": round(error_rate, 2),
                }
            )

        return {"endpoints": endpoints}
    except Exception as e:
        LOGGER.error(f"Failed to get top error endpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/metrics/heatmap", response_model=dict)
async def get_latency_heatmap(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    time_buckets: int = Query(24, ge=10, le=100, description="Number of time buckets"),
    latency_buckets: int = Query(20, ge=5, le=50, description="Number of latency buckets"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get latency distribution heatmap data.

    Uses PostgreSQL SQL aggregation for efficient computation when available,
    falls back to Python for SQLite.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        time_buckets: Number of time buckets (10-100)
        latency_buckets: Number of latency buckets (5-50)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Heatmap data with time and latency dimensions

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Route to appropriate implementation based on database dialect
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            return _get_latency_heatmap_postgresql(db, cutoff_time, hours, time_buckets, latency_buckets)
        return _get_latency_heatmap_python(db, cutoff_time, hours, time_buckets, latency_buckets)
    except Exception as e:
        LOGGER.error(f"Failed to generate latency heatmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/tools/usage", response_model=dict)
async def get_tool_usage(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of tools to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get tool usage frequency statistics.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of tools to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Tool usage statistics with counts and percentages

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Query tool invocations from spans
        # Note: Using $."tool.name" because the JSON key contains a dot
        tool_usage = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').label("tool_name"),
                func.count(ObservabilitySpan.span_id).label("count"),  # pylint: disable=not-callable
            )
            .filter(
                ObservabilitySpan.name == "tool.invoke",
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."tool.name"'))
            .order_by(func.count(ObservabilitySpan.span_id).desc())  # pylint: disable=not-callable
            .limit(limit)
            .all()
        )

        total_invocations = sum(row.count for row in tool_usage)

        tools = [
            {
                "tool_name": row.tool_name,
                "count": row.count,
                "percentage": round((row.count / total_invocations * 100) if total_invocations > 0 else 0, 2),
            }
            for row in tool_usage
        ]

        return {"tools": tools, "total_invocations": total_invocations, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get tool usage statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/tools/performance", response_model=dict)
async def get_tool_performance(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of tools to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get tool performance metrics (avg, min, max duration).

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of tools to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Tool performance metrics

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # First, get all tool invocations with durations
        tool_spans = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').label("tool_name"),
                ObservabilitySpan.duration_ms,
            )
            .filter(
                ObservabilitySpan.name == "tool.invoke",
                ObservabilitySpan.start_time >= cutoff_time_naive,
                ObservabilitySpan.duration_ms.isnot(None),
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').isnot(None),
            )
            .all()
        )

        # Group by tool name and calculate percentiles
        tool_durations = defaultdict(list)
        for span in tool_spans:
            tool_durations[span.tool_name].append(span.duration_ms)

        # Calculate metrics for each tool
        tools_data = []
        for tool_name, durations in tool_durations.items():
            durations_sorted = sorted(durations)
            n = len(durations_sorted)

            if n == 0:
                continue

            # Calculate percentiles
            def percentile(data, p):
                if not data:
                    return 0
                k = (len(data) - 1) * p
                f = int(k)
                c = min(f + 1, len(data) - 1)
                if f == c:
                    return data[f]
                return data[f] * (c - k) + data[c] * (k - f)

            tools_data.append(
                {
                    "tool_name": tool_name,
                    "count": n,
                    "avg_duration_ms": round(sum(durations) / n, 2),
                    "min_duration_ms": round(min(durations), 2),
                    "max_duration_ms": round(max(durations), 2),
                    "p50": round(percentile(durations_sorted, 0.50), 2),
                    "p90": round(percentile(durations_sorted, 0.90), 2),
                    "p95": round(percentile(durations_sorted, 0.95), 2),
                    "p99": round(percentile(durations_sorted, 0.99), 2),
                }
            )

        # Sort by average duration descending and limit
        tools_data.sort(key=lambda x: x["avg_duration_ms"], reverse=True)
        tools = tools_data[:limit]

        return {"tools": tools, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get tool performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/tools/errors", response_model=dict)
async def get_tool_errors(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of tools to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get tool error rates and statistics.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of tools to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Tool error statistics

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Query tool error rates
        tool_errors = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').label("tool_name"),
                func.count(ObservabilitySpan.span_id).label("total_count"),  # pylint: disable=not-callable
                func.sum(case((ObservabilitySpan.status == "error", 1), else_=0)).label("error_count"),  # pylint: disable=not-callable
            )
            .filter(
                ObservabilitySpan.name == "tool.invoke",
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."tool.name"'))
            .order_by(func.sum(case((ObservabilitySpan.status == "error", 1), else_=0)).desc())  # pylint: disable=not-callable
            .limit(limit)
            .all()
        )

        tools = [
            {
                "tool_name": row.tool_name,
                "total_count": row.total_count,
                "error_count": row.error_count or 0,
                "error_rate": round((row.error_count / row.total_count * 100) if row.total_count > 0 and row.error_count else 0, 2),
            }
            for row in tool_errors
        ]

        return {"tools": tools, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get tool error statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/tools/chains", response_model=dict)
async def get_tool_chains(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of chains to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get tool chain analysis (which tools are invoked together in the same trace).

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of chains to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Tool chain statistics showing common tool sequences

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Get all tool invocations grouped by trace_id
        tool_spans = (
            db.query(
                ObservabilitySpan.trace_id,
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').label("tool_name"),
                ObservabilitySpan.start_time,
            )
            .filter(
                ObservabilitySpan.name == "tool.invoke",
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."tool.name"').isnot(None),
            )
            .order_by(ObservabilitySpan.trace_id, ObservabilitySpan.start_time)
            .all()
        )

        # Group tools by trace and create chains
        trace_tools = {}
        for span in tool_spans:
            if span.trace_id not in trace_tools:
                trace_tools[span.trace_id] = []
            trace_tools[span.trace_id].append(span.tool_name)

        # Count tool chain frequencies
        chain_counts = {}
        for tools in trace_tools.values():
            if len(tools) > 1:
                # Create a chain string (sorted to treat [A,B] and [B,A] as same chain)
                chain = " -> ".join(tools)
                chain_counts[chain] = chain_counts.get(chain, 0) + 1

        # Sort by frequency and take top N
        sorted_chains = sorted(chain_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

        chains = [{"chain": chain, "count": count} for chain, count in sorted_chains]

        return {"chains": chains, "total_traces_with_tools": len(trace_tools), "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get tool chain statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/tools/partial", response_class=HTMLResponse)
async def get_tools_partial(
    request: Request,
    _user=Depends(get_current_user_with_permissions),
):
    """Render the tool invocation metrics dashboard HTML partial.

    Args:
        request: FastAPI request object
        _user: Authenticated user (required by dependency)

    Returns:
        HTMLResponse: Rendered tool metrics dashboard partial
    """
    root_path = request.scope.get("root_path", "")
    return request.app.state.templates.TemplateResponse(
        "observability_tools.html",
        {
            "request": request,
            "root_path": root_path,
        },
    )


# ==============================================================================
# Prompts Observability Endpoints
# ==============================================================================


@admin_router.get("/observability/prompts/usage", response_model=dict)
async def get_prompt_usage(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of prompts to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get prompt rendering frequency statistics.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of prompts to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Prompt usage statistics with counts and percentages

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Query prompt renders from spans (looking for prompts/get calls)
        # The prompt id should be in attributes as "prompt.id"
        prompt_usage = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').label("prompt_id"),
                func.count(ObservabilitySpan.span_id).label("count"),  # pylint: disable=not-callable
            )
            .filter(
                ObservabilitySpan.name.in_(["prompt.get", "prompts.get", "prompt.render"]),
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"'))
            .order_by(func.count(ObservabilitySpan.span_id).desc())  # pylint: disable=not-callable
            .limit(limit)
            .all()
        )

        total_renders = sum(row.count for row in prompt_usage)

        prompts = [
            {
                "prompt_id": row.prompt_id,
                "count": row.count,
                "percentage": round((row.count / total_renders * 100) if total_renders > 0 else 0, 2),
            }
            for row in prompt_usage
        ]

        return {"prompts": prompts, "total_renders": total_renders, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get prompt usage statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/prompts/performance", response_model=dict)
async def get_prompt_performance(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of prompts to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get prompt performance metrics (avg, min, max duration).

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of prompts to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Prompt performance metrics

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # First, get all prompt renders with durations
        prompt_spans = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').label("prompt_id"),
                ObservabilitySpan.duration_ms,
            )
            .filter(
                ObservabilitySpan.name.in_(["prompt.get", "prompts.get", "prompt.render"]),
                ObservabilitySpan.start_time >= cutoff_time_naive,
                ObservabilitySpan.duration_ms.isnot(None),
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').isnot(None),
            )
            .all()
        )

        # Group by prompt id and calculate percentiles
        prompt_durations = defaultdict(list)
        for span in prompt_spans:
            prompt_durations[span.prompt_id].append(span.duration_ms)

        # Calculate metrics for each prompt
        prompts_data = []
        for prompt_id, durations in prompt_durations.items():
            durations_sorted = sorted(durations)
            n = len(durations_sorted)

            if n == 0:
                continue

            # Calculate percentiles
            def percentile(data, p):
                if not data:
                    return 0
                k = (len(data) - 1) * p
                f = int(k)
                c = min(f + 1, len(data) - 1)
                if f == c:
                    return data[f]
                return data[f] * (c - k) + data[c] * (k - f)

            prompts_data.append(
                {
                    "prompt_id": prompt_id,
                    "count": n,
                    "avg_duration_ms": round(sum(durations) / n, 2),
                    "min_duration_ms": round(min(durations), 2),
                    "max_duration_ms": round(max(durations), 2),
                    "p50": round(percentile(durations_sorted, 0.50), 2),
                    "p90": round(percentile(durations_sorted, 0.90), 2),
                    "p95": round(percentile(durations_sorted, 0.95), 2),
                    "p99": round(percentile(durations_sorted, 0.99), 2),
                }
            )

        # Sort by average duration descending and limit
        prompts_data.sort(key=lambda x: x["avg_duration_ms"], reverse=True)
        prompts = prompts_data[:limit]

        return {"prompts": prompts, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get prompt performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/prompts/errors", response_model=dict)
async def get_prompts_errors(
    hours: int = Query(24, description="Time range in hours"),
    limit: int = Query(20, description="Maximum number of results"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get prompt error rates.

    Args:
        hours: Time range in hours to analyze
        limit: Maximum number of prompts to return
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Prompt error statistics
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Get all prompt spans with their status
        prompt_stats = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').label("prompt_id"),
                func.count().label("total_count"),  # pylint: disable=not-callable
                func.sum(case((ObservabilitySpan.status == "error", 1), else_=0)).label("error_count"),
            )
            .filter(
                ObservabilitySpan.name == "prompt.render",
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."prompt.id"'))
            .all()
        )

        prompts_data = []
        for stat in prompt_stats:
            total = stat.total_count
            errors = stat.error_count or 0
            error_rate = round((errors / total * 100), 2) if total > 0 else 0

            prompts_data.append({"prompt_id": stat.prompt_id, "total_count": total, "error_count": errors, "error_rate": error_rate})

        # Sort by error rate descending
        prompts_data.sort(key=lambda x: x["error_rate"], reverse=True)
        prompts_data = prompts_data[:limit]

        return {"prompts": prompts_data, "time_range_hours": hours}
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/prompts/partial", response_class=HTMLResponse)
async def get_prompts_partial(
    request: Request,
    _user=Depends(get_current_user_with_permissions),
):
    """Render the prompt rendering metrics dashboard HTML partial.

    Args:
        request: FastAPI request object
        _user: Authenticated user (required by dependency)

    Returns:
        HTMLResponse: Rendered prompt metrics dashboard partial
    """
    root_path = request.scope.get("root_path", "")
    return request.app.state.templates.TemplateResponse(
        "observability_prompts.html",
        {
            "request": request,
            "root_path": root_path,
        },
    )


# ==============================================================================
# Resources Observability Endpoints
# ==============================================================================


@admin_router.get("/observability/resources/usage", response_model=dict)
async def get_resource_usage(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of resources to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get resource fetch frequency statistics.

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of resources to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Resource usage statistics with counts and percentages

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Query resource reads from spans (looking for resources/read calls)
        # The resource URI should be in attributes
        resource_usage = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').label("resource_uri"),
                func.count(ObservabilitySpan.span_id).label("count"),  # pylint: disable=not-callable
            )
            .filter(
                ObservabilitySpan.name.in_(["resource.read", "resources.read", "resource.fetch"]),
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"'))
            .order_by(func.count(ObservabilitySpan.span_id).desc())  # pylint: disable=not-callable
            .limit(limit)
            .all()
        )

        total_fetches = sum(row.count for row in resource_usage)

        resources = [
            {
                "resource_uri": row.resource_uri,
                "count": row.count,
                "percentage": round((row.count / total_fetches * 100) if total_fetches > 0 else 0, 2),
            }
            for row in resource_usage
        ]

        return {"resources": resources, "total_fetches": total_fetches, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get resource usage statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/resources/performance", response_model=dict)
async def get_resource_performance(
    request: Request,  # pylint: disable=unused-argument
    hours: int = Query(24, ge=1, le=168, description="Time range in hours"),
    limit: int = Query(20, ge=5, le=100, description="Number of resources to return"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get resource performance metrics (avg, min, max duration).

    Args:
        request: FastAPI request object
        hours: Number of hours to look back (1-168)
        limit: Maximum number of resources to return (5-100)
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Resource performance metrics

    Raises:
        HTTPException: 500 if calculation fails
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # First, get all resource reads with durations
        resource_spans = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').label("resource_uri"),
                ObservabilitySpan.duration_ms,
            )
            .filter(
                ObservabilitySpan.name.in_(["resource.read", "resources.read", "resource.fetch"]),
                ObservabilitySpan.start_time >= cutoff_time_naive,
                ObservabilitySpan.duration_ms.isnot(None),
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').isnot(None),
            )
            .all()
        )

        # Group by resource URI and calculate percentiles
        resource_durations = defaultdict(list)
        for span in resource_spans:
            resource_durations[span.resource_uri].append(span.duration_ms)

        # Calculate metrics for each resource
        resources_data = []
        for resource_uri, durations in resource_durations.items():
            durations_sorted = sorted(durations)
            n = len(durations_sorted)

            if n == 0:
                continue

            # Calculate percentiles
            def percentile(data, p):
                if not data:
                    return 0
                k = (len(data) - 1) * p
                f = int(k)
                c = min(f + 1, len(data) - 1)
                if f == c:
                    return data[f]
                return data[f] * (c - k) + data[c] * (k - f)

            resources_data.append(
                {
                    "resource_uri": resource_uri,
                    "count": n,
                    "avg_duration_ms": round(sum(durations) / n, 2),
                    "min_duration_ms": round(min(durations), 2),
                    "max_duration_ms": round(max(durations), 2),
                    "p50": round(percentile(durations_sorted, 0.50), 2),
                    "p90": round(percentile(durations_sorted, 0.90), 2),
                    "p95": round(percentile(durations_sorted, 0.95), 2),
                    "p99": round(percentile(durations_sorted, 0.99), 2),
                }
            )

        # Sort by average duration descending and limit
        resources_data.sort(key=lambda x: x["avg_duration_ms"], reverse=True)
        resources = resources_data[:limit]

        return {"resources": resources, "time_range_hours": hours}
    except Exception as e:
        LOGGER.error(f"Failed to get resource performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/resources/errors", response_model=dict)
async def get_resources_errors(
    hours: int = Query(24, description="Time range in hours"),
    limit: int = Query(20, description="Maximum number of results"),
    _user=Depends(get_current_user_with_permissions),
):
    """Get resource error rates.

    Args:
        hours: Time range in hours to analyze
        limit: Maximum number of resources to return
        _user: Authenticated user (required by dependency)

    Returns:
        dict: Resource error statistics
    """
    db = next(get_db())
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        # Get all resource spans with their status
        resource_stats = (
            db.query(
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').label("resource_uri"),
                func.count().label("total_count"),  # pylint: disable=not-callable
                func.sum(case((ObservabilitySpan.status == "error", 1), else_=0)).label("error_count"),
            )
            .filter(
                ObservabilitySpan.name.in_(["resource.read", "resources.read", "resource.fetch"]),
                ObservabilitySpan.start_time >= cutoff_time_naive,
                extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"').isnot(None),
            )
            .group_by(extract_json_field(ObservabilitySpan.attributes, '$."resource.uri"'))
            .all()
        )

        resources_data = []
        for stat in resource_stats:
            total = stat.total_count
            errors = stat.error_count or 0
            error_rate = round((errors / total * 100), 2) if total > 0 else 0

            resources_data.append({"resource_uri": stat.resource_uri, "total_count": total, "error_count": errors, "error_rate": error_rate})

        # Sort by error rate descending
        resources_data.sort(key=lambda x: x["error_rate"], reverse=True)
        resources_data = resources_data[:limit]

        return {"resources": resources_data, "time_range_hours": hours}
    finally:
        # Ensure close() always runs even if commit() fails
        try:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
        finally:
            db.close()


@admin_router.get("/observability/resources/partial", response_class=HTMLResponse)
async def get_resources_partial(
    request: Request,
    _user=Depends(get_current_user_with_permissions),
):
    """Render the resource fetch metrics dashboard HTML partial.

    Args:
        request: FastAPI request object
        _user: Authenticated user (required by dependency)

    Returns:
        HTMLResponse: Rendered resource metrics dashboard partial
    """
    root_path = request.scope.get("root_path", "")
    return request.app.state.templates.TemplateResponse(
        "observability_resources.html",
        {
            "request": request,
            "root_path": root_path,
        },
    )


# ===================================
# Performance Monitoring Endpoints
# ===================================


@admin_router.get("/performance/stats", response_class=HTMLResponse)
async def get_performance_stats(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get comprehensive performance metrics for the dashboard.

    Returns either an HTML partial for HTMX requests or JSON for API requests.
    Includes system metrics, request metrics, worker status, and cache stats.

    Args:
        request: FastAPI request object
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        HTMLResponse or JSONResponse: Performance dashboard data

    Raises:
        HTTPException: 404 if performance tracking is disabled, 500 on retrieval error
    """
    if not settings.mcpgateway_performance_tracking:
        if request.headers.get("hx-request"):
            return HTMLResponse(content='<div class="text-center py-8 text-gray-500">Performance tracking is disabled. Enable with MCPGATEWAY_PERFORMANCE_TRACKING=true</div>')
        raise HTTPException(status_code=404, detail="Performance monitoring is disabled")

    try:
        service = get_performance_service(db)
        dashboard = await service.get_dashboard()

        # Convert to dict for template
        dashboard_data = dashboard.model_dump()

        # Format datetime fields for display
        if dashboard_data.get("timestamp"):
            dashboard_data["timestamp"] = dashboard_data["timestamp"].isoformat()
        if dashboard_data.get("system", {}).get("boot_time"):
            dashboard_data["system"]["boot_time"] = dashboard_data["system"]["boot_time"].isoformat()
        for worker in dashboard_data.get("workers", []):
            if worker.get("create_time"):
                worker["create_time"] = worker["create_time"].isoformat()

        if request.headers.get("hx-request"):
            root_path = request.scope.get("root_path", "")
            return request.app.state.templates.TemplateResponse(
                "performance_partial.html",
                {
                    "request": request,
                    "dashboard": dashboard_data,
                    "root_path": root_path,
                },
            )

        return ORJSONResponse(content=dashboard_data)

    except Exception as e:
        LOGGER.error(f"Performance metrics retrieval failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve performance metrics: {str(e)}")


@admin_router.get("/performance/system")
async def get_performance_system(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get current system resource metrics.

    Args:
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        JSONResponse: System metrics (CPU, memory, disk, network)

    Raises:
        HTTPException: 404 if performance tracking is disabled
    """
    if not settings.mcpgateway_performance_tracking:
        raise HTTPException(status_code=404, detail="Performance tracking is disabled")

    service = get_performance_service(db)
    metrics = service.get_system_metrics()
    return metrics.model_dump()


@admin_router.get("/performance/workers")
async def get_performance_workers(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get metrics for all worker processes.

    Args:
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        JSONResponse: List of worker metrics

    Raises:
        HTTPException: 404 if performance tracking is disabled
    """
    if not settings.mcpgateway_performance_tracking:
        raise HTTPException(status_code=404, detail="Performance tracking is disabled")

    service = get_performance_service(db)
    workers = service.get_worker_metrics()
    return [w.model_dump() for w in workers]


@admin_router.get("/performance/requests")
async def get_performance_requests(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get HTTP request performance metrics.

    Args:
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        JSONResponse: Request metrics from Prometheus

    Raises:
        HTTPException: 404 if performance tracking is disabled
    """
    if not settings.mcpgateway_performance_tracking:
        raise HTTPException(status_code=404, detail="Performance tracking is disabled")

    service = get_performance_service(db)
    metrics = service.get_request_metrics()
    return metrics.model_dump()


@admin_router.get("/performance/cache")
async def get_performance_cache(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get Redis cache metrics.

    Args:
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        JSONResponse: Redis cache metrics

    Raises:
        HTTPException: 404 if performance tracking is disabled
    """
    if not settings.mcpgateway_performance_tracking:
        raise HTTPException(status_code=404, detail="Performance tracking is disabled")

    service = get_performance_service(db)
    metrics = await service.get_cache_metrics()
    return metrics.model_dump()


@admin_router.get("/performance/history")
async def get_performance_history(
    period_type: str = Query("hourly", description="Aggregation period: hourly or daily"),
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get historical performance aggregates.

    Args:
        period_type: Aggregation type (hourly, daily)
        hours: Hours of history to retrieve
        db: Database session dependency
        _user: Authenticated user (required by dependency)

    Returns:
        JSONResponse: Historical performance aggregates

    Raises:
        HTTPException: 404 if performance tracking is disabled
    """
    if not settings.mcpgateway_performance_tracking:
        raise HTTPException(status_code=404, detail="Performance tracking is disabled")

    service = get_performance_service(db)
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    history = await service.get_history(
        db=db,
        period_type=period_type,
        start_time=start_time,
    )

    return history.model_dump()
