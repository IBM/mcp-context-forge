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
from typing import Any, Dict, Generator, List, Never, Optional
import uuid

# Third-Party
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette.requests import Request

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, fresh_db_session, SessionLocal
from mcpgateway.plugins.framework import get_plugin_manager, GlobalContext, HttpAuthResolveUserPayload, HttpHeaderPayload, HttpHookType, PluginViolationError, UserContext
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.trace_context import (
    clear_trace_context,
    set_trace_auth_method,
    set_trace_context_from_teams,
    set_trace_team_scope,
    set_trace_user_email,
    set_trace_user_is_admin,
)
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

# Security scheme
security = HTTPBearer(auto_error=False)

# Module-level sync Redis client for rate-limiting (lazy-initialized)
_SYNC_REDIS_CLIENT = None  # pylint: disable=invalid-name
_SYNC_REDIS_LOCK = threading.Lock()
_SYNC_REDIS_FAILURE_TIME: Optional[float] = None  # Backoff after connection failures

# Module-level in-memory cache for last_used rate-limiting (fallback when Redis unavailable)
_LAST_USED_CACHE: dict = {}
_LAST_USED_CACHE_LOCK = threading.Lock()


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


def _get_team_name_by_id_sync(team_id: Optional[str]) -> Optional[str]:
    """Return the active team display name for a team ID.

    Args:
        team_id: Team identifier to resolve.

    Returns:
        Team display name when the active team exists, otherwise ``None``.
    """
    if not team_id:
        return None

    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeam  # pylint: disable=import-outside-toplevel

        result = db.execute(
            select(EmailTeam.name).where(
                EmailTeam.id == team_id,
                EmailTeam.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()


def _extract_claim_team_name(payload: Dict[str, Any], team_id: Optional[str]) -> Optional[str]:
    """Extract a matching team display name from raw JWT team claims.

    Args:
        payload: Decoded JWT payload.
        team_id: Normalized primary team identifier to match.

    Returns:
        Matching team display name from the JWT claims, if present.
    """
    if not team_id:
        return None

    raw_teams = payload.get("teams")
    if not isinstance(raw_teams, list):
        return None

    for raw_team in raw_teams:
        raw_team_id = None
        raw_team_name = None
        if isinstance(raw_team, dict):
            raw_team_id = raw_team.get("id")
            raw_team_name = raw_team.get("name")
        elif isinstance(raw_team, str):
            raw_team_id = raw_team

        if str(raw_team_id).strip() != team_id:
            continue

        if raw_team_name is None:
            return None

        normalized_name = str(raw_team_name).strip()
        return normalized_name or None

    return None


async def resolve_trace_team_name(
    payload: Dict[str, Any],
    token_teams: Optional[List[str]],
    *,
    preresolved_team_names: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Resolve the primary team display name for tracing.

    The primary team name is additive trace metadata only. It does not affect
    scope enforcement, which continues to rely on canonical team IDs. For
    session tokens, DB-resolved membership is authoritative and raw JWT team
    display names are only used as a best-effort fallback for non-session
    tokens when no canonical name can be resolved.

    Args:
        payload: Decoded JWT payload.
        token_teams: Canonical resolved team IDs, or ``None`` for admin scope.
        preresolved_team_names: Optional mapping of team_id to display name from
            a batched DB lookup.

    Returns:
        Display name for the primary concrete team, or ``None`` for public/admin
        scopes or when the name cannot be resolved.
    """
    if not token_teams:
        return None

    primary_team_id = token_teams[0]
    if preresolved_team_names:
        resolved_name = preresolved_team_names.get(primary_team_id)
        if resolved_name:
            return resolved_name

    try:
        resolved_name = await asyncio.to_thread(_get_team_name_by_id_sync, primary_team_id)
        if resolved_name:
            return resolved_name
    except Exception as exc:
        logging.getLogger(__name__).debug("Failed to resolve trace team name for team_id=%s: %s", primary_team_id, exc)

    if payload.get("token_use") == "session":
        return None

    claim_team_name = _extract_claim_team_name(payload, primary_team_id)
    if claim_team_name:
        return claim_team_name

    return None


def get_user_team_roles(db, user_email: str) -> Dict[str, str]:
    """Return a {team_id: role} mapping for a user's active team memberships.

    Args:
        db: SQLAlchemy database session.
        user_email: Email address of the user to query memberships for.

    Returns:
        Dict mapping team_id to the user's role in that team.
        Returns empty dict on DB errors (safe default — headers stay masked).
    """
    try:
        # First-Party
        from mcpgateway.db import EmailTeamMember  # pylint: disable=import-outside-toplevel

        rows = db.query(EmailTeamMember.team_id, EmailTeamMember.role).filter(EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)).all()
        return {r.team_id: r.role for r in rows}
    except Exception:
        return {}


def _narrow_by_jwt_teams(payload: Dict[str, Any], db_teams: Optional[List[str]]) -> Optional[List[str]]:
    """Apply JWT intersection policy to DB-resolved teams.

    If *db_teams* is ``None`` (admin bypass), returns ``None`` immediately.
    If the JWT ``teams`` claim is a non-empty list, returns the intersection
    of *db_teams* and the JWT teams.  If the intersection is empty (e.g.
    all JWT-claimed teams have been revoked), returns ``[]`` so that
    downstream enforcement denies the request rather than silently
    broadening scope.

    Args:
        payload: The decoded JWT payload dict.
        db_teams: Teams resolved from the database, or ``None`` for admin bypass.

    Returns:
        None (admin bypass), [] (public-only / empty intersection), or list of team ID strings.
    """
    if db_teams is None:
        return None

    jwt_teams = payload.get("teams")
    if isinstance(jwt_teams, list) and jwt_teams:
        # Non-empty JWT teams → intersect with DB teams.  An empty
        # intersection (all JWT teams revoked) returns [], which gives
        # public-only access and lets downstream enforcement deny the
        # request (fail-closed).
        jwt_team_set = set(normalize_token_teams({"teams": jwt_teams}) or [])
        return [t for t in db_teams if t in jwt_team_set]

    # JWT teams absent, null, or empty list → no narrowing requested.
    # An explicit ``teams: []`` means "don't restrict by team" (i.e. use
    # the full DB membership), which intentionally differs from
    # ``normalize_token_teams`` where ``[] → public-only``.  The
    # distinction exists because session tokens always start from DB-
    # resolved teams — an empty JWT claim simply means the caller did not
    # request a subset.
    return db_teams


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


_UNSET: Any = object()  # sentinel distinguishing "not supplied" from explicit None


async def resolve_session_teams(
    payload: Dict[str, Any],
    email: Optional[str],
    user_info,
    *,
    preresolved_db_teams: Optional[List[str]] = _UNSET,
) -> Optional[List[str]]:
    """Resolve teams for a session token, using DB as the authority.

    The database is always consulted first so that revoked team memberships
    take effect immediately.  If the JWT carries a ``teams`` claim, the
    result is narrowed to the **intersection** of the DB teams and the JWT
    teams — this lets callers scope a session to a subset of their actual
    memberships (e.g. single-team mode) without risking stale grants.

    This is the **single policy point** for session-token team resolution.
    All code paths that need teams for a session token should call this
    function rather than inlining the decision.

    If *email* is ``None`` or empty, returns ``[]`` (public-only).  An
    identity-less session token never receives admin bypass — there is no
    user to resolve from the database.

    Policy:
        1. If *email* is falsy, return ``[]`` immediately (public-only).
        2. Resolve teams from DB/cache (``_resolve_teams_from_db``), or
           use *preresolved_db_teams* when the caller already fetched them
           (e.g. via a batched query).
        3. If DB returns ``None`` (admin bypass), return ``None``.
        4. If the JWT ``teams`` claim is a non-empty list, intersect with
           DB teams.  If the intersection is empty (all JWT-claimed teams
           revoked), return ``[]`` so downstream enforcement denies the
           request.
        5. Otherwise return the full DB result.

    Args:
        payload: The decoded JWT payload dict.
        email: User email address (for the DB lookup), or ``None``.
        user_info: User dict or EmailUser instance (for admin detection).
        preresolved_db_teams: If the caller already resolved DB teams (e.g.
            from a batched query), pass them here to skip the DB call.
            Pass ``None`` to indicate admin bypass was already determined.

    Returns:
        None (admin bypass), [] (public-only), or list of team ID strings.
    """
    if not email:
        return []  # No identity — public-only; never admin bypass
    if preresolved_db_teams is not _UNSET:
        db_teams: Optional[List[str]] = preresolved_db_teams
    else:
        db_teams = await _resolve_teams_from_db(email, user_info)

    return _narrow_by_jwt_teams(payload, db_teams)


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

        if not api_token:
            return None

        # Check expiration
        if api_token.expires_at:
            expires_at = api_token.expires_at.replace(tzinfo=timezone.utc) if api_token.expires_at.tzinfo is None else api_token.expires_at
            if utc_now() > expires_at:
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


def _get_sync_redis_client():
    """Get or create module-level synchronous Redis client for rate-limiting.

    Returns:
        Redis client or None if Redis is unavailable/disabled.
    """
    global _SYNC_REDIS_CLIENT, _SYNC_REDIS_FAILURE_TIME  # pylint: disable=global-statement

    # Standard
    import logging as log  # pylint: disable=import-outside-toplevel,reimported
    import time  # pylint: disable=import-outside-toplevel

    # First-Party
    from mcpgateway.config import settings as config_settings  # pylint: disable=import-outside-toplevel,reimported

    # Quick check without lock
    if _SYNC_REDIS_CLIENT is not None or not (config_settings.redis_url and config_settings.redis_url.strip() and config_settings.cache_type == "redis"):
        return _SYNC_REDIS_CLIENT

    # Backoff after recent failure (30 seconds)
    if _SYNC_REDIS_FAILURE_TIME and (time.time() - _SYNC_REDIS_FAILURE_TIME < 30):
        return None

    # Lazy initialization with lock
    with _SYNC_REDIS_LOCK:
        # Double-check after acquiring lock
        if _SYNC_REDIS_CLIENT is not None:
            return _SYNC_REDIS_CLIENT

        try:
            # Third-Party
            import redis  # pylint: disable=import-outside-toplevel

            _SYNC_REDIS_CLIENT = redis.from_url(config_settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
            # Test connection
            _SYNC_REDIS_CLIENT.ping()
            _SYNC_REDIS_FAILURE_TIME = None  # Clear failure state on success
            log.getLogger(__name__).debug("Sync Redis client initialized for API token rate-limiting")
        except Exception as e:
            log.getLogger(__name__).debug(f"Sync Redis client unavailable: {e}")
            _SYNC_REDIS_CLIENT = None
            _SYNC_REDIS_FAILURE_TIME = time.time()

    return _SYNC_REDIS_CLIENT


def _update_api_token_last_used_sync(jti: str) -> None:
    """Update last_used timestamp for an API token with rate-limiting.

    This function is called when an API token is successfully validated via JWT,
    ensuring the last_used field stays current for monitoring and security audits.

    Rate-limiting: Uses Redis cache (or in-memory fallback) to track the last
    update time and only writes to the database if the configured interval has
    elapsed. This prevents excessive DB writes on high-traffic tokens.

    Args:
        jti: JWT ID of the API token

    Note:
        Called via asyncio.to_thread() to avoid blocking the event loop.
        Uses fresh_db_session() for thread-safe database access.
    """
    # Standard
    import time  # pylint: disable=import-outside-toplevel,redefined-outer-name

    # First-Party
    from mcpgateway.config import settings as config_settings  # pylint: disable=import-outside-toplevel,reimported

    # Rate-limiting cache key
    cache_key = f"api_token_last_used:{jti}"
    update_interval_seconds = config_settings.token_last_used_update_interval_minutes * 60

    # Try Redis rate-limiting first (if available)
    redis_client = _get_sync_redis_client()
    if redis_client:
        try:
            last_update = redis_client.get(cache_key)
            if last_update:
                # Check if enough time has elapsed
                time_since_update = time.time() - float(last_update)
                if time_since_update < update_interval_seconds:
                    return  # Skip update - too soon

            # Update DB and cache
            with fresh_db_session() as db:
                # Third-Party
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.db import EmailApiToken, utc_now  # pylint: disable=import-outside-toplevel

                result = db.execute(select(EmailApiToken).where(EmailApiToken.jti == jti))
                api_token = result.scalar_one_or_none()
                if api_token:
                    api_token.last_used = utc_now()
                    db.commit()
                    # Update Redis cache with current timestamp
                    redis_client.setex(cache_key, update_interval_seconds * 2, str(time.time()))
            return
        except Exception as exc:
            # Redis failed, fall through to in-memory cache
            logger = logging.getLogger(__name__)
            logger.debug("Redis unavailable for API token rate-limiting, using in-memory fallback: %s", exc)

    # Fallback: In-memory cache (module-level dict with threading.Lock for thread-safety)
    # Note: This is per-process and won't work in multi-worker deployments
    # but provides basic rate-limiting when Redis is unavailable
    max_cache_size = 1024  # Prevent unbounded growth

    with _LAST_USED_CACHE_LOCK:
        last_update = _LAST_USED_CACHE.get(jti)
        if last_update:
            time_since_update = time.time() - last_update
            if time_since_update < update_interval_seconds:
                return  # Skip update - too soon

    # Update DB and cache
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailApiToken, utc_now  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailApiToken).where(EmailApiToken.jti == jti))
        api_token = result.scalar_one_or_none()
        if api_token:
            api_token.last_used = utc_now()
            db.commit()
            # Update in-memory cache (with lock for thread-safety)
            with _LAST_USED_CACHE_LOCK:
                if len(_LAST_USED_CACHE) >= max_cache_size:
                    # Evict oldest entries (by timestamp value)
                    sorted_keys = sorted(_LAST_USED_CACHE, key=_LAST_USED_CACHE.get)  # type: ignore[arg-type]
                    for k in sorted_keys[: len(_LAST_USED_CACHE) // 2]:
                        del _LAST_USED_CACHE[k]
                _LAST_USED_CACHE[jti] = time.time()


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

    try:
        with fresh_db_session() as db:
            result = db.execute(select(EmailApiToken.id).where(EmailApiToken.jti == jti).limit(1))
            return result.scalar_one_or_none() is not None
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


def _resolve_plugin_authenticated_user_sync(user_dict: Dict[str, Any]) -> Optional[EmailUser]:
    """Resolve plugin-authenticated user against database-backed identity state.

    Plugin hooks may authenticate a request and return identity claims. This
    helper enforces that admin status is always derived from the database record.

    Behavior:
    - Existing DB user: return DB user (authoritative for is_admin/is_active).
    - Missing DB user and REQUIRE_USER_IN_DB=true: reject (None).
    - Missing DB user and REQUIRE_USER_IN_DB=false: allow a non-admin virtual
      user built from non-privileged plugin claims.

    Args:
        user_dict: Identity claims returned by plugin auth hook.

    Returns:
        EmailUser when identity is accepted, otherwise None.
    """
    email = str(user_dict.get("email") or "").strip()
    if not email:
        return None

    db_user = _get_user_by_email_sync(email)
    if db_user:
        return db_user

    if settings.require_user_in_db:
        return None

    return EmailUser(
        email=email,
        password_hash=user_dict.get("password_hash", ""),
        full_name=user_dict.get("full_name"),
        is_admin=False,
        is_active=user_dict.get("is_active", True),
        auth_provider=user_dict.get("auth_provider", "local"),
        password_change_required=user_dict.get("password_change_required", False),
        email_verified_at=user_dict.get("email_verified_at"),
        created_at=user_dict.get("created_at", datetime.now(timezone.utc)),
        updated_at=user_dict.get("updated_at", datetime.now(timezone.utc)),
    )


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
        is_token_revoked (bool), team_ids (list of str), team_names (dict)

    Examples:
        >>> # This function runs in a thread pool
        >>> # result = _get_auth_context_batched_sync("test@example.com", "jti-123")
        >>> # result["is_token_revoked"]  # False if not revoked
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeam, EmailTeamMember, TokenRevocation  # pylint: disable=import-outside-toplevel

        result = {
            "user": None,
            "personal_team_id": None,
            "is_token_revoked": False,  # nosec B105 - boolean flag, not a password
            "team_ids": [],
            "team_names": {},
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
                select(EmailTeamMember.team_id, EmailTeam.name)
                .join(EmailTeam, EmailTeam.id == EmailTeamMember.team_id)
                .where(
                    EmailTeamMember.user_email == email,
                    EmailTeamMember.is_active.is_(True),
                    EmailTeam.is_active.is_(True),
                )
            )
            team_rows = team_ids_result.all()
            team_ids: list[str] = []
            team_names: dict[str, str] = {}

            for row in team_rows:
                team_id = None
                team_name = None

                mapping = getattr(row, "_mapping", None)
                if mapping is not None:
                    team_id = mapping.get("team_id")
                    team_name = mapping.get("name")

                if team_id is None:
                    team_id = getattr(row, "team_id", None)
                if team_name is None:
                    team_name = getattr(row, "name", None)

                if team_id is None and isinstance(row, tuple):
                    team_id = row[0] if len(row) > 0 else None
                    team_name = row[1] if len(row) > 1 else None

                if not team_id:
                    continue

                team_id_str = str(team_id)
                team_ids.append(team_id_str)
                if team_name:
                    team_names[team_id_str] = str(team_name)

            result["team_ids"] = team_ids
            result["team_names"] = team_names

        # Query 3: Check token revocation (if JTI provided)
        if jti:
            revoke_result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti))
            result["is_token_revoked"] = revoke_result.scalar_one_or_none() is not None

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
    request: Request = None,  # type: ignore[assignment]
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
    clear_trace_context()

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
            jti = payload.get("jti")
            if jti:
                request.state.jti = jti
                try:
                    await asyncio.to_thread(_update_api_token_last_used_sync, jti)
                except Exception as e:
                    logger.debug(f"Failed to update API token last_used: {e}")
                    # Continue authentication - last_used update is not critical
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
                request.state.jti = jti_for_check
                logger.debug(f"Legacy API token detected via DB lookup (JTI: ...{jti_for_check[-8:]})")
                try:
                    await asyncio.to_thread(_update_api_token_last_used_sync, jti_for_check)
                except Exception as e:
                    logger.debug(f"Failed to update legacy API token last_used: {e}")
                    # Continue authentication - last_used update is not critical
            else:
                request.state.auth_method = "jwt"
        else:
            # No auth_provider or JTI; default to interactive
            request.state.auth_method = "jwt"

    def _set_trace_for_user(user_obj: EmailUser, *, teams: Any = _UNSET, auth_method: Optional[str] = None, team_name: Optional[str] = None) -> None:
        """Populate trace context from the resolved user and request state.

        Args:
            user_obj: Resolved authenticated user object.
            teams: Optional resolved team scope override. When unset, team scope is derived from the user object.
            auth_method: Optional explicit authentication method label to record on the trace.
            team_name: Optional display name for the primary concrete team.
        """
        resolved_auth_method = auth_method
        if resolved_auth_method is None and request:
            resolved_auth_method = getattr(request.state, "auth_method", None)

        if teams is not _UNSET:
            set_trace_context_from_teams(
                teams,
                user_email=user_obj.email,
                is_admin=bool(user_obj.is_admin),
                auth_method=resolved_auth_method,
                team_name=team_name,
            )
            return

        set_trace_user_email(user_obj.email)
        set_trace_user_is_admin(bool(user_obj.is_admin))
        if resolved_auth_method:
            set_trace_auth_method(resolved_auth_method)
        if user_obj.is_admin:
            set_trace_team_scope("admin")

    # NEW: Custom authentication hook - allows plugins to provide alternative auth
    # This hook is invoked BEFORE standard JWT/API token validation
    try:
        # Get plugin manager singleton
        plugin_manager = await get_plugin_manager()

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
                # Propagate team_id → tenant_id for by_tenant rate limiting
                team_id = getattr(getattr(request, "state", None), "team_id", None) if request else None
                # Extract content type from headers
                content_type = headers.get("content-type") if headers else None
                global_context = GlobalContext(
                    request_id=request_id,
                    server_id=None,
                    tenant_id=team_id,
                    content_type=content_type,
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
                # Resolve plugin claims against DB state so admin flags are authoritative.
                user_dict = auth_result.modified_payload
                user = await asyncio.to_thread(_resolve_plugin_authenticated_user_sync, user_dict)

                if user is None:
                    logger.warning("Plugin auth rejected: user identity could not be resolved against DB policy")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User not found in database",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                if not user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Account disabled",
                        headers={"WWW-Authenticate": "Bearer"},
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

                _inject_userinfo_instate(request, user)
                _propagate_tenant_id(request)

                _set_trace_for_user(user)
                return user
            # If continue_processing=True (no payload), fall through to standard auth

    except PluginViolationError as e:
        # Plugin explicitly denied authentication with custom message
        logger.warning(f"Authentication denied by plugin: {SecurityValidator.sanitize_log_message(e.message)}")
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
        logger.warning(f"HTTP_AUTH_RESOLVE_USER hook failed, falling back to standard auth: {SecurityValidator.sanitize_log_message(str(e))}")

    # EXISTING: Standard authentication (JWT, API tokens)
    if not credentials:
        logger.warning("No credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("Attempting authentication with bearer credentials")
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
                            teams = await resolve_session_teams(payload, email, user_info)
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

                        request.state.trace_team_name = await resolve_trace_team_name(payload, teams)

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

                        _inject_userinfo_instate(request, _user_from_cached_dict(cached_ctx.user))
                        _propagate_tenant_id(request)

                        cached_user = _user_from_cached_dict(cached_ctx.user)
                        _set_trace_for_user(
                            cached_user,
                            teams=getattr(request.state, "token_teams", _UNSET) if request else _UNSET,
                            team_name=getattr(request.state, "trace_team_name", None) if request else None,
                        )
                        return cached_user

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
                    # Session token: use team_ids from batched query via resolve_session_teams
                    user_dict = auth_ctx.get("user")
                    is_admin = user_dict.get("is_admin", False) if user_dict else False
                    batch_teams = None if is_admin else auth_ctx.get("team_ids", [])
                    teams = await resolve_session_teams(payload, email, {"is_admin": is_admin}, preresolved_db_teams=batch_teams)
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
                    request.state.trace_team_name = await resolve_trace_team_name(payload, teams, preresolved_team_names=auth_ctx.get("team_names"))
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
                        # Cache the raw DB teams (batch_teams), not the narrowed
                        # intersection (teams), so that other sessions for the same
                        # user see the full membership and can narrow independently.
                        if token_use == "session" and batch_teams is not None:  # nosec B105
                            await auth_cache.set_user_teams(f"{email}:True", batch_teams)
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

                _inject_userinfo_instate(request, _batched_user)
                _propagate_tenant_id(request)

                _set_trace_for_user(
                    _batched_user,
                    teams=getattr(request.state, "token_teams", _UNSET) if request else _UNSET,
                    team_name=getattr(request.state, "trace_team_name", None) if request else None,
                )
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
                # Fail-secure: if the revocation check itself errors, reject the token.
                # Allowing through on error would let revoked tokens bypass enforcement
                # when the DB is unreachable or the table is missing.
                logger.warning(
                    f"Token revocation check failed for JTI {SecurityValidator.sanitize_log_message(jti)} — denying access (fail-secure): {SecurityValidator.sanitize_log_message(str(revoke_check_error))}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token validation failed",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Resolve teams based on token_use
        token_use = payload.get("token_use")
        if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
            # Session token: resolve teams from DB/cache (fallback path — separate query OK)
            user_info = {"is_admin": payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)}
            normalized_teams = await resolve_session_teams(payload, email, user_info)
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
            request.state.trace_team_name = await resolve_trace_team_name(payload, normalized_teams)
            # Store JTI for use in middleware (e.g., token usage logging)
            if jti:
                request.state.jti = jti
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
                    request.state.user_email = api_token_info["user_email"]
                    # Store JTI for use in middleware
                    if "jti" in api_token_info:
                        request.state.jti = api_token_info["jti"]
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
            logger.debug(f"Database API token validation failed with exception: {SecurityValidator.sanitize_log_message(str(e))}")
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

    _inject_userinfo_instate(request, user)
    _propagate_tenant_id(request)

    trace_teams = getattr(request.state, "token_teams", _UNSET) if request else _UNSET
    _set_trace_for_user(user, teams=trace_teams, team_name=getattr(request.state, "trace_team_name", None) if request else None)
    return user


def _propagate_tenant_id(request: Optional[object] = None) -> None:
    """Propagate request.state.team_id into GlobalContext.tenant_id for rate limiting.

    Called unconditionally at every return path in get_current_user() — unlike
    _inject_userinfo_instate() which is gated by include_user_info.  This
    ensures by_tenant rate limiting works even when include_user_info is False
    (the default) and the middleware has already created plugin_global_context.

    Only writes when tenant_id is still None (no overwrite of plugin-set values).

    Args:
        request: The incoming request object, or ``None`` if unavailable.
    """
    if not request:
        return
    global_context = getattr(getattr(request, "state", None), "plugin_global_context", None)
    if global_context and global_context.tenant_id is None:
        team_id = getattr(getattr(request, "state", None), "team_id", None)
        if team_id:
            global_context.tenant_id = team_id


def _inject_userinfo_instate(request: Optional[object] = None, user: Optional[EmailUser] = None) -> None:
    """Inject user identity into the plugin_global_context.

    Always populates both the legacy ``global_context.user`` dict (for backward
    compatibility) and the new structured ``global_context.user_context``
    (:class:`UserContext`).

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
        # Extract content type from request headers
        content_type = request.headers.get("content-type") if request and hasattr(request, "headers") else None
        # Create global context
        global_context = GlobalContext(
            request_id=request_id,
            server_id=None,
            tenant_id=None,
            content_type=content_type,
        )

    if user:
        # Backward-compatible dict population
        if not global_context.user:
            global_context.user = {}
        global_context.user["email"] = user.email
        global_context.user["is_admin"] = user.is_admin
        global_context.user["full_name"] = user.full_name

        # Build structured UserContext
        auth_method = getattr(request.state, "auth_method", None) if request and hasattr(request, "state") else None
        token_teams = getattr(request.state, "token_teams", None) if request and hasattr(request, "state") else None
        team_id = getattr(request.state, "team_id", None) if request and hasattr(request, "state") else None

        global_context.user_context = UserContext(
            user_id=user.email,
            email=user.email,
            full_name=user.full_name,
            is_admin=user.is_admin,
            teams=token_teams if isinstance(token_teams, list) else None,
            team_id=team_id,
            auth_method=auth_method,
            authenticated_at=datetime.now(timezone.utc),
        )

    if request and global_context:
        request.state.plugin_global_context = global_context
