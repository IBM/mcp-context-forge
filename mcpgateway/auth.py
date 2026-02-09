# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared authentication utilities.

This module provides common authentication functions that can be shared
across different parts of the application without creating circular imports.
"""

# Standard
import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import threading
import time
from typing import Any, Dict, Generator, List, Never, Optional
import uuid

# Third-Party
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, fresh_db_session, SessionLocal
from mcpgateway.plugins.framework import get_plugin_manager, GlobalContext, HttpAuthResolveUserPayload, HttpHeaderPayload, HttpHookType, PluginViolationError
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

# Security scheme
security = HTTPBearer(auto_error=False)


def _log_auth_event(
    logger: logging.Logger,
    message: str,
    level: int = logging.INFO,
    user_id: Optional[str] = None,
    auth_method: Optional[str] = None,
    auth_success: bool = False,
    security_event: Optional[str] = None,
    security_severity: str = "low",
    **extra_context,
) -> None:
    """Log authentication event with structured context and request_id.

    This helper creates structured log records that include request_id from the
    correlation ID context, enabling end-to-end tracing of authentication flows.

    Args:
        logger: Logger instance to use
        message: Log message
        level: Log level (default: INFO)
        user_id: User identifier
        auth_method: Authentication method used (jwt, api_token, etc.)
        auth_success: Whether authentication succeeded
        security_event: Type of security event (authentication, authorization, etc.)
        security_severity: Severity level (low, medium, high, critical)
        **extra_context: Additional context fields
    """
    # Get request_id from correlation ID context
    request_id = get_correlation_id()

    # Build structured log record
    extra = {
        "request_id": request_id,
        "entity_type": "auth",
        "auth_success": auth_success,
        "security_event": security_event or "authentication",
        "security_severity": security_severity,
    }

    if user_id:
        extra["user_id"] = user_id
    if auth_method:
        extra["auth_method"] = auth_method

    # Add any additional context
    extra.update(extra_context)

    # Log with structured context
    logger.log(level, message, extra=extra)


def get_db() -> Generator[Session, Never, None]:
    """Database dependency.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Examples:
        >>> db_gen = get_db()
        >>> db = next(db_gen)
        >>> hasattr(db, 'query')
        True
        >>> hasattr(db, 'close')
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


def _get_personal_team_sync(user_email: str) -> Optional[str]:
    """Synchronous helper to get user's personal team using a fresh DB session.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        user_email: The user's email address.

    Returns:
        The personal team ID, or None if not found.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeam, EmailTeamMember  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailTeam).join(EmailTeamMember).where(EmailTeamMember.user_email == user_email, EmailTeam.is_personal.is_(True)))
        personal_team = result.scalar_one_or_none()
        return personal_team.id if personal_team else None


def _get_user_team_ids_sync(email: str) -> List[str]:
    """Query all active team IDs for a user (including personal teams).

    Uses a fresh DB session so this can be called from thread pool.
    Matches the behavior of user.get_teams() which returns all active memberships.

    Args:
        email: User email address

    Returns:
        List of team ID strings
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeamMember  # pylint: disable=import-outside-toplevel

        result = db.execute(
            select(EmailTeamMember.team_id).where(
                EmailTeamMember.user_email == email,
                EmailTeamMember.is_active.is_(True),
            )
        )
        return [row[0] for row in result.all()]


def _resolve_teams_from_db_sync(email: str, is_admin: bool) -> Optional[List[str]]:
    """Resolve teams synchronously with L1 cache support.

    Used by StreamableHTTP transport which runs in a sync context.
    Checks the in-memory L1 cache before falling back to DB.

    Args:
        email: User email address
        is_admin: Whether the user is an admin

    Returns:
        None (admin bypass), [] (no teams), or list of team ID strings
    """
    if is_admin:
        return None  # Admin bypass

    cache_key = f"{email}:True"

    # Check L1 in-memory cache (sync-safe, no network I/O)
    try:
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

        entry = auth_cache._teams_list_cache.get(cache_key)  # pylint: disable=protected-access
        if entry and not entry.is_expired():
            auth_cache._hit_count += 1  # pylint: disable=protected-access
            return entry.value
    except Exception:  # nosec B110 - Cache unavailable is non-fatal
        pass

    # Cache miss: query DB
    team_ids = _get_user_team_ids_sync(email)

    # Populate L1 cache for subsequent requests
    try:
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache, CacheEntry  # pylint: disable=import-outside-toplevel

        with auth_cache._lock:  # pylint: disable=protected-access
            auth_cache._teams_list_cache[cache_key] = CacheEntry(  # pylint: disable=protected-access
                value=team_ids,
                expiry=time.time() + auth_cache._teams_list_ttl,  # pylint: disable=protected-access
            )
    except Exception:  # nosec B110 - Cache write failure is non-fatal
        pass

    return team_ids


async def _resolve_teams_from_db(email: str, user_info) -> Optional[List[str]]:
    """Resolve teams for session tokens from DB/cache.

    For admin users, returns None (admin bypass).
    For non-admin users, returns the full list of team IDs from DB/cache.

    Args:
        email: User email address
        user_info: User dict or EmailUser instance

    Returns:
        None (admin bypass), [] (no teams), or list of team ID strings
    """
    is_admin = user_info.get("is_admin", False) if isinstance(user_info, dict) else getattr(user_info, "is_admin", False)
    if is_admin:
        return None  # Admin bypass

    # Try auth cache first
    try:
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

        cached_teams = await auth_cache.get_user_teams(f"{email}:True")
        if cached_teams is not None:
            return cached_teams
    except Exception:  # nosec B110 - Cache unavailable is non-fatal, fall through to DB
        pass

    # Cache miss: query DB
    team_ids = await asyncio.to_thread(_get_user_team_ids_sync, email)

    # Cache the result
    try:
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

        await auth_cache.set_user_teams(f"{email}:True", team_ids)
    except Exception:  # nosec B110 - Cache write failure is non-fatal
        pass

    return team_ids


def normalize_token_teams(payload: Dict[str, Any]) -> Optional[List[str]]:
    """
    Normalize token teams to a canonical form for consistent security checks.

    SECURITY: This is the single source of truth for token team normalization.
    All code paths that read token teams should use this function.

    Rules:
    - "teams" key missing → [] (public-only, secure default)
    - "teams" is null + is_admin=true → None (admin bypass, sees all)
    - "teams" is null + is_admin=false → [] (public-only, no bypass for non-admins)
    - "teams" is [] → [] (explicit public-only)
    - "teams" is [...] → normalized list of string IDs

    Args:
        payload: The JWT payload dict

    Returns:
        None for admin bypass, [] for public-only, or list of normalized team ID strings
    """
    # Check if "teams" key exists (distinguishes missing from explicit null)
    if "teams" not in payload:
        # Missing teams key → public-only (secure default)
        return []

    teams = payload.get("teams")

    if teams is None:
        # Explicit null - only allow admin bypass if is_admin is true
        # Check BOTH top-level is_admin AND nested user.is_admin
        is_admin = payload.get("is_admin", False)
        if not is_admin:
            user_info = payload.get("user", {})
            is_admin = user_info.get("is_admin", False) if isinstance(user_info, dict) else False
        if is_admin:
            # Admin with explicit null teams → admin bypass (sees all)
            return None
        # Non-admin with null teams → public-only (no bypass)
        return []

    # teams is a list - normalize to string IDs
    # Handle both dict format [{"id": "team1"}] and string format ["team1"]
    normalized: List[str] = []
    for team in teams:
        if isinstance(team, dict):
            team_id = team.get("id")
            if team_id:
                normalized.append(str(team_id))
        elif isinstance(team, str):
            normalized.append(team)
    return normalized


async def get_team_from_token(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extract the team ID from an authentication token payload.

    SECURITY: This function uses secure-first defaults:
    - Missing teams key = public-only (no personal team fallback)
    - Empty teams list = public-only (no team access)
    - Teams with values = use first team ID

    This prevents privilege escalation where missing claims could grant
    unintended team access.

    Args:
        payload (Dict[str, Any]):
            The token payload. Expected fields:
            - "sub" (str): The user's unique identifier (email).
            - "teams" (List[str], optional): List containing team ID.

    Returns:
        Optional[str]:
            The resolved team ID. Returns `None` if teams is missing or empty.

    Examples:
        >>> import asyncio
        >>> # --- Case 1: Token has team ---
        >>> payload = {"sub": "user@example.com", "teams": ["team_456"]}
        >>> asyncio.run(get_team_from_token(payload))
        'team_456'

        >>> # --- Case 2: Token has explicit empty teams (public-only) ---
        >>> payload = {"sub": "user@example.com", "teams": []}
        >>> asyncio.run(get_team_from_token(payload))  # Returns None
        >>> # None

        >>> # --- Case 3: Token has no teams key (secure default) ---
        >>> payload = {"sub": "user@example.com"}
        >>> asyncio.run(get_team_from_token(payload))  # Returns None
        >>> # None
    """
    teams = payload.get("teams")

    # SECURITY: Treat missing teams as public-only (secure default)
    # - teams is None (missing key): Public-only (secure default, no legacy fallback)
    # - teams == [] (explicit empty list): Public-only, no team access
    # - teams == [...] (has teams): Use first team
    # Admin bypass is handled separately via is_admin flag in token, not via missing teams
    if teams is None or len(teams) == 0:
        # Missing teams or explicit empty = public-only, no fallback to personal team
        return None

    # Has teams - use the first one
    team_id = teams[0]
    if isinstance(team_id, dict):
        team_id = team_id.get("id")
    return team_id


def _check_token_revoked_sync(jti: str) -> bool:
    """Synchronous helper to check if a token is revoked.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        jti: The JWT ID to check.

    Returns:
        True if the token is revoked, False otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import TokenRevocation  # pylint: disable=import-outside-toplevel

        result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti))
        return result.scalar_one_or_none() is not None


# Small in-module TTL cache for legacy API-token JTI membership checks
# This avoids repeated fresh DB sessions for the same JTI within a short window.
_api_jti_cache: dict = {}
_api_jti_lock = threading.Lock()
_api_jti_ttl = getattr(settings, "auth_api_jti_ttl", 60)


def _lookup_api_token_sync(token_hash: str) -> Optional[Dict[str, Any]]:
    """Synchronous helper to look up an API token by hash.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        token_hash: SHA256 hash of the API token.

    Returns:
        Dict with token info if found and active, None otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailApiToken, utc_now  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailApiToken).where(EmailApiToken.token_hash == token_hash, EmailApiToken.is_active.is_(True)))
        api_token = result.scalar_one_or_none()

        if api_token:
            # Check expiration
            if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
                return {"expired": True}

            # Check revocation
            # First-Party
            from mcpgateway.db import TokenRevocation  # pylint: disable=import-outside-toplevel

            revoke_result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == api_token.jti))
            if revoke_result.scalar_one_or_none() is not None:
                return {"revoked": True}

            # Update last_used timestamp
            api_token.last_used = utc_now()
            db.commit()

            return {
                "user_email": api_token.user_email,
                "jti": api_token.jti,
            }
        return None


def _is_api_token_jti_sync(jti: str) -> bool:
    """Check if JTI belongs to an API token (legacy fallback) - SYNC version.

    Used for tokens created before auth_provider was added to the payload.
    Called via asyncio.to_thread() to avoid blocking the event loop.

    SECURITY: Fail-closed on DB errors. If we can't verify the token isn't
    an API token, treat it as one to preserve the hard-block policy.

    Args:
        jti: JWT ID to check

    Returns:
        bool: True if JTI exists in email_api_tokens table OR if lookup fails
    """
    # Third-Party
    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

    # First-Party
    from mcpgateway.db import EmailApiToken  # pylint: disable=import-outside-toplevel

    # Check small in-memory TTL cache first
    try:
        with _api_jti_lock:
            entry = _api_jti_cache.get(jti)
            if entry:
                value, expiry = entry
                if time.time() < expiry:
                    return value
                # expired
                _api_jti_cache.pop(jti, None)
    except Exception:
        pass

    # Cache miss: query DB and populate cache
    try:
        with fresh_db_session() as db:
            result = db.execute(select(EmailApiToken.id).where(EmailApiToken.jti == jti).limit(1))
            exists = result.scalar_one_or_none() is not None
            try:
                with _api_jti_lock:
                    _api_jti_cache[jti] = (exists, time.time() + _api_jti_ttl)
            except Exception:
                pass
            return exists
    except Exception as e:
        logging.getLogger(__name__).warning(f"Legacy API token check failed, failing closed: {e}")
        return True  # FAIL-CLOSED: treat as API token to preserve hard-block


def _get_user_by_email_sync(email: str) -> Optional[EmailUser]:
    """Synchronous helper to get user by email.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        email: The user's email address.

    Returns:
        EmailUser if found, None otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailUser).where(EmailUser.email == email))
        user = result.scalar_one_or_none()
        if user:
            # Detach from session and return a copy of attributes
            # since the session will be closed
            return EmailUser(
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                is_admin=user.is_admin,
                is_active=user.is_active,
                auth_provider=user.auth_provider,
                password_change_required=user.password_change_required,
                email_verified_at=user.email_verified_at,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        return None


def _get_auth_context_batched_sync(email: str, jti: Optional[str] = None) -> Dict[str, Any]:
    """Batched auth context lookup in a single DB session.

    Combines what were 3 separate asyncio.to_thread calls into 1:
    1. _get_user_by_email_sync - user data
    2. _get_personal_team_sync - personal team ID
    3. _check_token_revoked_sync - token revocation status
    4. _get_user_team_ids - all active team memberships (for session tokens)

    This reduces thread pool contention and DB connection overhead.

    Args:
        email: User email address
        jti: JWT ID for revocation check (optional)

    Returns:
        Dict with keys: user (dict or None), personal_team_id (str or None),
        is_token_revoked (bool), team_ids (list of str)

    Examples:
        >>> # This function runs in a thread pool
        >>> # result = _get_auth_context_batched_sync("test@example.com", "jti-123")
        >>> # result["is_token_revoked"]  # False if not revoked
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeam, EmailTeamMember, TokenRevocation, EmailApiToken  # pylint: disable=import-outside-toplevel

        result = {
            "user": None,
            "personal_team_id": None,
            "is_token_revoked": False,  # nosec B105 - boolean flag, not a password
            "team_ids": [],
        }

        # Query 1: Get user data
        user_result = db.execute(select(EmailUser).where(EmailUser.email == email))
        user = user_result.scalar_one_or_none()

        if user:
            # Detach user data as dict (session will close)
            result["user"] = {
                "email": user.email,
                "password_hash": user.password_hash,
                "full_name": user.full_name,
                "is_admin": user.is_admin,
                "is_active": user.is_active,
                "auth_provider": user.auth_provider,
                "password_change_required": user.password_change_required,
                "email_verified_at": user.email_verified_at,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            }

            # Query 2: Get personal team (only if user exists)
            team_result = db.execute(
                select(EmailTeam)
                .join(EmailTeamMember)
                .where(
                    EmailTeamMember.user_email == email,
                    EmailTeam.is_personal.is_(True),
                )
            )
            personal_team = team_result.scalar_one_or_none()
            if personal_team:
                result["personal_team_id"] = personal_team.id

            # Query 4: Get all active team memberships (for session token team resolution)
            team_ids_result = db.execute(
                select(EmailTeamMember.team_id).where(
                    EmailTeamMember.user_email == email,
                    EmailTeamMember.is_active.is_(True),
                )
            )
            result["team_ids"] = [row[0] for row in team_ids_result.all()]

        # Query 3: Check token revocation (if JTI provided)
        if jti:
            revoke_result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti))
            result["is_token_revoked"] = revoke_result.scalar_one_or_none() is not None

        # Query 5: Prime API-token JTI cache (legacy tokens)
        if jti:
            try:
                api_result = db.execute(select(EmailApiToken.id).where(EmailApiToken.jti == jti).limit(1))
                is_api_token = api_result.scalar_one_or_none() is not None
                try:
                    with _api_jti_lock:
                        _api_jti_cache[jti] = (is_api_token, time.time() + _api_jti_ttl)
                except Exception:
                    pass
            except Exception:
                # Don't fail the whole auth flow on caching errors
                pass

        return result


def _user_from_cached_dict(user_dict: Dict[str, Any]) -> EmailUser:
    """Create EmailUser instance from cached dict.

    Args:
        user_dict: User data dictionary from cache

    Returns:
        EmailUser instance (detached from any session)
    """
    return EmailUser(
        email=user_dict["email"],
        password_hash=user_dict.get("password_hash", ""),
        full_name=user_dict.get("full_name"),
        is_admin=user_dict.get("is_admin", False),
        is_active=user_dict.get("is_active", True),
        auth_provider=user_dict.get("auth_provider", "local"),
        password_change_required=user_dict.get("password_change_required", False),
        email_verified_at=user_dict.get("email_verified_at"),
        created_at=user_dict.get("created_at", datetime.now(timezone.utc)),
        updated_at=user_dict.get("updated_at", datetime.now(timezone.utc)),
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Optional[object] = None,
) -> EmailUser:
    """Get current authenticated user from JWT token with revocation checking.

    Supports plugin-based custom authentication via HTTP_AUTH_RESOLVE_USER hook.

    Args:
        credentials: HTTP authorization credentials
        request: Optional request object for plugin hooks

    Returns:
        EmailUser: Authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    logger = logging.getLogger(__name__)

    async def _set_auth_method_from_payload(payload: dict) -> None:
        """Set request.state.auth_method based on JWT payload.

        Args:
            payload: Decoded JWT payload
        """
        if not request:
            return

        # NOTE: Cannot use structural check (scopes dict) because email login JWTs
        # also have scopes dict (see email_auth.py:160)
        user_info = payload.get("user", {})
        auth_provider = user_info.get("auth_provider")

        if auth_provider == "api_token":
            request.state.auth_method = "api_token"
            return

        if auth_provider:
            # email, oauth, saml, or any other interactive auth provider
            request.state.auth_method = "jwt"
            return

        # Legacy API token fallback: check if JTI exists in API token table
        # This handles tokens created before auth_provider was added
        jti_for_check = payload.get("jti")
        if jti_for_check:
            is_legacy_api_token = await asyncio.to_thread(_is_api_token_jti_sync, jti_for_check)
            if is_legacy_api_token:
                request.state.auth_method = "api_token"
                logger.debug(f"Legacy API token detected via DB lookup (JTI: ...{jti_for_check[-8:]})")
            else:
                request.state.auth_method = "jwt"
        else:
            # No auth_provider or JTI; default to interactive
            request.state.auth_method = "jwt"

    # NEW: Custom authentication hook - allows plugins to provide alternative auth
    # This hook is invoked BEFORE standard JWT/API token validation
    try:
        # Get plugin manager singleton
        plugin_manager = get_plugin_manager()

        if plugin_manager and plugin_manager.has_hooks_for(HttpHookType.HTTP_AUTH_RESOLVE_USER):
            # Extract client information
            client_host = None
            client_port = None
            if request and hasattr(request, "client") and request.client:
                client_host = request.client.host
                client_port = request.client.port

            # Serialize credentials for plugin
            credentials_dict = None
            if credentials:
                credentials_dict = {
                    "scheme": credentials.scheme,
                    "credentials": credentials.credentials,
                }

            # Extract headers from request
            # Note: Middleware modifies request.scope["headers"], so request.headers
            # will automatically reflect any modifications made by HTTP_PRE_REQUEST hooks
            headers = {}
            if request and hasattr(request, "headers"):
                headers = dict(request.headers)

            # Get request ID from correlation ID context (set by CorrelationIDMiddleware)
            request_id = get_correlation_id()
            if not request_id:
                # Fallback chain for safety
                if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
                    request_id = request.state.request_id
                else:
                    request_id = uuid.uuid4().hex
                    logger.debug(f"Generated fallback request ID in get_current_user: {request_id}")

            # Get plugin contexts from request state if available
            global_context = getattr(request.state, "plugin_global_context", None) if request else None
            if not global_context:
                # Create global context
                global_context = GlobalContext(
                    request_id=request_id,
                    server_id=None,
                    tenant_id=None,
                )

            context_table = getattr(request.state, "plugin_context_table", None) if request else None

            # Invoke custom auth resolution hook
            # violations_as_exceptions=True so PluginViolationError is raised for explicit denials
            auth_result, context_table_result = await plugin_manager.invoke_hook(
                HttpHookType.HTTP_AUTH_RESOLVE_USER,
                payload=HttpAuthResolveUserPayload(
                    credentials=credentials_dict,
                    headers=HttpHeaderPayload(root=headers),
                    client_host=client_host,
                    client_port=client_port,
                ),
                global_context=global_context,
                local_contexts=context_table,
                violations_as_exceptions=True,  # Raise PluginViolationError for auth denials
            )

            # If plugin successfully authenticated user, return it
            if auth_result.modified_payload and isinstance(auth_result.modified_payload, dict):
                logger.info("User authenticated via plugin hook")
                # Create EmailUser from dict returned by plugin
                user_dict = auth_result.modified_payload
                user = EmailUser(
                    email=user_dict.get("email"),
                    password_hash=user_dict.get("password_hash", ""),
                    full_name=user_dict.get("full_name"),
                    is_admin=user_dict.get("is_admin", False),
                    is_active=user_dict.get("is_active", True),
                    auth_provider=user_dict.get("auth_provider", "local"),
                    password_change_required=user_dict.get("password_change_required", False),
                    email_verified_at=user_dict.get("email_verified_at"),
                    created_at=user_dict.get("created_at", datetime.now(timezone.utc)),
                    updated_at=user_dict.get("updated_at", datetime.now(timezone.utc)),
                )

                # Store auth_method in request.state so it can be accessed by RBAC middleware
                if request and auth_result.metadata:
                    auth_method = auth_result.metadata.get("auth_method")
                    if auth_method:
                        request.state.auth_method = auth_method
                        logger.debug(f"Stored auth_method '{auth_method}' in request.state")

                if request and context_table_result:
                    request.state.plugin_context_table = context_table_result

                if request and global_context:
                    request.state.plugin_global_context = global_context

                if plugin_manager and plugin_manager.config.plugin_settings.include_user_info:
                    _inject_userinfo_instate(request, user)

                return user
            # If continue_processing=True (no payload), fall through to standard auth

    except PluginViolationError as e:
        # Plugin explicitly denied authentication with custom message
        logger.warning(f"Authentication denied by plugin: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,  # Use plugin's custom error message
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log but don't fail on plugin errors - fall back to standard auth
        logger.warning(f"HTTP_AUTH_RESOLVE_USER hook failed, falling back to standard auth: {e}")

    # EXISTING: Standard authentication (JWT, API tokens)
    if not credentials:
        logger.warning("No credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("Attempting authentication with token: %s...", credentials.credentials[:20])
    email = None

    try:
        # Try JWT token first using the centralized verify_jwt_token_cached function
        logger.debug("Attempting JWT token validation")
        payload = await verify_jwt_token_cached(credentials.credentials, request)

        logger.debug("JWT token validated successfully")
        # Extract user identifier (support both new and legacy token formats)
        email = payload.get("sub")
        if email is None:
            # Try legacy format
            email = payload.get("email")

        if email is None:
            logger.debug("No email/sub found in JWT payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug("JWT authentication successful for email: %s", email)

        # Extract JTI for revocation check
        jti = payload.get("jti")

        # === AUTH CACHING: Check cache before DB queries ===
        if settings.auth_cache_enabled:
            try:
                # First-Party
                from mcpgateway.cache.auth_cache import auth_cache, CachedAuthContext  # pylint: disable=import-outside-toplevel

                cached_ctx = await auth_cache.get_auth_context(email, jti)
                if cached_ctx:
                    logger.debug(f"Auth cache hit for {email}")

                    # Check revocation from cache
                    if cached_ctx.is_token_revoked:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token has been revoked",
                            headers={"WWW-Authenticate": "Bearer"},
                        )

                    # Check user active status from cache
                    if cached_ctx.user and not cached_ctx.user.get("is_active", True):
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Account disabled",
                            headers={"WWW-Authenticate": "Bearer"},
                        )

                    # Resolve teams based on token_use
                    if request:
                        token_use = payload.get("token_use")
                        request.state.token_use = token_use

                        if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                            # Session token: resolve teams from DB/cache
                            user_info = cached_ctx.user or {"is_admin": False}
                            teams = await _resolve_teams_from_db(email, user_info)
                        else:
                            # API token or legacy: use embedded teams
                            teams = normalize_token_teams(payload)

                        request.state.token_teams = teams

                        # Set team_id: only for single-team API tokens
                        if teams is None:
                            request.state.team_id = None
                        elif len(teams) == 1 and token_use != "session":  # nosec B105
                            request.state.team_id = teams[0] if isinstance(teams[0], str) else teams[0].get("id")
                        else:
                            request.state.team_id = None

                        await _set_auth_method_from_payload(payload)

                    # Return user from cache
                    if cached_ctx.user:
                        # When require_user_in_db is enabled, verify user still exists in DB
                        # This prevents stale cache from bypassing strict mode
                        if settings.require_user_in_db:
                            db_user = await asyncio.to_thread(_get_user_by_email_sync, email)
                            if db_user is None:
                                logger.warning(
                                    f"Authentication rejected for {email}: cached user not found in database. " "REQUIRE_USER_IN_DB is enabled.",
                                    extra={"security_event": "user_not_in_db_rejected", "user_id": email},
                                )
                                raise HTTPException(
                                    status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="User not found in database",
                                    headers={"WWW-Authenticate": "Bearer"},
                                )

                        if plugin_manager and plugin_manager.config.plugin_settings.include_user_info:
                            _inject_userinfo_instate(request, _user_from_cached_dict(cached_ctx.user))

                        return _user_from_cached_dict(cached_ctx.user)

                    # User not in cache but context was (shouldn't happen, but handle it)
                    logger.debug("Auth context cached but user missing, falling through to DB")

            except HTTPException:
                raise
            except Exception as cache_error:
                logger.debug(f"Auth cache check failed, falling through to DB: {cache_error}")

        # === BATCHED QUERIES: Single DB call for user + team + revocation ===
        if settings.auth_cache_batch_queries:
            try:
                auth_ctx = await asyncio.to_thread(_get_auth_context_batched_sync, email, jti)

                # Check revocation
                if auth_ctx.get("is_token_revoked"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                # Resolve teams based on token_use
                token_use = payload.get("token_use")
                if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                    # Session token: use team_ids from batched query
                    user_dict = auth_ctx.get("user")
                    is_admin = user_dict.get("is_admin", False) if user_dict else False
                    if is_admin:
                        teams = None  # Admin bypass
                    else:
                        teams = auth_ctx.get("team_ids", [])
                else:
                    # API token or legacy: use embedded teams
                    teams = normalize_token_teams(payload)

                # Set team_id: only for single-team API tokens
                if teams is None:
                    team_id = None
                elif len(teams) == 1 and token_use != "session":  # nosec B105
                    team_id = teams[0] if isinstance(teams[0], str) else teams[0].get("id")
                else:
                    team_id = None

                if request:
                    request.state.token_teams = teams
                    request.state.team_id = team_id
                    request.state.token_use = token_use
                    await _set_auth_method_from_payload(payload)

                # Store in cache for future requests
                if settings.auth_cache_enabled:
                    try:
                        # First-Party
                        from mcpgateway.cache.auth_cache import auth_cache, CachedAuthContext  # noqa: F811 pylint: disable=import-outside-toplevel

                        await auth_cache.set_auth_context(
                            email,
                            jti,
                            CachedAuthContext(
                                user=auth_ctx.get("user"),
                                personal_team_id=auth_ctx.get("personal_team_id"),
                                is_token_revoked=auth_ctx.get("is_token_revoked", False),
                            ),
                        )
                        # Also populate teams-list cache so cached-path requests
                        # don't need an extra DB query via _resolve_teams_from_db()
                        if token_use == "session" and teams is not None:  # nosec B105
                            await auth_cache.set_user_teams(f"{email}:True", teams)
                    except Exception as cache_set_error:
                        logger.debug(f"Failed to cache auth context: {cache_set_error}")

                # Create user from batched result
                if auth_ctx.get("user"):
                    user_dict = auth_ctx["user"]
                    if not user_dict.get("is_active", True):
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Account disabled",
                            headers={"WWW-Authenticate": "Bearer"},
                        )
                    # Store user for return at end of function
                    # We'll check platform admin case and return below
                    _batched_user = _user_from_cached_dict(user_dict)
                else:
                    _batched_user = None

                # Handle user not found case
                if _batched_user is None:
                    # Check if strict user-in-DB mode is enabled
                    if settings.require_user_in_db:
                        logger.warning(
                            f"Authentication rejected for {email}: user not found in database. " "REQUIRE_USER_IN_DB is enabled.",
                            extra={"security_event": "user_not_in_db_rejected", "user_id": email},
                        )
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found in database",
                            headers={"WWW-Authenticate": "Bearer"},
                        )

                    # Platform admin bootstrap (only when REQUIRE_USER_IN_DB=false)
                    if email == getattr(settings, "platform_admin_email", "admin@example.com"):
                        logger.info(
                            f"Platform admin bootstrap authentication for {email}. " "User authenticated via platform admin configuration.",
                            extra={"security_event": "platform_admin_bootstrap", "user_id": email},
                        )
                        _batched_user = EmailUser(
                            email=email,
                            password_hash="",  # nosec B106
                            full_name=getattr(settings, "platform_admin_full_name", "Platform Administrator"),
                            is_admin=True,
                            is_active=True,
                            auth_provider="local",
                            password_change_required=False,
                            email_verified_at=datetime.now(timezone.utc),
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found",
                            headers={"WWW-Authenticate": "Bearer"},
                        )

                if plugin_manager and plugin_manager.config.plugin_settings.include_user_info:
                    _inject_userinfo_instate(request, _batched_user)

                return _batched_user

            except HTTPException:
                raise
            except Exception as batch_error:
                logger.warning(f"Batched auth query failed, falling back to individual queries: {batch_error}")

        # === FALLBACK: Original individual queries (if batching disabled or failed) ===
        if jti:
            try:
                is_revoked = await asyncio.to_thread(_check_token_revoked_sync, jti)
                if is_revoked:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except HTTPException:
                raise
            except Exception as revoke_check_error:
                # Log the error but don't fail authentication for admin tokens
                logger.warning(f"Token revocation check failed for JTI {jti}: {revoke_check_error}")

        # Resolve teams based on token_use
        token_use = payload.get("token_use")
        if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
            # Session token: resolve teams from DB/cache (fallback path — separate query OK)
            user_info = {"is_admin": payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)}
            normalized_teams = await _resolve_teams_from_db(email, user_info)
        else:
            # API token or legacy: use embedded teams
            normalized_teams = normalize_token_teams(payload)

        # Set team_id: only for single-team API tokens
        if normalized_teams is None:
            team_id = None
        elif len(normalized_teams) == 1 and token_use != "session":  # nosec B105
            team_id = normalized_teams[0] if isinstance(normalized_teams[0], str) else normalized_teams[0].get("id")
        else:
            team_id = None

        if request:
            request.state.token_teams = normalized_teams
            request.state.team_id = team_id
            request.state.token_use = token_use
            await _set_auth_method_from_payload(payload)

    except HTTPException:
        # Re-raise HTTPException from verify_jwt_token (handles expired/invalid tokens)
        raise
    except Exception as jwt_error:
        # JWT validation failed, try database API token
        # Uses fresh DB session via asyncio.to_thread to avoid blocking event loop
        logger.debug("JWT validation failed with error: %s, trying database API token", jwt_error)
        try:
            token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            logger.debug("Generated token hash: %s", token_hash)

            # Lookup API token using fresh session in thread pool
            api_token_info = await asyncio.to_thread(_lookup_api_token_sync, token_hash)
            logger.debug(f"Database lookup result: {api_token_info is not None}")

            if api_token_info:
                # Check for error conditions returned by helper
                if api_token_info.get("expired"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token expired",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                if api_token_info.get("revoked"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                # Use the email from the API token
                email = api_token_info["user_email"]
                logger.debug(f"API token authentication successful for email: {email}")

                # Set auth_method for database API tokens
                if request:
                    request.state.auth_method = "api_token"
            else:
                logger.debug("API token not found in database")
                logger.debug("No valid authentication method found")
                # Neither JWT nor API token worked
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Neither JWT nor API token validation worked
            logger.debug(f"Database API token validation failed with exception: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Get user from database using fresh session in thread pool
    user = await asyncio.to_thread(_get_user_by_email_sync, email)

    if user is None:
        # Check if strict user-in-DB mode is enabled
        if settings.require_user_in_db:
            logger.warning(
                f"Authentication rejected for {email}: user not found in database. " "REQUIRE_USER_IN_DB is enabled.",
                extra={"security_event": "user_not_in_db_rejected", "user_id": email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found in database",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Platform admin bootstrap (only when REQUIRE_USER_IN_DB=false)
        # If user doesn't exist but token is valid and email matches platform admin,
        # create a virtual admin user object
        if email == getattr(settings, "platform_admin_email", "admin@example.com"):
            logger.info(
                f"Platform admin bootstrap authentication for {email}. " "User authenticated via platform admin configuration.",
                extra={"security_event": "platform_admin_bootstrap", "user_id": email},
            )
            # Create a virtual admin user for authentication purposes
            user = EmailUser(
                email=email,
                password_hash="",  # nosec B106 - Not used for JWT authentication
                full_name=getattr(settings, "platform_admin_full_name", "Platform Administrator"),
                is_admin=True,
                is_active=True,
                auth_provider="local",
                password_change_required=False,
                email_verified_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if plugin_manager and plugin_manager.config.plugin_settings.include_user_info:
        _inject_userinfo_instate(request, user)

    return user


def _inject_userinfo_instate(request: Optional[object] = None, user: Optional[EmailUser] = None) -> None:
    """This function injects user related information into the plugin_global_context, if the config has
    include_user_info key set as true.

    Args:
        request: Optional request object for plugin hooks
        user: User related information
    """

    logger = logging.getLogger(__name__)
    # Get request ID from correlation ID context (set by CorrelationIDMiddleware)
    request_id = get_correlation_id()
    if not request_id:
        # Fallback chain for safety
        if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
            request_id = request.state.request_id
        else:
            request_id = uuid.uuid4().hex
            logger.debug(f"Generated fallback request ID in get_current_user: {request_id}")

    # Get plugin contexts from request state if available
    global_context = getattr(request.state, "plugin_global_context", None) if request else None
    if not global_context:
        # Create global context
        global_context = GlobalContext(
            request_id=request_id,
            server_id=None,
            tenant_id=None,
        )

    if user:
        if not global_context.user:
            global_context.user = {}
        global_context.user["email"] = user.email
        global_context.user["is_admin"] = user.is_admin
        global_context.user["full_name"] = user.full_name

    if request and global_context:
        request.state.plugin_global_context = global_context
